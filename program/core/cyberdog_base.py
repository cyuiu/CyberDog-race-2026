#!/usr/bin/env python3

import time

import rclpy
from rclpy.node import Node

from protocol.msg import MotionServoCmd
from protocol.msg import MotionStatus
from protocol.srv import MotionResultCmd


MOTION_STATUS_TOPIC = "/custom_namespace/motion_status"
MOTION_RESULT_SERVICE = "/custom_namespace/motion_result_cmd"
MOTION_SERVO_TOPIC = "/custom_namespace/motion_servo_cmd"

SAFE_SWITCH_STATUS = 0
STATUS_TIMEOUT = 5.0
SERVICE_TIMEOUT = 5.0
ACTION_TIMEOUT = 30.0

MAX_X = 0.12
MAX_Y = 0.05
MAX_YAW = 0.35
MAX_DURATION = 2.0


def clamp(value, low, high):
    return max(low, min(high, value))


class CyberDogBaseNode(Node):
    def __init__(self, node_name="cyberdog_console"):
        super().__init__(node_name)

        self.latest_status = None

        self.status_sub = self.create_subscription(
            MotionStatus,
            MOTION_STATUS_TOPIC,
            self.status_callback,
            10,
        )

        self.motion_client = self.create_client(
            MotionResultCmd,
            MOTION_RESULT_SERVICE,
        )

        self.servo_pub = self.create_publisher(
            MotionServoCmd,
            MOTION_SERVO_TOPIC,
            10,
        )

    def status_callback(self, msg):
        self.latest_status = msg

    def wait_for_status(self, timeout_sec=STATUS_TIMEOUT):
        self.latest_status = None
        self.get_logger().info(f"等待话题: {MOTION_STATUS_TOPIC}")

        end_time = time.monotonic() + timeout_sec
        while time.monotonic() < end_time and rclpy.ok():
            rclpy.spin_once(self, timeout_sec=0.1)
            if self.latest_status is not None:
                self.get_logger().info("已收到运动状态。")
                return True

        self.get_logger().error("等待运动状态超时。")
        return False

    def switch_status_name(self, switch_status):
        names = {
            0: "NORMAL",
            1: "TRANSITIONING",
            2: "ESTOP",
            3: "EDAMP",
            4: "LIFTED",
            5: "BAN_TRANS",
            6: "OVER_HEAT",
            7: "LOW_BAT",
            8: "ORI_ERR",
            9: "FOOTPOS_ERR",
            10: "STAND_STUCK",
            11: "MOTOR_OVER_HEAT",
            12: "MOTOR_OVER_CURR",
            13: "MOTOR_ERR",
            14: "CHARGING",
        }
        return names.get(switch_status, f"UNKNOWN_STATUS_{switch_status}")

    def is_status_safe(self):
        if self.latest_status is None:
            self.get_logger().error("无法检查安全状态：未收到运动状态。")
            return False

        switch_status = self.latest_status.switch_status
        status_name = self.switch_status_name(switch_status)

        if switch_status == SAFE_SWITCH_STATUS:
            self.get_logger().info(f"运动状态安全: {status_name}")
            return True

        self.get_logger().error(f"运动状态不安全: {status_name}")
        return False

    def ensure_safe_status(self):
        if not self.wait_for_status():
            return False
        return self.is_status_safe()

    def wait_for_motion_service(self):
        self.get_logger().info(f"等待服务: {MOTION_RESULT_SERVICE}")

        end_time = time.monotonic() + SERVICE_TIMEOUT
        while time.monotonic() < end_time and rclpy.ok():
            if self.motion_client.wait_for_service(timeout_sec=0.5):
                self.get_logger().info("运动服务已就绪。")
                return True

        self.get_logger().error("运动服务不可用。")
        return False

    def call_motion_result(self, motion_id, action_name, timeout_sec=ACTION_TIMEOUT):
        request = MotionResultCmd.Request()
        request.motion_id = int(motion_id)
        request.cmd_source = MotionResultCmd.Request.APP

        self.get_logger().info(f"调用 {action_name}: motion_id={request.motion_id}")
        future = self.motion_client.call_async(request)

        end_time = time.monotonic() + timeout_sec
        while time.monotonic() < end_time and rclpy.ok():
            rclpy.spin_once(self, timeout_sec=0.1)

            if future.done():
                try:
                    response = future.result()
                except Exception as exc:
                    self.get_logger().error(f"{action_name} 服务错误: {exc}")
                    return False

                self.get_logger().info(
                    f"{action_name} 响应: "
                    f"motion_id={response.motion_id}, "
                    f"result={response.result}, "
                    f"code={response.code}"
                )
                return bool(response.result)

        self.get_logger().error(f"{action_name} 命令超时。")
        return False

    def run_motion_action(self, action):
        if not self.ensure_safe_status():
            return False
        if not self.wait_for_motion_service():
            return False
        return self.call_motion_result(action["motion_id"], action["name"])

    def make_servo_cmd(self, motion_id, vel, step_height):
        cmd = MotionServoCmd()
        cmd.motion_id = int(motion_id)
        cmd.cmd_source = getattr(MotionServoCmd, "APP", 0)
        cmd.cmd_type = getattr(MotionServoCmd, "SERVO_DATA", 1)
        cmd.vel_des.fromlist([float(vel[0]), float(vel[1]), float(vel[2])])
        cmd.step_height.fromlist([float(step_height[0]), float(step_height[1])])
        return cmd

    def publish_servo_end(self, motion_id):
        cmd = MotionServoCmd()
        cmd.motion_id = int(motion_id)
        cmd.cmd_source = getattr(MotionServoCmd, "APP", 0)
        cmd.cmd_type = getattr(MotionServoCmd, "SERVO_END", 2)
        self.servo_pub.publish(cmd)

    def stop_servo(self, motion_id=345):
        self.get_logger().warning("正在发布 SERVO_END。")
        for _ in range(3):
            self.publish_servo_end(motion_id)
            rclpy.spin_once(self, timeout_sec=0.05)
            time.sleep(0.05)
        return True

    def run_servo_gait(self, gait):
        if gait.get("type") == "stop":
            return self.stop_servo(gait.get("motion_id", 345))

        if not self.ensure_safe_status():
            return False

        motion_id = int(gait["motion_id"])
        duration = min(float(gait.get("duration", 1.0)), MAX_DURATION)
        raw_vel = gait["vel"]

        vel = [
            clamp(float(raw_vel[0]), -MAX_X, MAX_X),
            clamp(float(raw_vel[1]), -MAX_Y, MAX_Y),
            clamp(float(raw_vel[2]), -MAX_YAW, MAX_YAW),
        ]

        step_height = gait.get("step_height", [0.04, 0.04])

        self.get_logger().info(
            f"执行步态 {gait['name']}: "
            f"motion_id={motion_id}, vel={vel}, duration={duration}"
        )

        end_time = time.monotonic() + duration
        try:
            while time.monotonic() < end_time and rclpy.ok():
                cmd = self.make_servo_cmd(motion_id, vel, step_height)
                self.servo_pub.publish(cmd)
                rclpy.spin_once(self, timeout_sec=0.0)
                time.sleep(0.05)
            return True
        finally:
            self.stop_servo(motion_id)
