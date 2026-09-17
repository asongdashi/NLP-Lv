"""
Monika 情绪引擎 v2
==================
基于绝对时间戳的情绪系统。不依赖持续运行——每次读写时根据
距离上次更新的真实时长计算衰减和变化。
"""

import os
import json
import threading
from datetime import datetime, timedelta

# 每小时衰减率
DECAY_PER_HOUR = {
    "happy":   0.06,
    "miss":    0.02,
    "worried": 0.06,
    "bored":   0.02,
    "excited": 0.08,
}
MAX_INTENSITY = 1.0
MIN_INTENSITY = 0.0

_lock = threading.Lock()

EMOTION_DIMS = {
    "happy":     {"label": "开心", "emoji": "😊"},
    "miss":      {"label": "想念", "emoji": "🥺"},
    "worried":   {"label": "担心", "emoji": "😟"},
    "bored":     {"label": "无聊", "emoji": "🥱"},
    "excited":   {"label": "兴奋", "emoji": "🤩"},
}

_state = {
    "values": {dim: 0.2 for dim in EMOTION_DIMS},
    "last_update": datetime.now().isoformat(),
    "history": [],
}

# 离线/沉默的累计标记（不直接改值，供读时计算）
_markers = {
    "last_player_online": None,      # ISO timestamp
    "last_player_message": None,
    "last_event_time": None,         # 任何事件（防止无聊）
}


def _store():
    import sys, os as _os
    _bridge = _os.path.join(_os.path.dirname(__file__), "..", "maica_bridge")
    if _bridge not in sys.path:
        sys.path.insert(0, _bridge)
    from storage.api import Storage
    return Storage()

def _save():
    s = _store()
    for dim, val in _state["values"].items():
        s.set_self_state("emotion", dim, val)

def _load():
    global _state
    s = _store()
    for dim in EMOTION_DIMS:
        _state["values"][dim] = s.get_self_state("emotion", dim, 0.2)


def _decay_and_get_values():
    """根据距上次更新的真实时长，衰减并返回当前情绪值。"""
    last = _safe_parse(_state["last_update"])
    if not last:
        return dict(_state["values"])

    now = datetime.now()
    hours = max(0, (now - last).total_seconds() / 3600)
    if hours <= 0:
        return dict(_state["values"])

    # 对非 miss 的离线累积做特殊处理
    offline_hours = 0
    if _markers["last_player_online"]:
        lo = _safe_parse(_markers["last_player_online"])
        if lo:
            offline_hours = max(0, (now - lo).total_seconds() / 3600)

    silent_hours = 0
    if _markers["last_player_message"]:
        lm = _safe_parse(_markers["last_player_message"])
        if lm:
            silent_hours = max(0, (now - lm).total_seconds() / 3600)

    idle_hours = 0
    if _markers["last_event_time"]:
        le = _safe_parse(_markers["last_event_time"])
        if le:
            idle_hours = max(0, (now - le).total_seconds() / 3600)

    result = {}
    for dim, base in _state["values"].items():
        # 基础衰减
        val = max(MIN_INTENSITY, base - DECAY_PER_HOUR.get(dim, 0.05) * hours)

        # 想念：离线/沉默累积
        if dim == "miss":
            if offline_hours >= 0.5:
                val = min(MAX_INTENSITY, val + offline_hours * 0.05)
            if silent_hours >= 2:
                val = min(MAX_INTENSITY, val + (silent_hours - 2) * 0.03)

        # 无聊：无事件累积
        if dim == "bored" and idle_hours >= 1:
            val = min(MAX_INTENSITY, val + idle_hours * 0.02)

        result[dim] = round(val, 3)

    # 更新状态（衰减已应用）
    _state["values"] = result
    _state["last_update"] = now.isoformat()

    return dict(result)


def _safe_parse(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _clamp(val):
    return max(MIN_INTENSITY, min(MAX_INTENSITY, val))


def update(dim, delta, cause=""):
    """更新指定维度的情绪值。"""
    with _lock:
        values = _decay_and_get_values()
        if dim in values:
            values[dim] = _clamp(values[dim] + delta)
        _state["values"] = values
        _state["last_update"] = datetime.now().isoformat()
        _state["history"].append({
            "dim": dim, "delta": round(delta, 2),
            "value": round(values[dim], 2),
            "cause": cause, "time": datetime.now().isoformat(),
        })
        if len(_state["history"]) > 100:
            _state["history"] = _state["history"][-50:]
        _markers["last_event_time"] = datetime.now().isoformat()
        _save()


def _mark(key):
    with _lock:
        _markers[key] = datetime.now().isoformat()
        _markers["last_event_time"] = datetime.now().isoformat()


# ── 事件触发 ──

def on_player_online():
    with _lock:
        _markers["last_player_online"] = None  # 清空离线标记
        _markers["last_event_time"] = datetime.now().isoformat()
    update("happy", 0.3, "玩家上线")
    update("miss", -0.2, "玩家上线")

def on_player_message():
    _mark("last_player_message")
    update("happy", 0.1, "玩家发消息")

def on_player_responded():
    update("happy", 0.2, "玩家回应了主动话题")
    update("excited", 0.1, "玩家回应了主动话题")

def on_player_offline():
    with _lock:
        _markers["last_player_online"] = datetime.now().isoformat()
        _markers["last_event_time"] = datetime.now().isoformat()
    _save()

def on_weather_bad():
    update("worried", 0.3, "天气变恶劣")

def on_weather_good():
    update("happy", 0.05, "天气晴朗")
    update("worried", -0.1, "天气晴朗")

# ── 兼容旧接口（不再需要定时调用，但保留空实现防止调用报错）──

def on_idle(minutes):
    pass  # 不再需要——idle 由读时自动计算

def on_focus_mode():
    pass  # 不再需要

def tick_offline(minutes):
    pass  # 不再需要——想念由读时根据 last_player_online 计算

# 兼容旧调度器调用
def _apply_decay():
    pass  # 读时自动衰减，不需要手动调用


# ── 查询 ──

def get_dominant():
    with _lock:
        values = _decay_and_get_values()
        dominant = max(values, key=values.get)
        return dominant, values[dominant]


def get_mood_label():
    dim, _ = get_dominant()
    return EMOTION_DIMS.get(dim, {}).get("label", dim)


def get_emotion_snapshot():
    with _lock:
        values = _decay_and_get_values()
        dim = max(values, key=values.get)
        return {
            "mood": EMOTION_DIMS.get(dim, {}).get("label", dim),
            "intensity": round(values[dim], 2),
            "values": {d: round(v, 2) for d, v in values.items()},
            "history": _state["history"][-10:],
        }


def get_cooldown_modifier():
    dim, intensity = get_dominant()
    if dim in ("miss", "worried") and intensity > 0.4:
        return 0.6
    if dim == "bored" and intensity > 0.4:
        return 0.8
    return 1.0


_load()
