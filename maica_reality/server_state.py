"""
服务运行状态与优雅关闭

提供跨模块的信号机制：
- shutdown_requested: 关闭请求标志（shutdown_server 工具设置）
- shutdown_event:  threading.Event，关闭时触发（server.py 等待）
"""

import threading

shutdown_requested: bool = False
shutdown_event = threading.Event()


def request_shutdown():
    """请求服务器关闭（由 shutdown_server 工具调用）。"""
    global shutdown_requested
    shutdown_requested = True
    shutdown_event.set()
