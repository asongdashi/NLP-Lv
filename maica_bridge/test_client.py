"""
MAICA Bridge 测试客户端
======================
模拟 MAICA 前端通过 WebSocket 连接桥接服务器，发送查询并打印回复。
交互模式: 直接运行 python test_client.py
单次模式: echo "你好" | python test_client.py --once

用法:
  python test_client.py            # 交互对话
  python test_client.py --once     # 从 stdin 读一行，打印回复后退出
  python test_client.py --raw      # 交互模式 + 打印每条原始 JSON 消息
"""

import asyncio
import json
import sys
import signal
import websockets

BRIDGE_WS = "ws://127.0.0.1:5000"


async def main():
    once = "--once" in sys.argv
    raw_mode = "--raw" in sys.argv

    print("MAICA Bridge Test Client")
    print("=" * 40)
    print(f"Connecting to {BRIDGE_WS} ...")

    async with websockets.connect(BRIDGE_WS, ping_interval=None, ping_timeout=None, close_timeout=10) as ws:
        # 等待连接握手（5100, 5102）
        handshake_done = False
        for _ in range(4):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
            except asyncio.TimeoutError:
                break
            msg = json.loads(raw)
            if raw_mode:
                print(f"[IN ] {json.dumps(msg, ensure_ascii=False)}")

            code = msg.get("code", 0)
            content = msg.get("content", "")

            if code == 5100:
                print("[OK] Connection established")
            elif code == 5102:
                info = json.loads(msg["content"]) if isinstance(msg["content"], str) else msg["content"]
                print(f"[OK] Initiated: model={info.get('model', '?')}")
                handshake_done = True
                break  # 收到 5102 后等待问候

        # 等待启动问候（可能需要 5-10 秒生成）
        if handshake_done:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=20)
            except asyncio.TimeoutError:
                pass
            else:
                msg = json.loads(raw)
                if raw_mode:
                    print(f"[IN ] {json.dumps(msg, ensure_ascii=False)}")
                code = msg.get("code", 0)
                content = msg.get("content", "")
                if code == 5200 and content:  # 启动问候
                    print(f"Monika: {content}", flush=True)
                    # 等待 5202 结束标记
                    try:
                        raw2 = await asyncio.wait_for(ws.recv(), timeout=5)
                        if raw_mode:
                            msg2 = json.loads(raw2)
                            print(f"[IN ] {json.dumps(msg2, ensure_ascii=False)}")
                    except asyncio.TimeoutError:
                        pass

        print("[OK] Ready.")
        print("-" * 40)

        session_id = 1

        def read_input():
            """跨平台读取一行，忽略键盘中断。"""
            try:
                return input("You: ")
            except (EOFError, KeyboardInterrupt):
                return None

        while True:
            user_input = read_input()
            if user_input is None:
                if once:
                    # 单次模式: 读完一行后等待回复再退出
                    pass
                else:
                    break
            elif user_input.strip() == "/quit":
                break
            elif not user_input.strip():
                continue

            # 发送查询
            query_obj = {
                "type": "query",
                "chat_session": session_id,
                "query": user_input,
            }
            query_str = json.dumps(query_obj)
            if raw_mode:
                print(f"[OUT] {query_str}")
            await ws.send(query_str)

            # 接收回复
            print("Monika: ", end="", flush=True)
            full_reply = ""

            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=120)
                except asyncio.TimeoutError:
                    print("\n[WARN] Response timeout")
                    break

                msg = json.loads(raw)
                if raw_mode:
                    print(f"\n[IN ] {json.dumps(msg, ensure_ascii=False)}")

                code = msg.get("code", 0)
                content = msg.get("content", "")
                status = msg.get("status", "")

                if code == 5200:  # streaming_continue
                    if content:
                        print(content, flush=True)
                        full_reply += content
                elif code == 5202:  # loop_finished
                    break
                elif code >= 5300:  # warning/error
                    print(f"\n[WARN] code={code} status={status}")
                    break

            if not full_reply:
                print("[NO RESPONSE]")
            print()

            if once:
                break

        print("[OK] Disconnected.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except websockets.exceptions.ConnectionClosed as e:
        print(f"\n[ERR] Connection closed: {e}")
    except KeyboardInterrupt:
        print("\n[OK] Interrupted.")
