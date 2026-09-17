"""
PWA WebSocket 推送
==================
当手机端 PWA 在线时，通过 WebSocket 直接推送消息。
"""

from .base import NotifyChannel


class PWAChannel(NotifyChannel):
    def channel_name(self):
        return "pwa"

    def is_available(self):
        # 简化版：检查是否有活跃的 mobile WS 连接
        return False  # 由 server.py 的连接管理动态更新

    def send(self, title, message, priority):
        # PWA 通过 WebSocket 实时推送，在 server.py 的 WS handler 中处理
        return True
