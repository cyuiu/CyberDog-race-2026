#!/usr/bin/env python3

import argparse
import sys

# 先导入 cyberdog_camera，让模块里的 ROS2/DDS 环境变量先设置好。
from cyberdog_camera import CyberDogCamera, DEFAULT_NAMESPACE
from cyberdog_fisheye import CyberDogFisheyeCamera

import rclpy


def parse_args():
    parser = argparse.ArgumentParser(description="CyberDog 相机预览")
    parser.add_argument("--source", choices=("rgb", "fisheye"), default="rgb")
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    parser.add_argument("--duration", type=float, default=3600.0)
    parser.add_argument("--web-host", default="0.0.0.0")
    parser.add_argument("--web-port", type=int, default=8080)
    parser.add_argument("--no-web", action="store_true")
    parser.add_argument("--output-dir", default="/home/mi/cyberdog_course/program/captures")
    parser.add_argument("--left-device", default="/dev/video2")
    parser.add_argument("--right-device", default="/dev/video3")
    parser.add_argument("--fisheye-width", type=int, default=640)
    parser.add_argument("--fisheye-height", type=int, default=400)
    return parser.parse_args()


def run_fisheye(args):
    camera = CyberDogFisheyeCamera(
        left_device=args.left_device,
        right_device=args.right_device,
        width=args.fisheye_width,
        height=args.fisheye_height,
        enable_preview=not args.no_web,
        web_host=args.web_host,
        web_port=args.web_port,
        output_dir=args.output_dir,
    )

    try:
        if not camera.start_camera():
            return 1
        print("[INFO] 双鱼眼预览运行中，duration={}s".format(args.duration))
        camera.spin_for(args.duration)
        camera.save_latest()
        return 0
    except KeyboardInterrupt:
        print("[WARN] 用户中断")
        return 130
    except Exception as exc:
        print("[ERROR] 双鱼眼预览失败: {}".format(exc))
        return 1
    finally:
        camera.stop_camera()
        camera.close_preview()


def run_rgb(args):
    rclpy.init()

    camera = CyberDogCamera(
        namespace=args.namespace,
        enable_preview=not args.no_web,
        web_host=args.web_host,
        web_port=args.web_port,
        output_dir=args.output_dir,
    )

    camera_started = False

    try:
        if not camera.start_camera():
            camera.get_logger().error("启动相机图像发布失败")
            return 1

        camera_started = True
        camera.get_logger().info(f"相机预览运行中，duration={args.duration}s")
        camera.spin_for(args.duration)
        camera.save_latest("camera_view_latest.jpg")
        return 0

    except KeyboardInterrupt:
        camera.get_logger().warning("用户中断")
        return 130

    finally:
        if camera_started:
            camera.stop_camera()

        camera.close_preview()
        camera.destroy_node()
        rclpy.shutdown()


def main():
    args = parse_args()

    if not args.no_web:
        print(f"[WEB] 机器狗本机: http://127.0.0.1:{args.web_port}")
        print(f"[WEB] 建议 SSH 隧道: ssh -N -L 18080:127.0.0.1:{args.web_port} cyberdog")
        print("[WEB] Ubuntu 浏览器打开: http://127.0.0.1:18080")

    if args.source == "fisheye":
        return run_fisheye(args)
    return run_rgb(args)


if __name__ == "__main__":
    sys.exit(main())
