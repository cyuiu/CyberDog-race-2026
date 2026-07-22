#!/usr/bin/env python3

import sys
import time

import rclpy
from rclpy.node import Node

from protocol.msg import MotionID
from protocol.msg import MotionStatus
from protocol.srv import MotionResultCmd


MOTION_STATUS_TOPIC = "/custom_namespace/motion_status"
MOTION_RESULT_SERVICE = "/custom_namespace/motion_result_cmd"

STATUS_TIMEOUT = 5.0
SERVICE_TIMEOUT = 5.0
STAND_TIMEOUT = 25.0

SAFE_SWITCH_STATUS = 0
RECOVERY_STAND_ID = getattr(MotionID, "RECOVERYSTAND", 111)


class StandOnce(Node):
    def __init__(self):
        super().__init__("stand1")

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

    def is_status_safe(self):
        if self.latest_status is None:
            self.get_logger().error("Cannot check safety: no motion status.")
            return False

        switch_status = self.latest_status.switch_status
        if switch_status == SAFE_SWITCH_STATUS:
            self.get_logger().info("Motion status is safe: NORMAL.")
            return True

        self.get_logger().error(f"Motion status is unsafe: switch_status={switch_status}")
        return False

    def wait_for_motion_service(self):
        self.get_logger().info(f"Waiting for service: {MOTION_RESULT_SERVICE}")

        end_time = time.monotonic() + SERVICE_TIMEOUT
        while time.monotonic() < end_time and rclpy.ok():
            if self.motion_client.wait_for_service(timeout_sec=0.5):
                self.get_logger().info("Motion service is ready.")
                return True

        self.get_logger().error("Motion service is not available.")
        return False

    def call_recovery_stand(self):
        request = MotionResultCmd.Request()
        request.motion_id = RECOVERY_STAND_ID
        request.cmd_source = MotionResultCmd.Request.APP

        self.get_logger().info(f"Calling recovery stand: motion_id={request.motion_id}")

        future = self.motion_client.call_async(request)

        end_time = time.monotonic() + STAND_TIMEOUT
        while time.monotonic() < end_time and rclpy.ok():
            rclpy.spin_once(self, timeout_sec=0.1)

            if future.done():
                response = future.result()
                self.get_logger().info(
                    "Stand response: "
                    f"motion_id={response.motion_id}, "
                    f"result={response.result}, "
                    f"code={response.code}"
                )
                return bool(response.result)

        self.get_logger().error("Recovery stand command timeout.")
        return False

    def run(self):
        if not self.wait_for_status():
            return False

        if not self.is_status_safe():
            return False

        if not self.wait_for_motion_service():
            return False

        return self.call_recovery_stand()


def main():
    rclpy.init()
    node = StandOnce()

    try:
        ok = node.run()
    finally:
        node.destroy_node()
        rclpy.shutdown()

    if ok:
        print("OK: recovery stand finished.")
        sys.exit(0)

    print("FAILED: recovery stand did not finish safely.")
    sys.exit(1)


if __name__ == "__main__":
    main()
