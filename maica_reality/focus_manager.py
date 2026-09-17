"""
勿扰模式管理器
==============
玩家告知 Monika 一段时间不要打扰。
"""

from datetime import datetime, timedelta


def set_focus(duration_minutes, reason=""):
    import shared_state
    shared_state.focus_until = (datetime.now() + timedelta(minutes=duration_minutes)).isoformat()
    from config import logger
    logger.info(f"[FOCUS] Do not disturb until {shared_state.focus_until} ({reason})")


def is_in_focus():
    import shared_state
    fu = shared_state.focus_until
    if not fu:
        return False
    return datetime.now() < datetime.fromisoformat(fu)


def cancel_focus():
    import shared_state
    shared_state.focus_until = None
    from config import logger
    logger.info("[FOCUS] Focus mode cancelled")
