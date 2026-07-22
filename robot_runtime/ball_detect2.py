#!/usr/bin/env python3

import argparse
import json
import os
import sys
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from pathlib import Path

# 实体 CyberDog 相机通信需要这些 ROS2/DDS 环境变量。
# 注意：必须在 import rclpy 和 rclpy.init() 之前设置。
os.environ.setdefault("RMW_IMPLEMENTATION", "rmw_cyclonedds_cpp")
os.environ.setdefault("CYCLONEDDS_URI", "file:///etc/mi/cyclonedds.xml")
os.environ.setdefault("ROS_DOMAIN_ID", "42")
os.environ.setdefault("ROS_LOCALHOST_ONLY", "0")

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image
from protocol.srv import CameraService


DEFAULT_NAMESPACE = "/mi_desktop_48_b0_2d_7b_05_1d"
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_FPS = 15


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class PreviewState:
    """网页线程和 ROS 图像线程共享的最新画面。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.annotated_jpeg = None
        self.blue_mask_jpeg = None
        self.orange_mask_jpeg = None
        self.status = {
            "frame": 0,
            "blue": None,
            "orange": None,
        }


class PreviewHandler(BaseHTTPRequestHandler):
    """极简网页服务：显示标注画面和 mask。"""

    state = None

    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        if self.path == "/":
            self.send_index()
        elif self.path == "/stream.mjpg":
            self.send_stream("annotated_jpeg")
        elif self.path == "/blue_mask.mjpg":
            self.send_stream("blue_mask_jpeg")
        elif self.path == "/orange_mask.mjpg":
            self.send_stream("orange_mask_jpeg")
        elif self.path == "/status.json":
            self.send_status_json()
        else:
            self.send_error(404)

    def send_index(self):
        html = b"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>CyberDog Ball Detector 2</title>
<style>
body { margin: 0; background: #111; color: #eee; font-family: sans-serif; }
main { padding: 16px; }
.grid { display: grid; grid-template-columns: 1fr; gap: 16px; max-width: 980px; }
img { max-width: 100%; border: 1px solid #444; background: #222; }
code { color: #9fe; }
</style>
</head>
<body>
<main>
<h2>CyberDog Ball Detector 2</h2>
<p>Annotated: <code>/stream.mjpg</code></p>
<div class="grid">
  <img src="/stream.mjpg">
  <div>
    <p>Blue mask</p>
    <img src="/blue_mask.mjpg">
  </div>
  <div>
    <p>Orange mask</p>
    <img src="/orange_mask.mjpg">
  </div>
</div>
</main>
</body>
</html>
"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def get_jpeg(self, attr):
        with self.state.lock:
            return getattr(self.state, attr)

    def send_stream(self, attr):
        self.send_response(200)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()

        while True:
            jpeg = self.get_jpeg(attr)
            if jpeg is not None:
                try:
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(jpeg)
                    self.wfile.write(b"\r\n")
                except BrokenPipeError:
                    break
            time.sleep(0.08)

    def send_status_json(self):
        with self.state.lock:
            data = json.dumps(self.state.status, ensure_ascii=False).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start_preview_server(state, host, port):
    PreviewHandler.state = state
    server = ThreadingHTTPServer((host, port), PreviewHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


class BallDetector(Node):
    """同时检测蓝球和橙球。"""

    def __init__(self, args, preview_state):
        super().__init__("ball_detect2")

        self.args = args
        self.preview_state = preview_state

        # 机器狗原生相机服务和图像话题。
        self.image_topic = f"{args.namespace}/image"
        self.camera_service_name = f"{args.namespace}/camera_service"

        # 我们自己维护的统计量。
        self.frame_count = 0
        self.blue_count = 0
        self.orange_count = 0

        self.capture_dir = Path(args.output_dir).expanduser()
        self.capture_dir.mkdir(parents=True, exist_ok=True)

        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
        )

        self.camera_client = self.create_client(CameraService, self.camera_service_name)
        self.image_sub = self.create_subscription(Image, self.image_topic, self.image_callback, qos)

    def call_camera_service(self, command, width=0, height=0, fps=0, label="camera"):
        self.get_logger().info(f"等待相机服务: {self.camera_service_name}")

        if not self.camera_client.wait_for_service(timeout_sec=8.0):
            self.get_logger().error(f"相机服务未就绪: {self.camera_service_name}")
            return False

        req = CameraService.Request()
        req.command = command
        req.args = ""
        req.width = width
        req.height = height
        req.fps = fps

        self.get_logger().info(f"调用 {label}: command={command}, width={width}, height={height}, fps={fps}")

        future = self.camera_client.call_async(req)
        rclpy.spin_until_future_complete(self, future, timeout_sec=15.0)

        if not future.done():
            self.get_logger().error(f"{label} 超时")
            return False

        res = future.result()
        if res is None:
            self.get_logger().error(f"{label} 没有返回结果")
            return False

        self.get_logger().info(f"{label} 返回: result={res.result}, code={res.code}, msg={res.msg!r}")
        return res.result == CameraService.Response.RESULT_SUCCESS

    def start_camera(self):
        return self.call_camera_service(
            CameraService.Request.START_IMAGE_PUBLISH,
            CAMERA_WIDTH,
            CAMERA_HEIGHT,
            CAMERA_FPS,
            "START_IMAGE_PUBLISH",
        )

    def stop_camera(self):
        return self.call_camera_service(
            CameraService.Request.STOP_IMAGE_PUBLISH,
            0,
            0,
            0,
            "STOP_IMAGE_PUBLISH",
        )

    def image_to_bgr(self, msg):
        # msg.encoding 是 ROS 图像消息里的原生字段。
        if msg.encoding not in ("bgr8", "rgb8", "mono8"):
            raise ValueError(f"暂不支持的图像格式: {msg.encoding}")

        data = np.frombuffer(msg.data, dtype=np.uint8)

        if msg.encoding == "mono8":
            image = data.reshape((msg.height, msg.step))[:, :msg.width]
            return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

        row_pixels = msg.step // 3
        image = data.reshape((msg.height, row_pixels, 3))[:, :msg.width, :]

        if msg.encoding == "rgb8":
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

        return image.copy()

    def make_mask(self, hsv, color_name):
        if color_name == "blue":
            lower = np.array([self.args.blue_h_low, self.args.blue_s_low, self.args.blue_v_low], dtype=np.uint8)
            upper = np.array([self.args.blue_h_high, self.args.blue_s_high, self.args.blue_v_high], dtype=np.uint8)
        elif color_name == "orange":
            lower = np.array([self.args.orange_h_low, self.args.orange_s_low, self.args.orange_v_low], dtype=np.uint8)
            upper = np.array([self.args.orange_h_high, self.args.orange_s_high, self.args.orange_v_high], dtype=np.uint8)
        else:
            raise ValueError(color_name)

        mask = cv2.inRange(hsv, lower, upper)

        kernel = np.ones((5, 5), dtype=np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        return mask

    def detect_one_color(self, bgr, hsv, color_name):
        mask = self.make_mask(hsv, color_name)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if color_name == "blue":
            min_area = self.args.blue_min_area
        else:
            min_area = self.args.orange_min_area

        if not contours:
            return None, mask

        contour = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(contour)

        if area < min_area:
            return None, mask

        (x, y), radius = cv2.minEnclosingCircle(contour)
        moments = cv2.moments(contour)

        if moments["m00"] > 0:
            cx = int(moments["m10"] / moments["m00"])
            cy = int(moments["m01"] / moments["m00"])
        else:
            cx = int(x)
            cy = int(y)

        result = {
            "color": color_name,
            "center_x": cx,
            "center_y": cy,
            "area": float(area),
            "radius": float(radius),
            "offset_x": float(cx - bgr.shape[1] / 2),
            "offset_y": float(cy - bgr.shape[0] / 2),
        }

        return result, mask

    def draw_result(self, bgr, blue_result, orange_result):
        annotated = bgr.copy()

        any_ball = False

        for result, draw_color, label in [
            (blue_result, (255, 80, 0), "BLUE"),
            (orange_result, (0, 165, 255), "ORANGE"),
        ]:
            if result is None:
                continue

            any_ball = True
            cx = result["center_x"]
            cy = result["center_y"]
            radius = int(result["radius"])

            cv2.circle(annotated, (cx, cy), radius, draw_color, 2)
            cv2.circle(annotated, (cx, cy), 4, (0, 0, 255), -1)

            text = f"{label} x={cx} y={cy} area={result['area']:.0f}"
            cv2.putText(annotated, text, (12, 32 if label == "BLUE" else 64),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.75, draw_color, 2)

        if not any_ball:
            cv2.putText(annotated, "no ball", (12, 32),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        return annotated

    def encode_jpeg(self, image):
        ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), self.args.jpeg_quality])
        if not ok:
            return None
        return encoded.tobytes()

    def update_preview(self, annotated, blue_mask, orange_mask, blue_result, orange_result):
        blue_mask_bgr = cv2.cvtColor(blue_mask, cv2.COLOR_GRAY2BGR)
        orange_mask_bgr = cv2.cvtColor(orange_mask, cv2.COLOR_GRAY2BGR)

        annotated_jpeg = self.encode_jpeg(annotated)
        blue_jpeg = self.encode_jpeg(blue_mask_bgr)
        orange_jpeg = self.encode_jpeg(orange_mask_bgr)

        with self.preview_state.lock:
            self.preview_state.annotated_jpeg = annotated_jpeg
            self.preview_state.blue_mask_jpeg = blue_jpeg
            self.preview_state.orange_mask_jpeg = orange_jpeg
            self.preview_state.status = {
                "frame": self.frame_count,
                "blue": blue_result,
                "orange": orange_result,
            }

    def image_callback(self, msg):
        self.frame_count += 1

        try:
            bgr = self.image_to_bgr(msg)
            hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)

            blue_result, blue_mask = self.detect_one_color(bgr, hsv, "blue")
            orange_result, orange_mask = self.detect_one_color(bgr, hsv, "orange")

            annotated = self.draw_result(bgr, blue_result, orange_result)
            self.update_preview(annotated, blue_mask, orange_mask, blue_result, orange_result)

        except Exception as exc:
            self.get_logger().error(f"图像处理失败: {exc}")
            return

        if blue_result is not None:
            self.blue_count += 1
            self.log_result("BLUE", blue_result)

        if orange_result is not None:
            self.orange_count += 1
            self.log_result("ORANGE", orange_result)

        if blue_result is None and orange_result is None and self.frame_count % self.args.print_every == 0:
            self.get_logger().info(f"未检测到蓝球/橙球 frame={self.frame_count}")

        should_save = (
            self.frame_count == 1
            or self.frame_count % self.args.save_every == 0
            or blue_result is not None
            or orange_result is not None
        )

        if should_save:
            cv2.imwrite(str(self.capture_dir / "ball2_latest.jpg"), annotated)
            cv2.imwrite(str(self.capture_dir / "ball2_blue_mask_latest.jpg"), blue_mask)
            cv2.imwrite(str(self.capture_dir / "ball2_orange_mask_latest.jpg"), orange_mask)

    def log_result(self, label, result):
        self.get_logger().info(
            f"{label} "
            f"frame={self.frame_count} "
            f"center=({result['center_x']},{result['center_y']}) "
            f"offset=({result['offset_x']:.1f},{result['offset_y']:.1f}) "
            f"area={result['area']:.1f} "
            f"radius={result['radius']:.1f}"
        )

    def run_until_done(self):
        self.get_logger().info(f"订阅图像话题: {self.image_topic}")
        self.get_logger().info(
            "蓝球HSV "
            f"H=[{self.args.blue_h_low},{self.args.blue_h_high}] "
            f"S=[{self.args.blue_s_low},{self.args.blue_s_high}] "
            f"V=[{self.args.blue_v_low},{self.args.blue_v_high}] "
            f"min_area={self.args.blue_min_area}"
        )
        self.get_logger().info(
            "橙球HSV "
            f"H=[{self.args.orange_h_low},{self.args.orange_h_high}] "
            f"S=[{self.args.orange_s_low},{self.args.orange_s_high}] "
            f"V=[{self.args.orange_v_low},{self.args.orange_v_high}] "
            f"min_area={self.args.orange_min_area}"
        )

        end_time = time.monotonic() + self.args.duration

        while rclpy.ok() and time.monotonic() < end_time:
            rclpy.spin_once(self, timeout_sec=0.1)

        self.get_logger().info(
            f"结束: frames={self.frame_count}, blue_hits={self.blue_count}, orange_hits={self.orange_count}"
        )


def parse_args():
    parser = argparse.ArgumentParser(description="CyberDog 蓝球/橙球 RGB 识别调参脚本")

    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    parser.add_argument("--duration", type=float, default=300.0)
    parser.add_argument("--output-dir", default="/home/mi/cyberdog_course/program/captures")

    parser.add_argument("--web-host", default="0.0.0.0")
    parser.add_argument("--web-port", type=int, default=8080)
    parser.add_argument("--no-web", action="store_true")
    parser.add_argument("--jpeg-quality", type=int, default=85)

    # 蓝球默认阈值：需要现场微调。
    parser.add_argument("--blue-h-low", type=int, default=85)
    parser.add_argument("--blue-h-high", type=int, default=130)
    parser.add_argument("--blue-s-low", type=int, default=50)
    parser.add_argument("--blue-s-high", type=int, default=255)
    parser.add_argument("--blue-v-low", type=int, default=40)
    parser.add_argument("--blue-v-high", type=int, default=255)
    parser.add_argument("--blue-min-area", type=float, default=800.0)

    # 橙球默认阈值：沿用上一版，但后续也要现场微调。
    parser.add_argument("--orange-h-low", type=int, default=5)
    parser.add_argument("--orange-h-high", type=int, default=25)
    parser.add_argument("--orange-s-low", type=int, default=80)
    parser.add_argument("--orange-s-high", type=int, default=255)
    parser.add_argument("--orange-v-low", type=int, default=80)
    parser.add_argument("--orange-v-high", type=int, default=255)
    parser.add_argument("--orange-min-area", type=float, default=500.0)

    parser.add_argument("--print-every", type=int, default=15)
    parser.add_argument("--save-every", type=int, default=30)

    return parser.parse_args()


def main():
    args = parse_args()
    preview_state = PreviewState()
    server = None

    if not args.no_web:
        server = start_preview_server(preview_state, args.web_host, args.web_port)
        print(f"[WEB] 机器狗本机: http://127.0.0.1:{args.web_port}")
        print(f"[WEB] 建议 SSH 隧道: ssh -N -L 18080:127.0.0.1:{args.web_port} cyberdog")
        print("[WEB] Ubuntu 浏览器打开: http://127.0.0.1:18080")

    rclpy.init()
    node = BallDetector(args, preview_state)

    camera_started = False

    try:
        if not node.start_camera():
            node.get_logger().error("启动相机图像发布失败")
            return 1

        camera_started = True
        node.run_until_done()
        return 0

    except KeyboardInterrupt:
        node.get_logger().warning("用户中断")
        return 130

    finally:
        if camera_started:
            node.stop_camera()

        node.destroy_node()
        rclpy.shutdown()

        if server is not None:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    sys.exit(main())
