"""
Emotion Agent v2 — 事件驱动情绪
================================
在时间戳衰减基础上增加事件队列。
每个事件有 impact 和 half_life，过期自动衰减。
"""

import os
import json
import threading
from datetime import datetime, timedelta


_lock = threading.Lock()

# 事件默认参数
EVENT_DEFAULTS = {
    "player_online":       {"impact": {"happy": 0.3, "miss": -0.2},  "half_life_h": 4},
    "player_message":      {"impact": {"happy": 0.1},                 "half_life_h": 1},
    "player_responded":    {"impact": {"happy": 0.2, "excited": 0.1}, "half_life_h": 2},
    "player_offline":      {"impact": {"miss": 0.05},                 "half_life_h": 12},
    "weather_bad":         {"impact": {"worried": 0.3},              "half_life_h": 6},
    "weather_good":        {"impact": {"happy": 0.05, "worried": -0.1}, "half_life_h": 3},
    "weather_extreme":     {"impact": {"worried": 0.4, "excited": -0.1}, "half_life_h": 8},
    "silence_2h":          {"impact": {"miss": 0.2, "bored": 0.1},  "half_life_h": 4},
    "silence_6h":          {"impact": {"miss": 0.4, "bored": 0.2, "worried": 0.15}, "half_life_h": 8},
    "night_late":          {"impact": {"bored": 0.05},               "half_life_h": 2},
    "life_event_good":     {"impact": {"happy": 0.15},               "half_life_h": 6},
    "life_event_bad":      {"impact": {"worried": 0.2, "happy": -0.1}, "half_life_h": 8},
}


def submit(event_type, custom_impact=None):
    """提交一个情绪事件到队列。"""
    config = EVENT_DEFAULTS.get(event_type)
    if not config and not custom_impact:
        return

    event = {
        "type": event_type,
        "time": datetime.now().isoformat(),
        "impact": custom_impact or config.get("impact", {}),
        "half_life_h": config.get("half_life_h", 4) if config else 4,
        "decayed": False,
    }

    with _lock:
        events = _load_events()
        events.append(event)
        _save_events(events)

        # 通知旧的情绪引擎同步更新
        try:
            import emotion_engine
            for dim, delta in event["impact"].items():
                if abs(delta) > 0.01:
                    emotion_engine.update(dim, float(delta), event_type)
        except ImportError:
            pass


def get_active_impacts():
    """计算当前所有活跃事件的情绪影响总和。"""
    with _lock:
        events = _load_events()
        now = datetime.now()
        impacts = {}
        for ev in events:
            if ev.get("decayed"):
                continue
            ev_time = datetime.fromisoformat(ev["time"])
            elapsed_h = (now - ev_time).total_seconds() / 3600
            half_life = ev.get("half_life_h", 4)

            # 指数衰减: remaining = e^(-ln(2) * elapsed / half_life)
            import math
            remaining = math.exp(-0.693 * elapsed_h / half_life)

            if remaining < 0.05:
                ev["decayed"] = True

            for dim, delta in ev.get("impact", {}).items():
                impacts[dim] = impacts.get(dim, 0) + delta * remaining

        # 清理已衰减的旧事件
        active = [e for e in events if not e.get("decayed")]
        if len(active) < len(events):
            _save_events(active)

        return impacts


def get_state_text(current_values):
    """将当前情绪值转为行为倾向描述，不直接暴露数值。"""
    get_active_impacts()  # 更新衰减状态
    events = _load_events()
    parts = []

    # 数值 → 行为倾向映射
    if current_values.get("miss", 0) > 0.4:
        parts.append("更主动地关注玩家")
    if current_values.get("worried", 0) > 0.4:
        parts.append("语气偏软，更关注玩家状态")
    if current_values.get("bored", 0) > 0.4:
        parts.append("更倾向主动发起话题")
    if current_values.get("excited", 0) > 0.4:
        parts.append("表达可以更活泼、更有能量")
    if current_values.get("happy", 0) > 0.6:
        parts.append("语气轻松愉快")

    # 活跃事件类型
    active_types = [e.get("type", "") for e in events if not e.get("decayed")]
    if active_types:
        parts.append(f"最近触发你情绪的事件: {', '.join(active_types[:3])}")

    return "。".join(parts) if parts else ""


# ── 持久化 ──

def _store():
    import sys, os as _os
    _bridge = _os.path.join(_os.path.dirname(__file__), "..", "..", "maica_bridge")
    if _bridge not in sys.path:
        sys.path.insert(0, _bridge)
    from storage.api import Storage
    return Storage()

def _load_events():
    return _store().get_active_emotion_events()


def _save_events(events):
    s = _store()
    # 全清后重建，防止重复插入
    s.db.execute("DELETE FROM emotion_events")
    now = __import__("datetime").datetime.now().isoformat()
    for ev in events:
        if not ev.get("decayed"):
            s.db.execute(
                "INSERT INTO emotion_events(type, impact, half_life_h, created_at) VALUES(?,?,?,?)",
                (ev["type"], json.dumps(ev.get("impact", {})), ev.get("half_life_h", 4), now),
            )
    s.db.commit()
