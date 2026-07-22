#!/usr/bin/env python3

import ctypes
import errno
import os
import select
import struct
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from cyberdog_camera import CameraPreviewState, start_preview_server

try:
    import fcntl
    import mmap
except ImportError:  # pragma: no cover - 仅 Linux 机器狗提供
    fcntl = None
    mmap = None


V4L2_BUF_TYPE_VIDEO_CAPTURE = 1
V4L2_MEMORY_MMAP = 1
V4L2_FIELD_NONE = 1
V4L2_CAP_DEVICE_CAPS = 0x80000000
V4L2_CAP_VIDEO_CAPTURE = 0x00000001
V4L2_CAP_STREAMING = 0x04000000

POLL_EVENTS = select.POLLIN | select.POLLERR | select.POLLHUP


def _fourcc(a, b, c, d):
    return ord(a) | (ord(b) << 8) | (ord(c) << 16) | (ord(d) << 24)


V4L2_PIX_FMT_SRGGB10 = _fourcc("R", "G", "1", "0")


def _ioc(direction, type_char, number, size):
    return (direction << 30) | (size << 16) | (ord(type_char) << 8) | number


def _ior(type_char, number, size):
    return _ioc(2, type_char, number, size)


def _iow(type_char, number, size):
    return _ioc(1, type_char, number, size)


def _iowr(type_char, number, size):
    return _ioc(3, type_char, number, size)


VIDIOC_QUERYCAP = _ior("V", 0, 104)
VIDIOC_S_FMT = _iowr("V", 5, 208)
VIDIOC_REQBUFS = _iowr("V", 8, 20)
VIDIOC_QUERYBUF = _iowr("V", 9, 88)
VIDIOC_QBUF = _iowr("V", 15, 88)
VIDIOC_DQBUF = _iowr("V", 17, 88)
VIDIOC_STREAMON = _iow("V", 18, 4)
VIDIOC_STREAMOFF = _iow("V", 19, 4)


def _decode_c_string(data):
    return bytes(data).split(b"\0", 1)[0].decode("ascii", errors="replace")


def raw10_to_mono8(raw, width, height, bytes_per_line):
    """将 Tegra 输出的 16 位容器 RG10 数据缩放为 mono8。"""

    row_pixels = bytes_per_line // 2
    required = row_pixels * height
    pixels = np.frombuffer(raw, dtype="<u2", count=required)
    rows = pixels.reshape((height, row_pixels))[:, :width]
    return np.right_shift(rows, 2).astype(np.uint8)


class _V4L2Camera:
    """单个 OV9782 的最小 V4L2 MMAP 采集器。"""

    def __init__(self, device, width, height, buffer_count=4):
        self.device = device
        self.width = width
        self.height = height
        self.buffer_count = buffer_count
        self.fd = -1
        self.maps = []
        self.streaming = False
        self.bytes_per_line = 0
        self.size_image = 0

    def _ioctl(self, request, data):
        while True:
            try:
                fcntl.ioctl(self.fd, request, data, True)
                return
            except OSError as exc:
                if exc.errno != errno.EINTR:
                    raise

    def open(self):
        if fcntl is None or mmap is None:
            raise RuntimeError("V4L2 fisheye capture requires Linux")
        if ctypes.sizeof(ctypes.c_void_p) != 8:
            raise RuntimeError("V4L2 buffer layout currently supports 64-bit Linux only")

        self.fd = os.open(self.device, os.O_RDWR | os.O_NONBLOCK)

        capability = bytearray(104)
        self._ioctl(VIDIOC_QUERYCAP, capability)
        driver = _decode_c_string(capability[0:16])
        card = _decode_c_string(capability[16:48])
        capabilities = struct.unpack_from("<I", capability, 84)[0]
        device_caps = struct.unpack_from("<I", capability, 88)[0]
        effective_caps = device_caps if capabilities & V4L2_CAP_DEVICE_CAPS else capabilities

        required_caps = V4L2_CAP_VIDEO_CAPTURE | V4L2_CAP_STREAMING
        if effective_caps & required_caps != required_caps:
            raise RuntimeError(
                "{} is not a streaming capture device: caps=0x{:08x}".format(
                    self.device, effective_caps
                )
            )

        fmt = bytearray(208)
        struct.pack_into("<I", fmt, 0, V4L2_BUF_TYPE_VIDEO_CAPTURE)
        struct.pack_into(
            "<IIII",
            fmt,
            8,
            self.width,
            self.height,
            V4L2_PIX_FMT_SRGGB10,
            V4L2_FIELD_NONE,
        )
        self._ioctl(VIDIOC_S_FMT, fmt)

        actual_width, actual_height, actual_format = struct.unpack_from("<III", fmt, 8)
        self.bytes_per_line, self.size_image = struct.unpack_from("<II", fmt, 24)
        if (
            actual_width != self.width
            or actual_height != self.height
            or actual_format != V4L2_PIX_FMT_SRGGB10
        ):
            raise RuntimeError(
                "{} returned unsupported format: {}x{} fourcc=0x{:08x}".format(
                    self.device, actual_width, actual_height, actual_format
                )
            )

        request = bytearray(20)
        struct.pack_into(
            "<III",
            request,
            0,
            self.buffer_count,
            V4L2_BUF_TYPE_VIDEO_CAPTURE,
            V4L2_MEMORY_MMAP,
        )
        self._ioctl(VIDIOC_REQBUFS, request)
        actual_count = struct.unpack_from("<I", request, 0)[0]
        if actual_count < 2:
            raise RuntimeError("{} returned only {} buffers".format(self.device, actual_count))

        for index in range(actual_count):
            buf = self._buffer(index)
            self._ioctl(VIDIOC_QUERYBUF, buf)
            length = struct.unpack_from("<I", buf, 72)[0]
            offset = struct.unpack_from("<I", buf, 64)[0]
            mapping = mmap.mmap(
                self.fd,
                length,
                flags=mmap.MAP_SHARED,
                prot=mmap.PROT_READ | mmap.PROT_WRITE,
                offset=offset,
            )
            self.maps.append(mapping)
            self._ioctl(VIDIOC_QBUF, buf)

        print(
            "[V4L2] device={} driver={} card={} format=RG10 size={}x{} buffers={}".format(
                self.device, driver, card, self.width, self.height, len(self.maps)
            )
        )

    def _buffer(self, index=0):
        buf = bytearray(88)
        struct.pack_into("<I", buf, 0, index)
        struct.pack_into("<I", buf, 4, V4L2_BUF_TYPE_VIDEO_CAPTURE)
        struct.pack_into("<I", buf, 60, V4L2_MEMORY_MMAP)
        return buf

    def stream_on(self):
        arg = bytearray(struct.pack("<I", V4L2_BUF_TYPE_VIDEO_CAPTURE))
        self._ioctl(VIDIOC_STREAMON, arg)
        self.streaming = True

    def dequeue(self):
        buf = self._buffer()
        try:
            self._ioctl(VIDIOC_DQBUF, buf)
        except OSError as exc:
            if exc.errno == errno.EAGAIN:
                return None
            raise

        index = struct.unpack_from("<I", buf, 0)[0]
        bytes_used = struct.unpack_from("<I", buf, 8)[0]
        sequence = struct.unpack_from("<I", buf, 56)[0]
        if index >= len(self.maps):
            raise RuntimeError("{} returned invalid buffer index {}".format(self.device, index))

        try:
            raw = self.maps[index][:bytes_used]
            frame = raw10_to_mono8(raw, self.width, self.height, self.bytes_per_line)
        finally:
            self._ioctl(VIDIOC_QBUF, buf)

        return frame, sequence

    def close(self):
        if self.fd < 0:
            return

        if self.streaming:
            try:
                arg = bytearray(struct.pack("<I", V4L2_BUF_TYPE_VIDEO_CAPTURE))
                self._ioctl(VIDIOC_STREAMOFF, arg)
            except OSError as exc:
                print("[WARN] STREAMOFF {} failed: {}".format(self.device, exc))
            self.streaming = False

        for mapping in self.maps:
            mapping.close()
        self.maps = []
        os.close(self.fd)
        self.fd = -1


class CyberDogFisheyeCamera:
    """直接读取两颗 OV9782，并将左右灰度画面合成为网页预览。"""

    def __init__(
        self,
        left_device="/dev/video2",
        right_device="/dev/video3",
        width=640,
        height=400,
        preview_fps=15,
        enable_preview=True,
        web_host="0.0.0.0",
        web_port=8080,
        output_dir="/home/mi/cyberdog_course/program/captures",
        jpeg_quality=85,
    ):
        self.left_device = left_device
        self.right_device = right_device
        self.width = width
        self.height = height
        self.preview_fps = max(1, preview_fps)
        self.jpeg_quality = jpeg_quality

        self.capture_dir = Path(output_dir).expanduser()
        self.capture_dir.mkdir(parents=True, exist_ok=True)

        self.preview_state = CameraPreviewState()
        self.preview_server = None
        self.enable_preview = enable_preview
        self.web_host = web_host
        self.web_port = web_port

        self.stop_event = threading.Event()
        self.ready_event = threading.Event()
        self.worker = None
        self.last_error = None
        self.latest_frame = None
        self.frame_counts = {"left": 0, "right": 0}

    def start_camera(self, ready_timeout=8.0):
        self.worker = threading.Thread(target=self._capture_loop, daemon=True)
        self.worker.start()
        self.ready_event.wait(ready_timeout)
        if self.last_error is not None:
            print("[ERROR] Fisheye capture failed: {}".format(self.last_error))
            return False
        if not self.ready_event.is_set():
            print("[ERROR] Timed out waiting for both fisheye cameras")
            return False
        if self.enable_preview:
            self.preview_server = start_preview_server(
                self.preview_state, self.web_host, self.web_port
            )
        return True

    def _capture_loop(self):
        cameras = {
            "left": _V4L2Camera(self.left_device, self.width, self.height),
            "right": _V4L2Camera(self.right_device, self.width, self.height),
        }
        latest = {"left": None, "right": None}
        last_preview = 0.0

        try:
            for camera in cameras.values():
                camera.open()
            for camera in cameras.values():
                camera.stream_on()

            poller = select.poll()
            roles_by_fd = {}
            for role, camera in cameras.items():
                poller.register(camera.fd, POLL_EVENTS)
                roles_by_fd[camera.fd] = role

            print("[V4L2] Dual fisheye streaming started")

            while not self.stop_event.is_set():
                for fd, event in poller.poll(200):
                    role = roles_by_fd[fd]
                    if event & (select.POLLERR | select.POLLHUP):
                        raise RuntimeError("{} poll error: 0x{:x}".format(cameras[role].device, event))

                    result = cameras[role].dequeue()
                    if result is None:
                        continue

                    frame, _sequence = result
                    latest[role] = frame
                    self.frame_counts[role] += 1

                now = time.monotonic()
                if (
                    latest["left"] is not None
                    and latest["right"] is not None
                    and now - last_preview >= 1.0 / self.preview_fps
                ):
                    composite = self._compose(latest["left"], latest["right"])
                    self.latest_frame = composite
                    self._update_preview(composite)
                    last_preview = now
                    self.ready_event.set()

        except Exception as exc:
            self.last_error = exc
            self.ready_event.set()
        finally:
            for camera in reversed(list(cameras.values())):
                camera.close()

    def _compose(self, left, right):
        left_bgr = cv2.cvtColor(left, cv2.COLOR_GRAY2BGR)
        right_bgr = cv2.cvtColor(right, cv2.COLOR_GRAY2BGR)
        cv2.putText(left_bgr, "LEFT  {}".format(self.left_device), (12, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
        cv2.putText(right_bgr, "RIGHT  {}".format(self.right_device), (12, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
        return np.hstack((left_bgr, right_bgr))

    def _update_preview(self, frame):
        ok, encoded = cv2.imencode(
            ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality]
        )
        if not ok:
            return

        with self.preview_state.lock:
            self.preview_state.main_jpeg = encoded.tobytes()
            self.preview_state.status_text = "left={} right={}".format(
                self.frame_counts["left"], self.frame_counts["right"]
            )

    def spin_for(self, duration):
        end_time = time.monotonic() + duration
        while time.monotonic() < end_time:
            if self.last_error is not None:
                raise RuntimeError(str(self.last_error))
            time.sleep(0.1)

    def save_latest(self, filename="fisheye_view_latest.jpg"):
        if self.latest_frame is None:
            return None
        path = self.capture_dir / filename
        cv2.imwrite(str(path), self.latest_frame)
        return path

    def stop_camera(self):
        self.stop_event.set()
        if self.worker is not None:
            self.worker.join(timeout=3.0)
            if self.worker.is_alive():
                print("[WARN] Fisheye worker did not stop within 3 seconds")

    def close_preview(self):
        if self.preview_server is not None:
            self.preview_server.shutdown()
            self.preview_server.server_close()
            self.preview_server = None
