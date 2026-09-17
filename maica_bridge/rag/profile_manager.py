"""
玩家档案管理模块

Monika 对玩家的认知存储:
- 位置 (城市/省份/国家) → 天气查询默认城市
- 身份 (职业/兴趣等)
- 偏好 (昵称/语言/话题偏好)

档案由 Monika 通过 update_profile 工具写入，在RAG检索时注入系统提示。
"""

import os
import json
import time
import logging

logger = logging.getLogger("maica_bridge.rag")

PROFILE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "profile")
PROFILE_PATH = os.path.join(PROFILE_DIR, "player_profile.json")

_DEFAULT_PROFILE = {
    "player_name": "",
    "location": {
        "city": "",
        "province": "",
        "country": "中国",
    },
    "identity": {
        "occupation": "",
        "interests": [],
        "note": "",
    },
    "preferences": {
        "nickname": "",
        "language": "zh",
        "topics_of_interest": [],
    },
    "updated_at": "",
}


def _load_profile():
    """加载档案，不存在则创建默认档案。"""
    os.makedirs(PROFILE_DIR, exist_ok=True)
    if not os.path.exists(PROFILE_PATH):
        _save_profile(_DEFAULT_PROFILE)
        return dict(_DEFAULT_PROFILE)
    try:
        with open(PROFILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.warning("Failed to load profile, using default")
        return dict(_DEFAULT_PROFILE)


def _save_profile(profile):
    """保存档案到文件。"""
    os.makedirs(PROFILE_DIR, exist_ok=True)
    with open(PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)


def get_profile():
    """获取当前玩家档案。"""
    return _load_profile()


def sync_player_name(name: str):
    """服务启动时将 config.json 中的 player_name 同步到档案（仅首次）。"""
    if not name:
        return
    profile = _load_profile()
    if not profile.get("player_name"):
        profile["player_name"] = name
        _save_profile(profile)
        logger.info(f"Profile synced: player_name = {name}")


def update_profile(field: str, value: str) -> str:
    """
    更新档案中的指定字段。

    支持点号路径：
      location.city, location.province, identity.occupation
      preferences.nickname, preferences.language
      player_name (顶级字段)

    返回确认消息。
    """
    profile = _load_profile()
    field = field.strip().lower()

    # 解析路径
    parts = field.split(".")
    # 映射可能的字段名变体
    field_map = {
        "location.city": ("location", "city"),
        "location.province": ("location", "province"),
        "location.country": ("location", "country"),
        "identity.occupation": ("identity", "occupation"),
        "identity.interests": ("identity", "interests"),
        "identity.note": ("identity", "note"),
        "preferences.nickname": ("preferences", "nickname"),
        "preferences.language": ("preferences", "language"),
        "preferences.topics_of_interest": ("preferences", "topics_of_interest"),
        "player_name": ("_top", "player_name"),
    }

    # 精确匹配
    key = field
    if key not in field_map:
        # 模糊匹配
        candidates = [k for k in field_map if k.endswith(field) or field in k]
        if len(candidates) == 1:
            key = candidates[0]
        elif len(candidates) > 1:
            return f"字段 '{field}' 匹配到多个可能项: {', '.join(candidates)}，请明确指定。"
        else:
            return f"未知字段 '{field}'。可更新的字段: {', '.join(field_map.keys())}"

    section, fname = field_map[key]
    if section == "_top":
        profile[fname] = value
    elif isinstance(profile.get(section), dict):
        profile[section][fname] = value
    else:
        return f"无法更新字段 '{field}'"

    profile["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_profile(profile)
    logger.info(f"Profile updated: {field} = {value}")
    return f"已更新档案：{field} = {value}"


def get_location_city():
    """获取档案中的城市（用于天气默认值）。"""
    profile = get_profile()
    city = (profile.get("location") or {}).get("city", "")
    return city if city else ""


_profile_cache = {"text": "", "ts": 0}
_PROFILE_CACHE_TTL = 60  # 档案很少变，60s 缓存

def profile_to_prompt() -> str:
    """将档案格式化为系统提示片段。"""
    import time
    now = time.time()
    if now - _profile_cache["ts"] < _PROFILE_CACHE_TTL:
        return _profile_cache["text"]

    profile = get_profile()
    parts = []

    name = profile.get("player_name", "")
    if name:
        parts.append(f"玩家姓名: {name}")

    loc = profile.get("location", {})
    loc_str = " ".join(filter(None, [
        loc.get("country", ""),
        loc.get("province", ""),
        loc.get("city", ""),
    ]))
    if loc_str:
        parts.append(f"玩家位置: {loc_str}")

    ident = profile.get("identity", {})
    occ = ident.get("occupation", "")
    if occ:
        parts.append(f"玩家职业: {occ}")
    interests = ident.get("interests", [])
    if interests:
        parts.append(f"玩家兴趣: {', '.join(interests)}")
    note = ident.get("note", "")
    if note:
        parts.append(f"备注: {note}")

    pref = profile.get("preferences", {})
    nick = pref.get("nickname", "")
    if nick:
        parts.append(f"玩家偏好的称呼: {nick}")

    if not parts:
        _profile_cache["text"] = ""
        _profile_cache["ts"] = now
        return ""

    result = (
        "\n[PROFILE — 你对玩家的已知信息。"
        "如果话题涉及位置、职业等，请依据此信息。"
        "如果你了解到新信息，你可以通过 update_profile 工具更新。]\n"
        + "\n".join(parts)
    )
    _profile_cache["text"] = result
    _profile_cache["ts"] = now
    return result
