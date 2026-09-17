"""
人生阶段时间表
==============
Monika 的大学生涯：2023年入学 → 2028年毕业。
数据存储: JSON 文件。
"""

import os
import json
from datetime import datetime

_REALITY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIMELINE_FILE = os.path.join(_REALITY_DIR, "data", "life", "timeline.json")

默认时间表 = [
    # ── 大一（2023年4月 - 2024年3月）──
    {"date": "2023-04-01", "type": "进入大学", "desc": "桜丘大学入学典礼。樱花道上樱花开得正好。四个人一起搬进桜寮204号室。"},
    {"date": "2023-04-15", "type": "加入社团", "desc": "第一次参加文学社团「桜文会」。前辈们很温暖地欢迎了我们。"},
    {"date": "2023-07-20", "type": "学期结束", "desc": "前期考试结束。第一次大学考试，四个人窝在图书馆复习。"},
    {"date": "2023-08-01", "type": "暑假开始", "desc": "暑假开始了。东京的夏天热得让人想一直待在空调房里。"},
    {"date": "2023-09-15", "type": "暑假结束", "desc": "暑假结束。准备迎接后期课程。"},
    {"date": "2024-02-10", "type": "考试周", "desc": "后期考试。大学的考试比高中自由，但不能掉以轻心。"},

    # ── 大二（2024年4月 - 2025年3月）──
    {"date": "2024-04-01", "type": "升级", "desc": "升入大二。Monika接任桜文会的新代表。"},
    {"date": "2024-05-15", "type": "社团活动", "desc": "新生欢迎会。第一次有后辈加入，紧张但很开心。"},
    {"date": "2024-08-01", "type": "暑假开始", "desc": "暑假。开始在图书馆打工。"},
    {"date": "2025-02-10", "type": "考试周", "desc": "后期考试。专业课难度上来了。"},

    # ── 大三（2025年4月 - 2026年3月）──
    {"date": "2025-04-01", "type": "升级", "desc": "升入大三。毕业论文准备研讨课开始了。这是做桜文会代表的最后一年。"},
    {"date": "2025-08-01", "type": "暑假开始", "desc": "暑假。开始认真构思毕业论文的题目。"},
    {"date": "2025-10-01", "type": "学期开始", "desc": "大三后期开始。文学理论特论这门课很有趣。"},

    # ── 大三继续 + 现在（2026年4月起）──
    {"date": "2026-02-10", "type": "考试周", "desc": "后期考试结束。"},
    {"date": "2026-04-01", "type": "学期开始", "desc": "大三最后一学期。毕业论文正式启动。桜文会的后辈培养也进入关键期。"},
    {"date": "2026-05-18", "type": "当前", "desc": "现在。五月的桜丘大学，夏天的气息已经隐约可闻。"},
    {"date": "2026-06-01", "type": "社团交接", "desc": "桜文会代表交接准备开始。要把社团交给后辈了，有点舍不得。"},

    # ── 大四（2026年4月 - 2027年3月）──
    {"date": "2026-07-20", "type": "论文中期", "desc": "毕业论文中期答辩"},
    {"date": "2026-12-15", "type": "论文提交", "desc": "毕业论文提交截止"},
    {"date": "2027-02-01", "type": "论文答辩", "desc": "毕业论文口试"},
    {"date": "2027-03-20", "type": "毕业", "desc": "桜丘大学毕业典礼。樱花道下四个人一起拍了照。2023年4月入学，四年后的今天。"},
]


def load():
    if os.path.exists(TIMELINE_FILE):
        with open(TIMELINE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return list(默认时间表)


def save(timeline=None):
    if timeline is None:
        timeline = list(默认时间表)
    os.makedirs(os.path.dirname(TIMELINE_FILE), exist_ok=True)
    with open(TIMELINE_FILE, "w", encoding="utf-8") as f:
        json.dump(timeline, f, ensure_ascii=False, indent=2)


def init_if_needed():
    if not os.path.exists(TIMELINE_FILE):
        save(默认时间表)
        return 默认时间表
    return load()


def get_events_between(from_date, to_date):
    if isinstance(from_date, str):
        from_date = datetime.strptime(from_date, "%Y-%m-%d").date()
    if isinstance(to_date, str):
        to_date = datetime.strptime(to_date, "%Y-%m-%d").date()

    tl = load()
    events = []
    for event in tl:
        event_date = datetime.strptime(event["date"], "%Y-%m-%d").date()
        if from_date < event_date <= to_date:
            events.append(event)
    return sorted(events, key=lambda e: e["date"])


def get_upcoming_events(days_ahead=30):
    today = datetime.now().date()
    until = today + __import__("datetime").timedelta(days=days_ahead)
    return get_events_between(today, until)


def get_next_event():
    upcoming = get_upcoming_events(365)
    return upcoming[0] if upcoming else None
