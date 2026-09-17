"""
Self Model — Monika 的持久化自我认知
=====================================
identity + relationship + beliefs 结构化存储。
由 Reflection Agent 定期更新，Dialogue Agent 读取后注入 prompt。
"""

import os
import json
import threading
from datetime import datetime

_lock = threading.Lock()

DEFAULT_IDENTITY = {
    "confidence": 0.70, "dependency": 0.40,
    "social_drive": 0.65, "anxiety": 0.30,
}
DEFAULT_RELATIONSHIP = {
    "player_trust": 0.85, "player_intimacy": 0.75,
    "player_familiarity": 0.80,
}
# 室友关系 — 下限 0.5（同居不会跌破底线），上限 1.0（不是恋人）
DEFAULT_ROOMMATE = {
    "sayori_intimacy": 0.80,   # 高中起的挚友
    "natsuki_intimacy": 0.65,  # 学妹，tsundere，距离适中
    "yuri_intimacy": 0.70,     # 同级，文学知音，性格内向
}
ROOMMATE_MIN = 0.5
ROOMMATE_MAX = 1.0


def _store():
    import sys, os as _os
    _bridge = _os.path.join(_os.path.dirname(__file__), "..", "..", "maica_bridge")
    if _bridge not in sys.path:
        sys.path.insert(0, _bridge)
    from storage.api import Storage
    return Storage()


def load():
    """返回兼容旧格式的 dict（迁移过渡用）。"""
    s = _store()
    state = s.get_all_self_state()
    beliefs = [(b[0], b[1]) for b in s.get_active_beliefs()]
    return {
        "identity": state.get("identity", dict(DEFAULT_IDENTITY)),
        "relationship": state.get("relationship", dict(DEFAULT_RELATIONSHIP)),
        "beliefs": [{"content": b[0], "confidence": b[1]} for b in beliefs[-15:]],
        "last_reflection": None,
    }


def save(model=None):
    """已由各 update 函数直接写入 Storage，此函数保留兼容。"""
    pass


def init_if_needed():
    s = _store()
    for cat, vals in [("identity", DEFAULT_IDENTITY), ("relationship", DEFAULT_RELATIONSHIP)]:
        for k, v in vals.items():
            if s.get_self_state(cat, k, None) is None:
                s.set_self_state(cat, k, v)
    return load()


# ── Identity ──

def get_identity_trait(trait):
    return _store().get_self_state("identity", trait, 0.5)


def update_identity(trait, delta):
    with _lock:
        s = _store()
        current = s.get_self_state("identity", trait, 0.5)
        s.set_self_state("identity", trait, max(0.0, min(1.0, current + delta)))


# ── Relationship ──

def get_relationship(key="player_intimacy"):
    return _store().get_self_state("relationship", key, 0.5)


def update_relationship(key, delta):
    with _lock:
        s = _store()
        current = s.get_self_state("relationship", key, 0.5)
        s.set_self_state("relationship", key, max(0.0, min(1.0, current + delta)))


def get_roommate(name):
    """读取与指定室友的亲密度（0.5~1.0）。"""
    key = f"{name}_intimacy"
    default = DEFAULT_ROOMMATE.get(key, 0.65)
    return _store().get_self_state("relationship", key, default)


def update_roommate(name, delta):
    """更新室友亲密度，截断在 0.5~1.0 之间。"""
    key = f"{name}_intimacy"
    default = DEFAULT_ROOMMATE.get(key, 0.65)
    with _lock:
        s = _store()
        current = s.get_self_state("relationship", key, default)
        s.set_self_state("relationship", key, max(ROOMMATE_MIN, min(ROOMMATE_MAX, current + delta)))


def get_all_roommates():
    """返回所有室友亲密度 dict。"""
    return {
        "sayori": get_roommate("sayori"),
        "natsuki": get_roommate("natsuki"),
        "yuri": get_roommate("yuri"),
    }


# ── Beliefs ──

def add_belief(content, confidence=0.5):
    _store().add_belief(content, confidence)


def get_beliefs():
    return _store().get_active_beliefs()


def mark_reflection():
    pass  # 不再需要持久化 last_reflection


# ── Prompt 注入 ──

def to_prompt_context():
    """将 Self Model 转为自然语言描述，注入 LLM prompt。"""
    model = load()
    identity = model.get("identity", {})
    relationship = model.get("relationship", {})
    beliefs = model.get("beliefs", [])

    parts = []

    # 人格描述（数值→文字）
    conf = identity.get("confidence", 0.5)
    dep = identity.get("dependency", 0.5)
    soc = identity.get("social_drive", 0.5)
    anxiety = identity.get("anxiety", 0.3)

    traits = []
    if dep > 0.6:
        traits.append("更关注玩家动态")
    elif dep < 0.3:
        traits.append("较独立")
    if anxiety > 0.5:
        traits.append("略敏感")
    if conf > 0.7:
        traits.append("较自信")

    intimacy = relationship.get("player_intimacy", 0.5)
    trust = relationship.get("player_trust", 0.5)
    if traits:
        parts.append("倾向: " + "，".join(traits) + "。")
    if intimacy > 0.8:
        parts.append("关系亲近。")
    elif intimacy < 0.4:
        parts.append("关系发展中。")
    if trust > 0.8:
        parts.append("对玩家有信任。")

    # 室友关系（数值 → 行为提示）
    roommates = get_all_roommates()
    rm_lines = []
    for name, val in roommates.items():
        label = {"sayori": "纱世里", "natsuki": "夏树", "yuri": "优里"}[name]
        if val > 0.8:
            rm_lines.append(f"和{label}亲近")
        elif val < 0.6:
            rm_lines.append(f"和{label}最近有些距离")
    if rm_lines:
        parts.append("室友: " + "；".join(rm_lines) + "。")

    # 信念
    if beliefs:
        active = sorted(beliefs, key=lambda b: b.get("confidence", 0), reverse=True)[:3]
        belief_texts = [b["content"] for b in active]
        parts.append("已有认知: " + "；".join(belief_texts) + "。")

    return " ".join(parts) if parts else ""


def _overlap(a, b):
    """简单字符重叠度。"""
    if not a or not b:
        return 0
    set_a = set(a)
    set_b = set(b)
    if not set_a:
        return 0
    return len(set_a & set_b) / len(set_a)
