"""
MAICA 统一启动器
================
一键启动内系统 (bridge) + 外系统 (reality)，两个独立进程。

用法: python start.py
"""

import subprocess
import sys
import os
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
BRIDGE_DIR = os.path.join(ROOT, "maica_bridge")
REALITY_DIR = os.path.join(ROOT, "maica_reality")


def main():
    print("=" * 50)
    print("  MAICA 双系统启动器")
    print("  内系统: maica_bridge  (对话 + 记忆 + 人格)")
    print("  外系统: maica_reality (感官 + 情绪 + 主动推送)")
    print("=" * 50)

    # 启动外系统
    print("\n[1/2] 启动外系统 (reality)...")
    reality_proc = subprocess.Popen(
        [sys.executable, "server.py"],
        cwd=REALITY_DIR,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

    time.sleep(2)

    # 启动内系统
    print("\n[2/2] 启动内系统 (bridge)...")
    bridge_proc = subprocess.Popen(
        [sys.executable, "server.py"],
        cwd=BRIDGE_DIR,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

    print("\n" + "=" * 50)
    print("  双系统已启动！")
    print("  聊天界面: http://127.0.0.1:8080/chat")
    print("  外系统 API: http://127.0.0.1:6101")
    print("  按 Ctrl+C 停止")
    print("=" * 50 + "\n")

    try:
        bridge_proc.wait()
        reality_proc.wait()
    except KeyboardInterrupt:
        print("\n[关闭] 正在停止...")
        bridge_proc.terminate()
        reality_proc.terminate()
        bridge_proc.wait()
        reality_proc.wait()
        print("[关闭] 双系统已停止")


if __name__ == "__main__":
    main()
