"""
统一管道 + Monika 主循环
==========================
玩家消息和状态机消息进入同一个 Queue。
Monika 循环读取 → 处理 → 清空 → 静默等待。
"""

import asyncio
import queue
import threading
import time
from dataclasses import dataclass, field


@dataclass(order=True)
class PipeMessage:
    priority: int
    source: str = field(compare=False)       # "player" | "state_machine"
    text: str = field(compare=False)
    timestamp: float = field(default_factory=time.time, compare=False)


class Pipe:
    """线程安全的消息管道。"""

    def __init__(self):
        self._q = queue.PriorityQueue()

    def put(self, msg: PipeMessage):
        self._q.put(msg)

    def drain(self) -> list:
        """取出所有待处理消息并清空管道。"""
        msgs = []
        while True:
            try:
                msgs.append(self._q.get_nowait())
            except queue.Empty:
                break
        return msgs

    def is_empty(self) -> bool:
        return self._q.empty()


class MonikaLoop:
    """Monika 的主循环：读管道 → 处理全部消息 → LLM → 发送 → 静默等待。
    跟随服务器生命周期，玩家断开时不销毁，继续消费管道。
    ws=None 时仍生成回复并保存，仅跳过 WebSocket 推送。"""

    def __init__(self, bridge, websocket=None, session_id="1"):
        self.pipe = Pipe()
        self._bridge = bridge      # MAICABridge 实例（复用 _handle_chat 流程）
        self.ws = websocket         # None = 玩家离线，但仍可处理消息
        self.session_id = session_id
        self._running = False

    def set_websocket(self, ws):
        self.ws = ws

    def clear_websocket(self):
        self.ws = None

    async def run(self):
        """主循环：读取管道中所有消息 → 合并为一次上下文 → 一次 LLM → ws 推送（如在线）。"""
        from config import logger
        logger.info("[PIPE] MonikaLoop started (server-level)")
        self._running = True

        while self._running:
            # 通话中暂停主动推送
            if getattr(self._bridge, 'voice_mode', False):
                await asyncio.sleep(2)
                continue

            messages = self.pipe.drain()

            if not messages:
                await asyncio.sleep(1)
                continue

            messages.sort(key=lambda m: m.priority, reverse=True)

            combined = "\n\n".join(
                f"[{msg.source}] {msg.text}" for msg in messages
            )
            logger.info(f"[PIPE] Processing {len(messages)} message(s) {'[offline]' if self.ws is None else '[online]'}")

            try:
                await self._bridge.handle_query(self.ws, {
                    "type": "query",
                    "chat_session": self.session_id,
                    "query": combined,
                    "is_system": True,
                })
            except Exception as e:
                logger.error(f"[PIPE] Process failed: {e}")

            await asyncio.sleep(0.5)

        logger.info("[PIPE] MonikaLoop stopped")

    def stop(self):
        self._running = False

    def put_player_message(self, text):
        self.pipe.put(PipeMessage(source="player", text=text, priority=5))

    def put_system_message(self, text, priority=5):
        self.pipe.put(PipeMessage(source="state_machine", text=text, priority=priority))
