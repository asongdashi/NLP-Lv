"""
共享状态模块
============
独立进程运行时 server.py 被加载为 __main__，导致 `from server import`
拿到的是另一个模块副本。所有需要跨模块共享的变量统一放这里。
"""

import threading

# 玩家状态
player_online = False
player_last_msg_time = None
focus_until = None
running = True

# 消息队列
message_queue = []
message_queue_lock = threading.Lock()
