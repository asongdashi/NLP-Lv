"""
通知渠道抽象基类
"""


class NotifyChannel:
    """通知渠道抽象基类"""

    def send(self, title, message, priority):
        raise NotImplementedError

    def is_available(self):
        raise NotImplementedError

    def channel_name(self):
        raise NotImplementedError
