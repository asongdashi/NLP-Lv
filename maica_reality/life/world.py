"""
世界设定管理
============
Monika 的生活环境。字段名使用中文。
数据存储: JSON 文件。
"""

import os
import json
from datetime import datetime, timedelta

_REALITY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORLD_FILE = os.path.join(_REALITY_DIR, "data", "life", "world.json")


def _current_season():
    m = datetime.now().month
    if 3 <= m <= 5: return "春"
    if 6 <= m <= 8: return "夏"
    if 9 <= m <= 11: return "秋"
    return "冬"


DEFAULT_WORLD = {
    "国家": "日本", "城市": "东京",
    "大学": "桜丘大学", "大学类型": "私立·中上水平·人文系强",
    "学部": "文学部 人文学科", "年级": "大三",
    "社团": "文学社团「桜文会」（代表，即将卸任）",
    "宿舍": "桜寮 204号室", "室友": ["纱世里", "夏树", "优里"],
    "季节": _current_season(),
    "学期": "前期（春学期）",
    "当前日期": datetime.now().strftime("%Y-%m-%d"),
    "起始日期": "2023-04-01",
    "入学时间": "2023年4月（现在大三）",
}


def load():
    if os.path.exists(WORLD_FILE):
        with open(WORLD_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return dict(DEFAULT_WORLD)


def save(world):
    os.makedirs(os.path.dirname(WORLD_FILE), exist_ok=True)
    with open(WORLD_FILE, "w", encoding="utf-8") as f:
        json.dump(world, f, ensure_ascii=False, indent=2)


def init_if_needed():
    if not os.path.exists(WORLD_FILE):
        save(DEFAULT_WORLD)
        return DEFAULT_WORLD
    return load()


def update_season():
    w = load()
    new_season = _current_season()
    if w.get("季节") != new_season:
        w["季节"] = new_season
        save(w)
        return True
    return False


def advance_date(days=1):
    w = load()
    old = datetime.strptime(w["当前日期"], "%Y-%m-%d")
    new = (old + timedelta(days=days)).strftime("%Y-%m-%d")
    w["当前日期"] = new
    w["季节"] = _current_season()
    save(w)
    return w


def apply_event(event):
    """应用人生阶段事件到世界设定。"""
    w = load()
    etype = event.get("type", "")
    desc = event.get("desc", "")

    if etype in ("升级", "grade_promotion"):
        if "大二" in desc:
            w["年级"] = "大二"
        elif "大三" in desc:
            w["年级"] = "大三"
        elif "大四" in desc:
            w["年级"] = "大四"
        w["社团"] = event.get("new_club", w.get("社团", ""))

    elif etype in ("毕业", "school_change"):
        w["年级"] = "毕业"

    w["当前日期"] = event.get("date", w["当前日期"])
    w["季节"] = _current_season()
    save(w)
    return w


def _get(obj, path, default=""):
    keys = path.split(".")
    for k in keys:
        if isinstance(obj, dict):
            obj = obj.get(k, default)
        else:
            return default
    return obj or default


def get_world_context():
    w = load()

    大学 = w.get("大学", {})
    学部 = w.get("学部", {})
    宿舍 = w.get("宿舍", {})
    社团 = w.get("社团", {})

    roommates = "、".join(宿舍.get("室友", [])) if isinstance(宿舍, dict) else "纱世里、夏树、优里"
    grade = _get(w, "学部.年级") or _get(w, "年级", "大四")
    university = _get(w, "大学.名称") or _get(w, "大学", "")
    department = _get(w, "学部.名称") or _get(w, "学部", "")
    major = _get(w, "学部.专业") or ""
    dorm = _get(w, "宿舍.名称") or _get(w, "宿舍", "")
    club_name = _get(w, "社团.名称") or _get(w, "社团", "")
    club_role = _get(w, "社团.职务") or ""

    lines = [
        f"国家: {w.get('国家','日本')}，城市: {w.get('城市','东京')}",
        f"大学: {university}（{_get(w,'大学.类型','')}），校风: {_get(w,'大学.校风','')}",
        f"学部: {department}，专业: {major}，年级: {grade}",
        f"学籍: {_get(w,'学部.学籍','')}，毕业要件: {_get(w,'学部.毕业要件','')}",
        f"季节: {w.get('季节','')}，学期: {w.get('学期','')}",
        f"宿舍: {dorm}，{_get(w,'宿舍.类型','')}，室友: {roommates}",
        f"Monika的床位: {_get(w,'宿舍.Monika的床位','')}",
        f"社团: {club_name}，职务: {club_role}",
        f"当前状态: {w.get('当前状态','')}",
    ]
    return "\n".join(lines)
