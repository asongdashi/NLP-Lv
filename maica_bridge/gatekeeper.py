"""
门控系统 v3 — 事件驱动
======================
读取生成器产出的结构化事件日志，精确判断 Monika 当前活动。
忙时发送自动回复，上课时有概率偷回。
"""

import os
import json
import random
from datetime import datetime

_BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))

ACTIVITY_REPLIES = {
    "睡觉":       {"resolve": "早上7点",   "tmpl": "[自动回复] Monika在睡觉～她会在{resolve}后回复你。晚安~"},
    "上课90分钟": {"resolve": "下课后",   "tmpl": "[自动回复] Monika正在上课，预计{resolve}回复你。不急的话等一下哦~"},
    "上课45分钟": {"resolve": "下课后",   "tmpl": "[自动回复] Monika正在上课，预计{resolve}回复你。"},
    "吃早饭":     {"resolve": "一会儿",   "tmpl": "[自动回复] Monika在吃早饭～{resolve}就回来。"},
    "吃午饭":     {"resolve": "一会儿",   "tmpl": "[自动回复] Monika在吃午饭～{resolve}就回来。"},
    "吃晚饭":     {"resolve": "一会儿",   "tmpl": "[自动回复] Monika在吃晚饭～{resolve}就回来。"},
    "洗澡":       {"resolve": "洗完澡",   "tmpl": "[自动回复] Monika在洗澡，{resolve}就来找你 [害羞]"},
    "打工":       {"resolve": "下班后",   "tmpl": "[自动回复] Monika在图书馆打工，{resolve}回复你～"},
    "社团活动":   {"resolve": "社团结束后","tmpl": "[自动回复] Monika在社团活动中，{resolve}回复你。"},
    "写作业":     {"resolve": "写完后",   "tmpl": "[自动回复] Monika在写作业，{resolve}回复你。"},
}

_sneaked_today = False


def _parse_time(t):
    parts = t.split(":")
    return int(parts[0]) * 60 + int(parts[1])


def get_current_event():
    """读取今日事件日志，找到当前时间所在的事件。通过 Storage API。"""
    from storage.api import Storage
    events = Storage().get_daily_events(datetime.now().strftime("%Y-%m-%d"))
    if not events:
        if datetime.now().hour < 7 or datetime.now().hour >= 23:
            return {"activity": "睡觉", "detail": "", "end": "07:00" if datetime.now().hour < 7 else "23:59"}
        return None

    now_min = datetime.now().hour * 60 + datetime.now().minute
    for ev in events:
        start = _parse_time(ev.get("time", "00:00"))
        end = _parse_time(ev.get("end", "00:00"))
        if start <= now_min < end:
            return ev

    if datetime.now().hour < 7 or datetime.now().hour >= 23:
        return {"activity": "睡觉", "detail": "", "end": "07:00" if datetime.now().hour < 7 else "23:59"}
    return None


def handle_player_message(msg):
    """返回 None（正常对话）、auto_reply dict、或 sneak dict。
    门控独立判断——不读 can_reply 字段，自行根据活动类型决策。"""
    ev = get_current_event()

    if not ev:
        return None

    activity = ev.get("activity", "")
    end_time = ev.get("end", "")
    can_reply = ev.get("can_reply", True)
    sneak_possible = ev.get("sneak_possible", False)

    # 1. 偷回
    global _sneaked_today
    if sneak_possible and not _sneaked_today and random.random() < 0.12:
        _sneaked_today = True
        return {"type": "sneak", "msg": msg,
                "context": f"你正在{activity}，看了一眼手机。回复简短，自然提及你正在做什么。"}

    # 2. can_reply=false → 自动回复
    if not can_reply:
        cfg = ACTIVITY_REPLIES.get(activity)
        if cfg:
            resolve = cfg["resolve"]
            return {"type": "auto_reply", "text": cfg["tmpl"].format(resolve=resolve)}
        return {"type": "auto_reply", "text": f"[自动回复] Monika正在{activity}，稍后回复你。"}

    # 3. can_reply=true → 正常对话
    return None


def reset_sneak():
    global _sneaked_today
    today = datetime.now().strftime("%Y-%m-%d")
    if not hasattr(reset_sneak, "_date"):
        reset_sneak._date = today
    if today != reset_sneak._date:
        _sneaked_today = False
        reset_sneak._date = today
