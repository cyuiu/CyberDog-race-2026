#!/usr/bin/env python3

import argparse
import os
import re
import sys
import time

# 非交互 SSH 运行时也要显式使用 CyberDog 的 DDS 配置。
# 这些变量必须在 import rclpy 之前设置。
os.environ.setdefault("RMW_IMPLEMENTATION", "rmw_cyclonedds_cpp")
os.environ.setdefault("CYCLONEDDS_URI", "file:///etc/mi/cyclonedds.xml")
os.environ.setdefault("ROS_DOMAIN_ID", "42")
os.environ.setdefault("ROS_LOCALHOST_ONLY", "0")


IMAGE_TYPE = "sensor_msgs/msg/Image"
COMPRESSED_IMAGE_TYPE = "sensor_msgs/msg/CompressedImage"
SUPPORTED_IMAGE_TYPES = (IMAGE_TYPE, COMPRESSED_IMAGE_TYPE)
DISCOVERY_KEYWORDS = ("camera", "image", "left", "right", "fisheye", "stereo", "miloc", "mivins")


class TopicState:
    """保存我们自己的探测状态，不修改任何机器狗原生状态。"""

    def __init__(self, topic, role, message_type, source):
        self.topic = topic
        self.role = role
        self.message_type = message_type
        self.source = source
        self.publisher_count = 0
        self.offered_qos = []
        self.subscription_qos = "unknown"
        self.subscription = None
        self.frame_count = 0
        self.first_frame_time = None
        self.last_frame_time = None
        self.latest_metadata = ""

    def record_frame(self, msg):
        now = time.monotonic()
        self.frame_count += 1
        if self.first_frame_time is None:
            self.first_frame_time = now
        self.last_frame_time = now
        self.latest_metadata = describe_message(msg)

        if self.frame_count == 1:
            print(
                "[FRAME] topic={} role={} qos={} {}".format(
                    self.topic,
                    self.role,
                    self.subscription_qos,
                    self.latest_metadata,
                ),
                flush=True,
            )

    def rate_hz(self):
        if self.frame_count < 2 or self.first_frame_time == self.last_frame_time:
            return 0.0
        return (self.frame_count - 1) / (self.last_frame_time - self.first_frame_time)


def normalize_topic(topic):
    topic = topic.strip()
    if not topic:
        return ""
    if not topic.startswith("/"):
        topic = "/" + topic
    return topic.rstrip("/") or "/"


def classify_topic(topic):
    """根据话题名生成我们的角色标签；标签不是 ROS 消息字段。"""

    lower = topic.lower()
    tokens = set(part for part in re.split(r"[/_.-]+", lower) if part)

    if "left" in tokens:
        return "left"
    if "right" in tokens:
        return "right"
    if tokens.intersection(("fisheye", "stereo", "miloc", "mivins")):
        return "fisheye"
    if "rgb" in tokens or lower.endswith("/image"):
        return "rgb"
    return "image"


def describe_message(msg):
    header = getattr(msg, "header", None)
    stamp = getattr(header, "stamp", None)
    stamp_text = "{}.{}".format(
        getattr(stamp, "sec", 0),
        str(getattr(stamp, "nanosec", 0)).zfill(9),
    )
    frame_id = getattr(header, "frame_id", "")
    data_size = len(getattr(msg, "data", b""))

    if hasattr(msg, "height") and hasattr(msg, "width"):
        return (
            "stamp={} frame_id={!r} size={}x{} encoding={} step={} bytes={}".format(
                stamp_text,
                frame_id,
                msg.width,
                msg.height,
                getattr(msg, "encoding", ""),
                getattr(msg, "step", 0),
                data_size,
            )
        )

    return "stamp={} frame_id={!r} format={!r} bytes={}".format(
        stamp_text,
        frame_id,
        getattr(msg, "format", ""),
        data_size,
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="只读探测 CyberDog 左右鱼眼图像话题，不调用服务或运动接口。"
    )
    parser.add_argument("--duration", type=float, default=12.0, help="探测总时长，默认 12 秒")
    parser.add_argument("--min-frames", type=int, default=3, help="判定有稳定数据所需的最少帧数")
    parser.add_argument("--namespace", help="可选的机器狗命名空间，用于补充 image_left/right 候选")
    parser.add_argument("--left-topic", help="明确指定左鱼眼话题")
    parser.add_argument("--right-topic", help="明确指定右鱼眼话题")
    parser.add_argument("--topic", action="append", default=[], help="追加候选图像话题，可重复使用")
    parser.add_argument(
        "--qos",
        choices=("auto", "reliable", "best_effort"),
        default="auto",
        help="订阅可靠性；auto 会优先匹配发布者，无发布者信息时使用 reliable",
    )
    parser.add_argument(
        "--require",
        choices=("both", "any"),
        default="both",
        help="成功条件：左右两路都有数据，或任一非 RGB 候选有数据",
    )
    return parser.parse_args(argv)


def choose_message_type(types):
    if IMAGE_TYPE in types:
        return IMAGE_TYPE
    if COMPRESSED_IMAGE_TYPE in types:
        return COMPRESSED_IMAGE_TYPE
    return None


def reliability_label(value):
    name = getattr(value, "name", str(value)).upper()
    if "BEST_EFFORT" in name or "BEST EFFORT" in name:
        return "best_effort"
    if "RELIABLE" in name:
        return "reliable"
    return name.lower()


def inspect_publishers(node, topic):
    try:
        infos = list(node.get_publishers_info_by_topic(topic))
    except (AttributeError, RuntimeError):
        infos = []

    if infos:
        labels = sorted(
            set(reliability_label(info.qos_profile.reliability) for info in infos)
        )
        return len(infos), labels, infos

    try:
        count = node.count_publishers(topic)
    except (AttributeError, RuntimeError):
        count = 0
    return count, [], infos


def choose_subscription_qos(args, infos, ReliabilityPolicy):
    if args.qos == "reliable":
        return ReliabilityPolicy.RELIABLE, "reliable"
    if args.qos == "best_effort":
        return ReliabilityPolicy.BEST_EFFORT, "best_effort"

    offered = [getattr(info.qos_profile, "reliability", None) for info in infos]
    if ReliabilityPolicy.BEST_EFFORT in offered:
        return ReliabilityPolicy.BEST_EFFORT, "best_effort"
    return ReliabilityPolicy.RELIABLE, "reliable"


def collect_candidates(node, explicit_roles, requested_namespace=None):
    topic_types = dict(node.get_topic_names_and_types())
    candidates = {}

    for topic, role in explicit_roles.items():
        message_type = choose_message_type(topic_types.get(topic, [])) or IMAGE_TYPE
        candidates[topic] = (role, message_type, "explicit")

    namespaces = set()
    for topic, types in topic_types.items():
        message_type = choose_message_type(types)
        if message_type is None:
            continue

        candidates.setdefault(topic, (classify_topic(topic), message_type, "graph"))
        if topic.endswith("/image"):
            namespaces.add(topic[: -len("/image")])

    try:
        services = node.get_service_names_and_types()
    except (AttributeError, RuntimeError):
        services = []

    for service, _types in services:
        if service.endswith("/camera_service"):
            namespaces.add(service[: -len("/camera_service")])

    if requested_namespace:
        namespaces.add(requested_namespace)

    # 即使图中暂时没有这些话题，也创建只读订阅，从 publisher=0 与 QoS 问题中区分原因。
    candidates.setdefault("/image_left", ("left", IMAGE_TYPE, "common-name"))
    candidates.setdefault("/image_right", ("right", IMAGE_TYPE, "common-name"))
    for namespace in namespaces:
        namespace = normalize_topic(namespace)
        candidates.setdefault(namespace + "/image_left", ("left", IMAGE_TYPE, "namespace-guess"))
        candidates.setdefault(namespace + "/image_right", ("right", IMAGE_TYPE, "namespace-guess"))

    return candidates, topic_types


def matching_nodes(node):
    try:
        nodes = node.get_node_names_and_namespaces()
    except (AttributeError, RuntimeError):
        return []

    matches = []
    for name, namespace in nodes:
        full_name = (namespace.rstrip("/") + "/" + name).replace("//", "/")
        if any(keyword in full_name.lower() for keyword in DISCOVERY_KEYWORDS):
            matches.append(full_name)
    return sorted(set(matches))


def main(argv=None):
    args = parse_args(argv)
    if args.duration <= 0 or args.min_frames <= 0:
        print("[ERROR] duration 和 min-frames 必须大于 0", flush=True)
        return 64

    try:
        import rclpy
        from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
        from sensor_msgs.msg import CompressedImage, Image
    except ImportError as exc:
        print("[ERROR] 缺少机器狗 ROS2 环境: {}".format(exc), flush=True)
        return 69

    message_classes = {
        IMAGE_TYPE: Image,
        COMPRESSED_IMAGE_TYPE: CompressedImage,
    }

    explicit_roles = {}
    if args.left_topic:
        explicit_roles[normalize_topic(args.left_topic)] = "left"
    if args.right_topic:
        explicit_roles[normalize_topic(args.right_topic)] = "right"
    for topic in args.topic:
        normalized = normalize_topic(topic)
        if normalized:
            explicit_roles.setdefault(normalized, classify_topic(normalized))
    requested_namespace = normalize_topic(args.namespace) if args.namespace else None

    print("[ENV] RMW_IMPLEMENTATION={}".format(os.environ.get("RMW_IMPLEMENTATION")), flush=True)
    print("[ENV] CYCLONEDDS_URI={}".format(os.environ.get("CYCLONEDDS_URI")), flush=True)
    print("[ENV] ROS_DOMAIN_ID={}".format(os.environ.get("ROS_DOMAIN_ID")), flush=True)
    print("[ENV] ROS_LOCALHOST_ONLY={}".format(os.environ.get("ROS_LOCALHOST_ONLY")), flush=True)
    print("[INFO] 只读探测，不调用 camera_service、lifecycle 或运动接口。", flush=True)

    rclpy.init(args=[])
    node = rclpy.create_node("fisheye_probe")
    states = {}
    seen_graph_topics = set()
    seen_nodes = set()
    start_time = time.monotonic()
    deadline = start_time + args.duration
    next_refresh = 0.0
    next_progress = start_time + 3.0

    def install_subscription(state, infos):
        reliability, label = choose_subscription_qos(args, infos, ReliabilityPolicy)
        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=reliability,
        )

        if state.subscription is not None:
            node.destroy_subscription(state.subscription)

        msg_class = message_classes[state.message_type]
        state.subscription_qos = label
        state.subscription = node.create_subscription(
            msg_class,
            state.topic,
            lambda msg, current=state: current.record_frame(msg),
            qos,
        )
        print(
            "[SUB] topic={} role={} type={} source={} publishers={} offered_qos={} subscribe_qos={}".format(
                state.topic,
                state.role,
                state.message_type,
                state.source,
                state.publisher_count,
                ",".join(state.offered_qos) or "unknown",
                state.subscription_qos,
            ),
            flush=True,
        )

    try:
        while rclpy.ok() and time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_refresh:
                candidates, topic_types = collect_candidates(
                    node,
                    explicit_roles,
                    requested_namespace,
                )

                for topic, types in sorted(topic_types.items()):
                    if choose_message_type(types) and topic not in seen_graph_topics:
                        print("[GRAPH] image_topic={} types={}".format(topic, ",".join(types)), flush=True)
                        seen_graph_topics.add(topic)

                for node_name in matching_nodes(node):
                    if node_name not in seen_nodes:
                        print("[GRAPH] related_node={}".format(node_name), flush=True)
                        seen_nodes.add(node_name)

                for topic, (role, message_type, source) in sorted(candidates.items()):
                    if topic == "__namespace__":
                        continue

                    count, offered_qos, infos = inspect_publishers(node, topic)
                    state = states.get(topic)
                    if state is None:
                        state = TopicState(topic, role, message_type, source)
                        states[topic] = state
                    elif source == "graph" and state.source != "explicit":
                        state.role = role
                        state.source = source
                    state.publisher_count = count
                    state.offered_qos = offered_qos

                    desired_qos = choose_subscription_qos(args, infos, ReliabilityPolicy)[1]
                    type_changed = state.message_type != message_type and state.frame_count == 0
                    qos_changed = state.subscription_qos != desired_qos and state.frame_count == 0
                    if type_changed:
                        state.message_type = message_type
                    if state.subscription is None or type_changed or qos_changed:
                        install_subscription(state, infos)

                next_refresh = now + 0.75

            rclpy.spin_once(node, timeout_sec=0.15)

            if time.monotonic() >= next_progress:
                active = sum(1 for state in states.values() if state.frame_count > 0)
                print(
                    "[WAIT] elapsed={:.1f}s subscribed={} receiving={}".format(
                        time.monotonic() - start_time,
                        len(states),
                        active,
                    ),
                    flush=True,
                )
                next_progress += 3.0

    except KeyboardInterrupt:
        print("[INFO] 用户中断探测", flush=True)
    finally:
        print("[SUMMARY]", flush=True)
        for state in sorted(states.values(), key=lambda item: item.topic):
            print(
                (
                    "[TOPIC] topic={} role={} type={} publishers={} offered_qos={} "
                    "subscribe_qos={} frames={} rate_hz={:.2f} latest={}"
                ).format(
                    state.topic,
                    state.role,
                    state.message_type,
                    state.publisher_count,
                    ",".join(state.offered_qos) or "unknown",
                    state.subscription_qos,
                    state.frame_count,
                    state.rate_hz(),
                    state.latest_metadata or "none",
                ),
                flush=True,
            )

        node.destroy_node()
        rclpy.shutdown()

    left_ready = any(
        state.role == "left" and state.frame_count >= args.min_frames for state in states.values()
    )
    right_ready = any(
        state.role == "right" and state.frame_count >= args.min_frames for state in states.values()
    )
    non_rgb_ready = any(
        state.role != "rgb" and state.frame_count >= args.min_frames for state in states.values()
    )
    success = left_ready and right_ready if args.require == "both" else non_rgb_ready

    print("LEFT_READY={}".format("yes" if left_ready else "no"), flush=True)
    print("RIGHT_READY={}".format("yes" if right_ready else "no"), flush=True)
    print("FISHEYE_PAIR_READY={}".format("yes" if left_ready and right_ready else "no"), flush=True)

    if success:
        print("RESULT=READY", flush=True)
        return 0
    if not any(state.publisher_count > 0 for state in states.values()):
        print("RESULT=NO_PUBLISHER", flush=True)
        return 2
    if not any(state.frame_count > 0 for state in states.values()):
        print("RESULT=PUBLISHER_WITHOUT_FRAMES", flush=True)
        return 3

    print("RESULT=PARTIAL_DATA", flush=True)
    return 4


if __name__ == "__main__":
    sys.exit(main())
