#!/usr/bin/env python3

import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from pathlib import Path

# 实体 CyberDog 相机通信需要这些 ROS2/DDS 环境变量。
# 必须在 import rclpy 和 rclpy.init() 之前设置。
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
DEFAULT_WIDTH = 640
DEFAULT_HEIGHT = 480
DEFAULT_FPS = 15


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """兼容 Python 3.6 的多线程 HTTPServer。"""

    daemon_threads = True


class CameraPreviewState:
    """网页线程和 ROS 图像线程共享的最新画面。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.main_jpeg = None
        self.status_text = "等待图像"


class CameraPreviewHandler(BaseHTTPRequestHandler):
    """极简 MJPEG 网页服务，用浏览器查看相机画面。"""

    state = None

    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        if self.path == "/":
            self.send_index()
        elif self.path == "/stream.mjpg":
            self.send_stream()
        else:
            self.send_error(404)

    def send_index(self):
        html = b"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>CyberDog Camera View</title>
<style>
body { margin: 0; background: #111; color: #eee; font-family: sans-serif; }
main { padding: 16px; }
img { max-width: 100%; border: 1px solid #444; background: #222; }
code { color: #9fe; }
</style>
</head>
<body>
<main>
<h2>CyberDog Camera View</h2>
<p>Live stream: <code>/stream.mjpg</code></p>
<img src="/stream.mjpg">
</main>
</body>
</html>
"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def get_jpeg(self):
        with self.state.lock:
            return self.state.main_jpeg

    def send_stream(self):
        self.send_response(200)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()

        while True:
            jpeg = self.get_jpeg()
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


def start_preview_server(state, host="0.0.0.0", port=8080):
    CameraPreviewHandler.state = state
    server = ThreadingHTTPServer((host, port), CameraPreviewHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


class CyberDogCamera(Node):
    """CyberDog RGB 相机基础模块。

    这个类只负责：
    1. 调 camera_service 启动/停止图像发布。
    2. 订阅 ROS Image。
    3. 转成 OpenCV BGR frame。
    4. 保存 latest_frame。
    5. 可选网页预览。

    它不负责蓝球、橙球、黄线、石板等具体识别算法。
    """

    def __init__(
        self,
        namespace=DEFAULT_NAMESPACE,
        width=DEFAULT_WIDTH,
        height=DEFAULT_HEIGHT,
        fps=DEFAULT_FPS,
        enable_preview=True,
        web_host="0.0.0.0",
        web_port=8080,
        output_dir="/home/mi/cyberdog_course/program/captures",
        jpeg_quality=85,
    ):
        super().__init__("cyberdog_camera")

        self.namespace = namespace
        self.width = width
        self.height = height
        self.fps = fps
        self.jpeg_quality = jpeg_quality

        # 机器狗原生相机服务和图像话题。
        self.image_topic = f"{namespace}/image"
        self.camera_service_name = f"{namespace}/camera_service"

        # 我们自己维护的运行状态。
        self.frame_count = 0
        self.latest_frame = None
        self.latest_msg = None
        self.latest_stamp = None

        self.capture_dir = Path(output_dir).expanduser()
        self.capture_dir.mkdir(parents=True, exist_ok=True)

        self.preview_state = CameraPreviewState()
        self.preview_server = None

        if enable_preview:
            self.preview_server = start_preview_server(self.preview_state, web_host, web_port)

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
        """启动相机图像发布。

        实体机上有时会出现 START_IMAGE_PUBLISH 返回 result=5 的情况。
        这个结果在 CameraService 里表示 RESULT_INVALID_STATE，常见原因是上一次
        图像发布没有被正常停止，服务端状态还没清干净。

        所以这里采用保守策略：
        1. 先正常 START。
        2. 如果失败，先 STOP 一次。
        3. 等 1 秒后再 START 重试一次。
        """

        ok = self.call_camera_service(
            CameraService.Request.START_IMAGE_PUBLISH,
            self.width,
            self.height,
            self.fps,
            "START_IMAGE_PUBLISH",
        )

        if ok:
            return True

        self.get_logger().warning("第一次启动相机失败，尝试先停止图像发布再重启。")

        self.call_camera_service(
            CameraService.Request.STOP_IMAGE_PUBLISH,
            0,
            0,
            0,
            "STOP_IMAGE_PUBLISH_BEFORE_RETRY",
        )

        time.sleep(1.0)

        return self.call_camera_service(
            CameraService.Request.START_IMAGE_PUBLISH,
            self.width,
            self.height,
            self.fps,
            "START_IMAGE_PUBLISH_RETRY",
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
        """把 ROS Image 转成 OpenCV 使用的 BGR 图像。"""

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

    def image_callback(self, msg):
        self.frame_count += 1

        try:
            frame = self.image_to_bgr(msg)
        except Exception as exc:
            self.get_logger().error(f"图像转换失败: {exc}")
            return

        self.latest_frame = frame
        self.latest_msg = msg
        self.latest_stamp = msg.header.stamp

        self.update_preview(frame)

    def update_preview(self, frame):
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
        if not ok:
            return

        with self.preview_state.lock:
            self.preview_state.main_jpeg = encoded.tobytes()
            self.preview_state.status_text = f"frame={self.frame_count}"

    def save_latest(self, filename="camera_latest.jpg"):
        if self.latest_frame is None:
            return None

        path = self.capture_dir / filename
        cv2.imwrite(str(path), self.latest_frame)
        return path

    def spin_for(self, duration):
        end_time = time.monotonic() + duration

        while rclpy.ok() and time.monotonic() < end_time:
            rclpy.spin_once(self, timeout_sec=0.1)

    def close_preview(self):
        if self.preview_server is not None:
            self.preview_server.shutdown()
            self.preview_server.server_close()
            self.preview_server = None
