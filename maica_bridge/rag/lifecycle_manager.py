"""
服务器生命周期日志管理

记录 Monika 的"存在状态"：
- 启动时间 / 运行时长
- 对话次数 / 消息总数
- 最后活跃时间

通过 get_my_status 工具让 Monika 感知自己的运行状态。
"""

import os
import json
import time
import logging

logger = logging.getLogger("maica_bridge.rag")

LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
LIFECYCLE_PATH = os.path.join(LOGS_DIR, "lifecycle.json")


_default_lifecycle = {
    "started_at": "",
    "total_sessions": 0,
    "total_messages": 0,
    "uptime": "",
    "last_active": "",
}


def _load():
    os.makedirs(LOGS_DIR, exist_ok=True)
    if not os.path.exists(LIFECYCLE_PATH):
        _save(_default_lifecycle)
        return dict(_default_lifecycle)
    try:
        with open(LIFECYCLE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return dict(_default_lifecycle)


def _save(data):
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(LIFECYCLE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def record_startup():
    """服务启动时调用，记录启动时间。"""
    data = _load()
    from datetime import datetime, timezone, timedelta
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    weekday_zh = ["一", "二", "三", "四", "五", "六", "日"]
    wd = weekday_zh[now.weekday()]
    data["started_at"] = f"{now.strftime('%Y-%m-%d %H:%M:%S')} 星期{wd}"
    data["last_active"] = data["started_at"]
    _save(data)
    logger.info(f"Lifecycle: startup recorded at {data['started_at']}")


def increment_message():
    """每次对话完成后调用：消息数 +1，更新最后活跃时间、运行时长。"""
    data = _load()
    data["total_messages"] = data.get("total_messages", 0) + 1

    from datetime import datetime, timezone, timedelta
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    weekday_zh = ["一", "二", "三", "四", "五", "六", "日"]
    wd = weekday_zh[now.weekday()]
    data["last_active"] = f"{now.strftime('%Y-%m-%d %H:%M:%S')} 星期{wd}"

    # 计算运行时长
    started_str = data.get("started_at", "")
    if started_str:
        try:
            started_dt = datetime.strptime(started_str[:19], "%Y-%m-%d %H:%M:%S")
            started_dt = started_dt.replace(tzinfo=tz)
            delta = now - started_dt
            hours = int(delta.total_seconds()) // 3600
            mins = (int(delta.total_seconds()) % 3600) // 60
            if hours > 0:
                data["uptime"] = f"{hours}小时{mins}分钟"
            else:
                data["uptime"] = f"{mins}分钟"
        except Exception:
            pass

    _save(data)


def increment_session():
    """新会话时调用：会话数 +1。"""
    data = _load()
    data["total_sessions"] = data.get("total_sessions", 0) + 1
    _save(data)


def get_status_text() -> str:
    """返回格式化的状态文本。"""
    data = _load()
    started = data.get("started_at", "未知")
    uptime = data.get("uptime", "未知")
    total = data.get("total_messages", 0)
    sessions = data.get("total_sessions", 0)
    return (
        f"启动时间：{started}\n"
        f"已运行：{uptime}\n"
        f"本次运行对话次数：{sessions}\n"
        f"本次运行消息数：{total}"
    )
