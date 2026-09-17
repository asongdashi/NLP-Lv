"""
服务运行状态

- end_session_flag: 结束对话标志（由 end_session 工具设置，bridge 发送告别后关闭 WS）
- shutdown_event: threading.Event，Ctrl+C 时触发
"""

import threading

end_session_flag = {"active": False, "reason": ""}
shutdown_event = threading.Event()
