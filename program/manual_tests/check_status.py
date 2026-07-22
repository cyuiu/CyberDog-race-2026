#!/usr/bin/env python3

import sys
import time

import rclpy
from rclpy.node import Node
from protocol.msg  import MotionStatus

MOTION_STATUS_TOPIC = "/custom_namespace/motion_status"
STATUS_TIMEOUT = 5.0  # seconds
SAFE_STATUS = 0

class StatusChecker(Node):
    def __init__(self):
        super().__init__("status_checker")

        self.latest_status = None

        self.status_sub = self.create_subscription(
            MotionStatus,
            MOTION_STATUS_TOPIC,
            self.status_callback,
            10,
        )

    def status_callback(self, msg):
        self.latest_status = msg

    def wait_for_status(self):
        self.get_logger().info(f"Waiting for topic: {MOTION_STATUS_TOPIC}")

        end_time = time.monotonic() + STATUS_TIMEOUT

        while time.monotonic() < end_time and rclpy.ok():
            rclpy.spin_once(self, timeout_sec=0.1)

            if self.latest_status is not None:
                self.get_logger().info("Received motion status.")
                return True

        self.get_logger().error("Timeout waiting for motion status.")
        return False
    
    def switch_status_name(self, switch_status):
        status_names = {
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
        return status_names.get(switch_status, f"UNKNOWN_STATUS_{switch_status}")
    
    def is_status_safe(self):
        if self.latest_status is None:
            self.get_logger().error("Cannot check safety: no motion status.")
            return False

        switch_status = self.latest_status.switch_status
        status_name = self.switch_status_name(switch_status)

        if switch_status == SAFE_STATUS:
            self.get_logger().info(f"Motion status is safe: {status_name}")
            return True

        self.get_logger().warning(f"Motion status is unsafe: {status_name}")
        return False
    
def main():
    rclpy.init()

    checker = StatusChecker()

    try:
        if not checker.wait_for_status():
            ok = False
        else:
            ok = checker.is_status_safe()
    finally:
        checker.destroy_node()
        rclpy.shutdown()

    if ok:
        print("OK: robot motion status is safe.")
        sys.exit(0)

    print("FAILED: robot motion status is not ready or unsafe.")
    sys.exit(1)


if __name__ == "__main__":
    main()
 
