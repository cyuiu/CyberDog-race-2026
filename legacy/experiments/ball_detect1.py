#!/usr/bin/env python3

import argparse
import os
import sys
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

# CyberDog 的 Ubuntu 18.04 默认 Python 通常是 3.6。
# Python 3.6 没有标准库 ThreadingHTTPServer，所以这里自己组合一个兼容版本。
class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

from pathlib import Path

# 这些是实体 CyberDog 上相机通信需要的 ROS2/DDS 环境变量。
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
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_FPS = 15


class PreviewState:
    """保存最新一帧 JPEG，供网页线程读取。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.jpeg = None
        self.status = "等待图像"


class PreviewHandler(BaseHTTPRequestHandler):
    """极简 MJPEG 网页服务，用浏览器查看实时标注画面。"""

    state = None

    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        if self.path == "/":
            self._send_index()
        elif self.path == "/latest.jpg":
            self._send_latest_jpg()
        elif self.path == "/stream.mjpg":
            self._send_stream()
        else:
            self.send_error(404)

    def _send_index(self):
        html = b"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>CyberDog Ball Detector</title>
<style>
body { margin: 0; background: #111; color: #eee; font-family: sans-serif; }
main { padding: 16px; }
img { max-width: 100%; border: 1px solid #444; }
code { color: #9fe; }
</style>
</head>
<body>
<main>
<h2>CyberDog Ball Detector</h2>
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

    def _get_jpeg(self):
        with self.state.lock:
            return self.state.jpeg

    def _send_latest_jpg(self):
        jpeg = self._get_jpeg()
        if jpeg is None:
            self.send_error(503, "还没有收到图像")
            return

        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(jpeg)))
        self.end_headers()
        self.wfile.write(jpeg)

    def _send_stream(self):
        self.send_response(200)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()

        while True:
            jpeg = self._get_jpeg()
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


def start_preview_server(state, host, port):
    PreviewHandler.state = state
    server = ThreadingHTTPServer((host, port), PreviewHandler)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    return server


class BallDetector(Node):
    """订阅 CyberDog RGB 图像，用 HSV 阈值检测球。"""

    def __init__(self, args, preview_state):
        super().__init__("ball_detect1")

        self.args = args
        self.preview_state = preview_state

        # 机器狗原生图像话题和相机服务。
        self.image_topic = f"{args.namespace}/image"
        self.camera_service_name = f"{args.namespace}/camera_service"

        # 我们自己统计的运行状态。
        self.frame_count = 0
        self.detect_count = 0

        self.capture_dir = Path(args.output_dir).expanduser()
        self.capture_dir.mkdir(parents=True, exist_ok=True)

        # 相机发布者使用 RELIABLE QoS，这里订阅者也使用 RELIABLE。
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
        # bgr 是我们转换出来给 OpenCV 使用的图像数组。
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

    def detect_ball(self, bgr):
        # HSV 比 RGB 更适合做颜色阈值分割。
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)

        lower = np.array([self.args.h_low, self.args.s_low, self.args.v_low], dtype=np.uint8)
        upper = np.array([self.args.h_high, self.args.s_high, self.args.v_high], dtype=np.uint8)

        mask = cv2.inRange(hsv, lower, upper)

        # 形态学开闭运算：去小噪点，补小空洞。
        kernel = np.ones((5, 5), dtype=np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return None, mask

        contour = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(contour)

        if area < self.args.min_area:
            return None, mask

        (x, y), radius = cv2.minEnclosingCircle(contour)
        moments = cv2.moments(contour)

        if moments["m00"] > 0:
            cx = int(moments["m10"] / moments["m00"])
            cy = int(moments["m01"] / moments["m00"])
        else:
            cx = int(x)
            cy = int(y)

        return {
            "center_x": cx,
            "center_y": cy,
            "area": float(area),
            "radius": float(radius),
            "offset_x": float(cx - bgr.shape[1] / 2),
            "offset_y": float(cy - bgr.shape[0] / 2),
        }, mask

    def draw_result(self, bgr, result):
        annotated = bgr.copy()

        if result is None:
            cv2.putText(annotated, "no ball", (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            return annotated

        cx = result["center_x"]
        cy = result["center_y"]
        radius = int(result["radius"])

        cv2.circle(annotated, (cx, cy), radius, (0, 255, 0), 2)
        cv2.circle(annotated, (cx, cy), 4, (0, 0, 255), -1)

        text = f"ball x={cx} y={cy} area={result['area']:.0f}"
        cv2.putText(annotated, text, (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

        return annotated

    def update_preview(self, annotated):
        ok, encoded = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), self.args.jpeg_quality])
        if not ok:
            return

        jpeg = encoded.tobytes()

        with self.preview_state.lock:
            self.preview_state.jpeg = jpeg
            self.preview_state.status = f"frame={self.frame_count}"

    def image_callback(self, msg):
        self.frame_count += 1

        try:
            bgr = self.image_to_bgr(msg)
            result, mask = self.detect_ball(bgr)
            annotated = self.draw_result(bgr, result)
            self.update_preview(annotated)
        except Exception as exc:
            self.get_logger().error(f"图像处理失败: {exc}")
            return

        if result is not None:
            self.detect_count += 1
            self.get_logger().info(
                "BALL "
                f"frame={self.frame_count} "
                f"center=({result['center_x']},{result['center_y']}) "
                f"offset=({result['offset_x']:.1f},{result['offset_y']:.1f}) "
                f"area={result['area']:.1f} "
                f"radius={result['radius']:.1f}"
            )
        elif self.frame_count % self.args.print_every == 0:
            self.get_logger().info(f"未检测到球 frame={self.frame_count}")

        should_save = self.frame_count == 1 or self.frame_count % self.args.save_every == 0 or result is not None

        if should_save:
            cv2.imwrite(str(self.capture_dir / "ball_detect_latest.jpg"), annotated)
            cv2.imwrite(str(self.capture_dir / "ball_detect_mask_latest.jpg"), mask)

            if result is not None:
                hit_path = self.capture_dir / f"ball_detect_hit_{self.detect_count:04d}.jpg"
                cv2.imwrite(str(hit_path), annotated)

    def run_until_done(self):
        self.get_logger().info(f"订阅图像话题: {self.image_topic}")
        self.get_logger().info(
            f"HSV阈值 H=[{self.args.h_low},{self.args.h_high}] "
            f"S=[{self.args.s_low},{self.args.s_high}] "
            f"V=[{self.args.v_low},{self.args.v_high}] "
            f"min_area={self.args.min_area}"
        )

        end_time = time.monotonic() + self.args.duration

        while rclpy.ok() and time.monotonic() < end_time:
            rclpy.spin_once(self, timeout_sec=0.1)

        self.get_logger().info(
            f"结束: frames={self.frame_count}, detections={self.detect_count}, "
            f"latest={self.capture_dir / 'ball_detect_latest.jpg'}"
        )


def parse_args():
    parser = argparse.ArgumentParser(description="CyberDog RGB 球识别 + 网页实时预览")
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--output-dir", default="/home/mi/cyberdog_course/program/captures")

    parser.add_argument("--web-host", default="0.0.0.0")
    parser.add_argument("--web-port", type=int, default=8080)
    parser.add_argument("--no-web", action="store_true")
    parser.add_argument("--jpeg-quality", type=int, default=85)

    parser.add_argument("--h-low", type=int, default=5)
    parser.add_argument("--h-high", type=int, default=25)
    parser.add_argument("--s-low", type=int, default=80)
    parser.add_argument("--s-high", type=int, default=255)
    parser.add_argument("--v-low", type=int, default=80)
    parser.add_argument("--v-high", type=int, default=255)

    parser.add_argument("--min-area", type=float, default=500.0)
    parser.add_argument("--print-every", type=int, default=15)
    parser.add_argument("--save-every", type=int, default=30)

    return parser.parse_args()


def main():
    args = parse_args()
    preview_state = PreviewState()
    server = None

    if not args.no_web:
        server = start_preview_server(preview_state, args.web_host, args.web_port)
        print(f"[WEB] open: http://<robot-ip>:{args.web_port}")

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
