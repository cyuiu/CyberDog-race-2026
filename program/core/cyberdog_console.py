#!/usr/bin/env python3

import sys

import rclpy

from cyberdog_actions import ACTIONS
from cyberdog_base import CyberDogBaseNode
from cyberdog_gaits import GAITS


def risk_label(risk):
    labels = {
        "low": "低",
        "medium": "中",
        "high": "高",
        "very_high": "很高",
    }
    return labels.get(risk, risk)


def confirm_risk(item):
    risk = item.get("risk", "medium")
    name = item["name"]

    if risk == "low":
        return True

    print()
    print(f"[SAFETY] 即将执行：{name}")
    print(f"[SAFETY] 风险等级：{risk_label(risk)}")
    print("[SAFETY] 请确认机器狗在空旷地面，旁边有人，APP 急停可用。")

    if risk == "medium":
        answer = input("继续执行？[y/N] ").strip()
        return answer in ("y", "Y")

    if risk == "high":
        answer = input("高风险动作，输入 YES 继续：").strip()
        return answer == "YES"

    if risk == "very_high":
        answer = input("很高风险动作，输入 UNLOCK_HIGH_RISK 继续：").strip()
        return answer == "UNLOCK_HIGH_RISK"

    return False


def build_menu():
    entries = []

    entries.append(("status", {"name": "检查状态", "risk": "low"}))

    for action in ACTIONS:
        entries.append(("action", action))

    for gait in GAITS:
        entries.append(("gait", gait))

    return entries


def print_menu(entries):
    print()
    print("========== CyberDog Console ==========")
    print("q) 退出")
    print()

    for index, (kind, item) in enumerate(entries, start=1):
        if kind == "status":
            group = "状态"
        elif kind == "action":
            group = "动作"
        else:
            group = "步态"

        motion_id = item.get("motion_id", "-")
        print(
            f"{index:02d}) [{group}] {item['name']} "
            f"(motion_id={motion_id}, risk={risk_label(item.get('risk', 'medium'))})"
        )

    print("======================================")


def run_choice(node, kind, item):
    if kind == "status":
        return node.ensure_safe_status()

    if not confirm_risk(item):
        print("[INFO] 已取消。")
        return False

    if kind == "action":
        return node.run_motion_action(item)

    if kind == "gait":
        return node.run_servo_gait(item)

    print(f"[错误] 未知项目类型: {kind}")
    return False


def console_loop(node):
    while rclpy.ok():
        entries = build_menu()
        print_menu(entries)

        choice = input("请选择编号：").strip()

        if choice in ("q", "Q"):
            print("[信息] 再见。")
            return 0

        if not choice.isdigit():
            print("[ERROR] 请输入编号或 q。")
            continue

        index = int(choice)
        if index < 1 or index > len(entries):
            print("[ERROR] 编号超出范围。")
            continue

        kind, item = entries[index - 1]
        ok = run_choice(node, kind, item)

        if ok:
            print("[OK] 执行完成。")
        else:
            print("[FAILED] 执行失败或已取消。")


def main():
    rclpy.init()
    node = CyberDogBaseNode("cyberdog_console")

    try:
        return_code = console_loop(node)
    finally:
        node.stop_servo()
        node.destroy_node()
        rclpy.shutdown()

    sys.exit(return_code)


if __name__ == "__main__":
    main()
