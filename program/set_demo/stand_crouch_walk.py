#!/usr/bin/env python3
"""
CyberDog 站立行走 → 蹲下行走 演示脚本（真机版，LCM 直连运控板）

核心原理（来自官方文档 cyberdog_loco_cn.md）：
  - 运控板 M813 通过 LCM 接收 robot_control_cmd 指令
  - pos_des[2] 控制身体质心距地面高度（正常范围 0.1~0.32m）
  - mode=11 为行走模式，gait_id=3 为 TROT_MEDIUM 中速步态
  - gait_id=26 为自变频步态

流程:
  1. STAND_UP    — 恢复站立 (mode=12)
  2. NORMAL_WALK — 正常行走 (mode=11, gait_id=3, pos_des[2]=0.22)
  3. CROUCH_WALK — 蹲下行走 (mode=11, gait_id=3, pos_des[2]=0.15, vx=0.06)
  4. FINAL_STOP  — 停止 (mode=12)

不需要 cyberdog_msg、ROS2 yaml_parameter 等仿真专用接口。
"""
import math
import os
import sys
import time

# ── LCM 路径设置 ──────────────────────────────────────────────────
LCM_SEARCH_PATHS = [
    "/home/lcm/build/python",
    "/opt/ros2/galactic/lib/python3/dist-packages",
]
CONTROL_SEARCH_PATHS = [
    "/home/loco_hl_example/sequential_motion",
    os.path.dirname(os.path.abspath(__file__)),
]

for p in LCM_SEARCH_PATHS + CONTROL_SEARCH_PATHS:
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

import lcm
from robot_control_cmd_lcmt import robot_control_cmd_lcmt


# ── 身体高度参数（官方文档: pos_des[2] 范围 0.1~0.32m）──────────
NORMAL_HEIGHT = 0.22    # 正常站立高度
CROUCH_HEIGHT = 0.15    # 蹲下高度


# ── 步态参数 ─────────────────────────────────────────────────────
class GaitConfig:
    """步态配置"""
    # 正常行走
    NORMAL_VX = 0.10            # 前进速度 m/s
    NORMAL_STEP_HEIGHT = [0.06, 0.06]  # 步高 m

    # 蹲下行走
    CROUCH_VX = 0.06            # 前进速度 m/s（更慢）
    CROUCH_STEP_HEIGHT = [0.03, 0.03]  # 步高 m（更小）


# ── 时间参数（控制周期 50Hz，即每帧 0.02s）─────────────────────
# 但实际官方例程使用 10Hz 级别的心跳，这里保持 50Hz 以确保稳定
HEARTBEAT_HZ = 50
HEARTBEAT_DT = 1.0 / HEARTBEAT_HZ

STAND_DURATION = 2.0       # 站立恢复时间（秒）
NORMAL_WALK_DURATION = 3.0  # 正常行走时间（秒）
CROUCH_SETTLE_DURATION = 2.0  # 蹲下稳定时间（秒）
CROUCH_WALK_DURATION = 3.0  # 蹲下行走时间（秒）
STOP_DURATION = 1.5         # 停止时间（秒）

# yaw 对齐参数
YAW_ALIGN_KP = 0.8
YAW_ALIGN_MAX_VYAW = 0.3
YAW_ALIGN_TOLERANCE = 0.02


def normalize_angle(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


class StandCrouchWalkController:
    def __init__(self):
        self.state = "STAND_UP"
        self.state_start_time = time.monotonic()
        self.task_finished = False

        # LCM 通道
        self.lc = lcm.LCM("udpm://239.255.76.67:7671?ttl=255")
        self.cmd = robot_control_cmd_lcmt()

        print("[INIT] 控制器初始化完成")
        print(f"[INIT] 正常高度={NORMAL_HEIGHT}m, 蹲下高度={CROUCH_HEIGHT}m")
        print(f"[INIT] 正常行走: vx={GaitConfig.NORMAL_VX}, "
              f"蹲下行走: vx={GaitConfig.CROUCH_VX}")

    def publish(self, vx, vy=0.0, vyaw=0.0, mode=11, gait_id=3,
                body_height=None, step_height=None, duration=0):
        """发送一条 robot_control_cmd 控制指令"""
        self.cmd.mode = mode
        self.cmd.gait_id = gait_id
        self.cmd.contact = 15 if mode == 11 else 0
        self.cmd.vel_des = [float(vx), float(vy), float(vyaw)]
        self.cmd.rpy_des = [0.0, 0.0, 0.0]

        if body_height is not None:
            self.cmd.pos_des = [0.0, 0.0, float(body_height)]
        self.cmd.duration = int(duration)

        if step_height is not None:
            self.cmd.step_height = [float(step_height[0]), float(step_height[1])]

        self.cmd.life_count = (self.cmd.life_count + 1) % 128
        self.lc.publish("robot_control_cmd", self.cmd.encode())

    def recovery_stand(self):
        """恢复站立: mode=12"""
        self.publish(0, 0, 0, mode=12, gait_id=0)

    def damper_stop(self):
        """阻尼停止: mode=7"""
        self.publish(0, 0, 0, mode=7, gait_id=0)

    def elapsed(self):
        return time.monotonic() - self.state_start_time

    def transition(self, new_state):
        self.state = new_state
        self.state_start_time = time.monotonic()
        print(f"\n{'='*50}")
        print(f"  → 切换到: {new_state}")
        print(f"{'='*50}")

    def step(self):
        """主控制步进，每个调用周期执行一次"""

        if self.state == "STAND_UP":
            # 前半段恢复站立，后半段设置正常高度
            if self.elapsed() < STAND_DURATION * 0.6:
                self.recovery_stand()
            else:
                # 用 mode=21 设置正常身体高度
                self.cmd.mode = 21
                self.cmd.gait_id = 5
                self.cmd.pos_des = [0.0, 0.0, NORMAL_HEIGHT]
                self.cmd.duration = 0
                self.cmd.life_count = (self.cmd.life_count + 1) % 128
                self.lc.publish("robot_control_cmd", self.cmd.encode())

            if self.elapsed() >= STAND_DURATION:
                print("[STAND_UP] 站立完成")
                self.transition("NORMAL_WALK")

        elif self.state == "NORMAL_WALK":
            self.publish(
                vx=GaitConfig.NORMAL_VX,
                body_height=NORMAL_HEIGHT,
                step_height=GaitConfig.NORMAL_STEP_HEIGHT,
            )

            elapsed = self.elapsed()
            if elapsed % 1.0 < HEARTBEAT_DT:
                print(f"  正常行走中... {elapsed:.1f}/{NORMAL_WALK_DURATION}s")

            if self.elapsed() >= NORMAL_WALK_DURATION:
                print("[NORMAL_WALK] 正常行走完成")
                self.transition("CROUCH_SETTLE")

        elif self.state == "CROUCH_SETTLE":
            # 先零速行走让身体高度过渡到蹲下
            if self.elapsed() < CROUCH_SETTLE_DURATION:
                self.publish(
                    vx=0.0,
                    body_height=CROUCH_HEIGHT,
                    step_height=GaitConfig.CROUCH_STEP_HEIGHT,
                )
                if self.elapsed() < 0.5:
                    print("[CROUCH_SETTLE] 正在降低身体高度...")
            else:
                print("[CROUCH_SETTLE] 身体已降低")
                self.transition("CROUCH_WALK")

        elif self.state == "CROUCH_WALK":
            self.publish(
                vx=GaitConfig.CROUCH_VX,
                body_height=CROUCH_HEIGHT,
                step_height=GaitConfig.CROUCH_STEP_HEIGHT,
            )

            elapsed = self.elapsed()
            if elapsed % 1.0 < HEARTBEAT_DT:
                print(f"  蹲下行走中... {elapsed:.1f}/{CROUCH_WALK_DURATION}s")

            if self.elapsed() >= CROUCH_WALK_DURATION:
                print("[CROUCH_WALK] 蹲下行走完成")
                self.transition("FINAL_STOP")

        elif self.state == "FINAL_STOP":
            # 先恢复高度再停止
            if self.elapsed() < STOP_DURATION * 0.4:
                self.publish(
                    vx=0.0,
                    body_height=NORMAL_HEIGHT,
                    step_height=GaitConfig.NORMAL_STEP_HEIGHT,
                )
            elif self.elapsed() < STOP_DURATION * 0.6:
                self.recovery_stand()
            else:
                self.damper_stop()

            if self.elapsed() >= STOP_DURATION:
                print("[FINAL_STOP] 已停止")
                self.task_finished = True


def main():
    print("=" * 50)
    print("  CyberDog 站立 → 行走 → 蹲走 → 停止")
    print("  (LCM 直连运控板，pos_des[2] 控制身体高度)")
    print("=" * 50)

    ctrl = StandCrouchWalkController()

    try:
        while not ctrl.task_finished:
            ctrl.step()
            time.sleep(HEARTBEAT_DT)

        print("\n[DONE] 任务完成!")

    except KeyboardInterrupt:
        print("\n[STOP] Ctrl+C 中断，阻尼停止...")
        ctrl.damper_stop()


if __name__ == "__main__":
    main()
