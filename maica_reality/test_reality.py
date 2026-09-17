"""
外系统调试客户端
================
测试 reality 系统各模块是否正常工作。
用法: python test_reality.py
"""

import requests
import json
import time
import sys

REALITY = "http://127.0.0.1:6101"

def check(path, label):
    try:
        r = requests.get(f"{REALITY}{path}", timeout=5)
        data = r.json()
        print(f"  [{label}] HTTP {r.status_code}")
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, list):
                    print(f"    {k}: {len(v)} 条")
                elif isinstance(v, dict):
                    print(f"    {k}: {json.dumps(v, ensure_ascii=False)[:100]}")
                else:
                    print(f"    {k}: {v}")
        return data
    except Exception as e:
        print(f"  [{label}] 不可达: {e}")
        return None

def notify(event, msg=None):
    body = {"event": event, "timestamp": "now"}
    if msg:
        body["player_message"] = msg
    try:
        r = requests.post(f"{REALITY}/api/notify", json=body, timeout=3)
        print(f"  [{event}] HTTP {r.status_code}")
    except Exception as e:
        print(f"  [{event}] 失败: {e}")

def main():
    print("=" * 50)
    print("  MAICA Reality 外系统调试")
    print("=" * 50)

    # 1. 检查服务器是否在线
    print("\n[1] 外系统连接检查")
    if not check("/api/emotion", "情绪API"):
        print("\n外系统未启动！请先运行: cd maica_reality && python server.py")
        sys.exit(1)

    # 2. 查看当前情绪
    print("\n[2] Monika 当前情绪")
    check("/api/emotion", "情绪快照")

    # 3. 模拟玩家上线
    print("\n[3] 模拟玩家上线")
    notify("player_online")

    # 4. 检查待投递消息队列（初始应为空）
    print("\n[4] 当前待投递消息")
    pending = check("/api/pending", "消息队列")

    # 5. 再次检查待投递消息（应有刚才那条）
    print("\n[6] 再次检查消息队列（应有1条）")
    pending2 = check("/api/pending", "消息队列(第2次)")

    # 7. 模拟玩家发消息（触发勿扰检测）
    print("\n[7] 模拟玩家消息（正常聊天）")
    notify("player_message", "Monika 你好呀")

    time.sleep(0.5)

    # 8. 模拟勿扰指令
    print("\n[8] 模拟勿扰指令")
    focus_body = {
        "event": "player_message",
        "player_message": "接下来 1 小时我在上课",
        "focus_request": {"duration_minutes": 60, "reason": "上课"},
        "timestamp": "now",
    }
    try:
        r = requests.post(f"{REALITY}/api/notify", json=focus_body, timeout=3)
        print(f"  [focus] HTTP {r.status_code}")
    except Exception as e:
        print(f"  [focus] 失败: {e}")

    # 9. 确认勿扰状态
    try:
        from focus_manager import is_in_focus
        print(f"  勿扰模式: {'开启' if is_in_focus() else '关闭'}")
    except Exception:
        pass

    # 10. 模拟玩家离线
    print("\n[9] 模拟玩家离线")
    notify("player_offline")

    print("\n" + "=" * 50)
    print("  测试完成！")
    print("  如果上面各项都正常，外系统已就绪。")
    print()
    print("  联调方式:")
    print("    1. 确保 bridge 也在运行")
    print("    2. bridge 会自动通知外系统玩家上线/下线")
    print("    3. 调度器会自动生成主动话题推入队列")
    print("    4. bridge 每个 chat turn 拉取并投递")
    print("=" * 50)


if __name__ == "__main__":
    main()
