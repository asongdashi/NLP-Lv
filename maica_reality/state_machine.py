"""
状态机 — Monika 的"五感"
==========================
7 个 Condition 独立监控世界状态。
条件满足时向管道 push 自然语言消息。
所有数据来源均为 SQLite（不再依赖 JSON 文件）。
"""

import os
import time
import threading
from datetime import datetime

_REALITY_DIR = os.path.dirname(os.path.abspath(__file__))

from pipe_loop import PipeMessage
from config import logger

# 顶层导入 Storage，所有 Condition 复用
try:
    from storage.api import Storage
    _STORAGE = Storage()
except ImportError as e:
    logger.warning(f"[SM] Storage unavailable: {e}")
    _STORAGE = None


class Condition:
    """条件基类。每个条件独立判断是否触发。"""
    name = "base"
    priority = 5
    cooldown_sec = 600  # 默认 10 分钟冷却

    def __init__(self):
        self._last_fired = 0

    def should_fire(self) -> bool:
        if time.time() - self._last_fired < self.cooldown_sec:
            return False
        return self._check()

    def _check(self) -> bool:
        return False

    def build_message(self) -> str:
        return ""

    def mark_fired(self):
        self._last_fired = time.time()


# ═══ 具体条件 ═══


class MealCondition(Condition):
    name = "meal"
    priority = 6
    cooldown_sec = 10800  # 3 小时 — 三餐各触发一次

    def _check(self):
        h = datetime.now().hour
        return (7 <= h < 9) or (11 <= h < 13) or (17 <= h < 19)

    def build_message(self):
        h = datetime.now().hour
        if 7 <= h < 9:
            return "[饮食提醒] 早餐时间。Monika想提醒玩家吃早饭。"
        elif 11 <= h < 13:
            return "[饮食提醒] 午餐时间。Monika想问玩家中午吃了什么。"
        return "[饮食提醒] 晚饭时间。玩家吃晚饭了吗？"


class WeatherCondition(Condition):
    name = "weather"
    priority = 8
    cooldown_sec = 3600

    def _check(self):
        try:
            from shared_state import player_online
            if not player_online:
                return False
            snap_file = os.path.join(_REALITY_DIR, "data", "state", "last_weather.json")
            if not os.path.exists(snap_file):
                return False
            with open(snap_file, "r", encoding="utf-8") as f:
                snap = json.load(f)
            cond = snap.get("condition", "")
            return any(w in cond for w in ["雨", "雪", "台风", "暴雨"])
        except Exception:
            return False

    def build_message(self):
        return "[天气提醒] 天气变了。Monika想提醒玩家带伞或注意保暖。"


class GoalCondition(Condition):
    """目标与进度 — 检测今天 life_events 中是否有论文/社团/打工相关活动。"""
    name = "goal"
    priority = 6
    cooldown_sec = 10800  # 3 小时 — 上午最多触发 2 次

    _GOAL_KEYWORDS = ['论文', '社团', '桜文', '打工', '图书馆', '写作', '研讨', '答辩']

    def _check(self):
        """检测：上午时段 (7-12h) 且今天 life_events 有目标相关活动。"""
        h = datetime.now().hour
        if not (7 <= h < 12):
            return False
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            events = _STORAGE.get_daily_events(today) if _STORAGE else []
            for ev in events:
                text = json.dumps(ev, ensure_ascii=False)
                if any(kw in text for kw in self._GOAL_KEYWORDS):
                    return True
        except Exception:
            pass
        return False

    def build_message(self):
        """从 life_events 中提取目标相关活动，组装触发消息。"""
        today = datetime.now().strftime("%Y-%m-%d")
        events = _STORAGE.get_daily_events(today) if _STORAGE else []
        relevant = []
        for ev in events:
            text = json.dumps(ev, ensure_ascii=False)
            if any(kw in text for kw in self._GOAL_KEYWORDS):
                line = f"{ev['time']}-{ev['end']} {ev['activity']}"
                if ev.get('detail'):
                    line += f"：{ev['detail']}"
                if ev.get('participants'):
                    line += f"（和{'、'.join(ev['participants'])}一起）"
                relevant.append(line)

        if not relevant:
            return "[目标] Monika在思考今天的计划。"

        return "[目标与进度] 今天 Monika 有以下安排：\n" + "\n".join(relevant[:4])


class DormCondition(Condition):
    """宿舍生活 — 检测今晚 life_events 中是否有宿舍相关活动。"""
    name = "dorm"
    priority = 2
    cooldown_sec = 7200  # 2 小时 — 晚上最多触发 2 次

    _DORM_NAMES = ['纱世里', '夏树', '优里']
    _DORM_KEYWORDS = ['宿舍', '桜寮', '204', '晚饭', '洗澡', '睡前', '室友',
                       '聊天', '综艺', '点心', '看书', '日记', '纱世里', '夏树', '优里']

    def _check(self):
        """检测：晚上时间段 AND 今天 life_events 有晚间宿舍相关活动。"""
        h = datetime.now().hour
        if not (19 <= h < 23):
            return False
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            events = _STORAGE.get_daily_events(today) if _STORAGE else []
            for ev in events:
                if ev.get("time", "00:00") >= "18:00":
                    text = json.dumps(ev, ensure_ascii=False)
                    # 有室友参与 或 活动内容含宿舍关键词
                    pts = [p for p in ev.get("participants", [])
                           if p in self._DORM_NAMES]
                    if pts or any(kw in text for kw in self._DORM_KEYWORDS):
                        return True
        except Exception:
            pass
        return False

    def build_message(self):
        """从 life_events 中提取今晚的宿舍相关活动。"""
        today = datetime.now().strftime("%Y-%m-%d")
        events = _STORAGE.get_daily_events(today) if _STORAGE else []
        evening = []
        for ev in events:
            if ev.get("time", "00:00") < "18:00":
                continue
            text = json.dumps(ev, ensure_ascii=False)
            pts = [p for p in ev.get("participants", []) if p in self._DORM_NAMES]
            if pts or any(kw in text for kw in self._DORM_KEYWORDS):
                line = f"{ev['time']} {ev['activity']}"
                if ev.get('detail'):
                    line += f" — {ev['detail']}"
                if pts:
                    line += f"【{'、'.join(pts)}在场】"
                # 子事件（如做点心、写日记等细节）
                for se in ev.get("sub_events", [])[:2]:
                    line += f"\n  · {se.get('time', '')} {se.get('what', '')}"
                evening.append(line)

        if not evening:
            return "[宿舍] 204号室的夜晚。Monika和室友们在宿舍里。"

        return "[宿舍生活] 今晚的204号室：\n" + "\n".join(evening[:3])


class StateMachine:
    """状态机主循环。后台线程，独立运行。"""

    def __init__(self, pipe):
        self.pipe = pipe
        self._stop = threading.Event()
        self.conditions = [
            MealCondition(),
            WeatherCondition(),
            GoalCondition(),
            DormCondition(),
        ]

    def _run(self):
        logger.info("[SM] State machine started")
        while not self._stop.is_set():
            for cond in self.conditions:
                try:
                    if cond.should_fire():
                        msg = cond.build_message()
                        if msg:
                            if self.pipe is not None:
                                # 同进程模式：直接推到 Pipe
                                self.pipe.put(PipeMessage(
                                    source="state_machine",
                                    text=msg,
                                    priority=cond.priority,
                                ))
                            else:
                                # 独立进程模式：推到 message_queue，bridge 通过 /api/pending 轮询
                                from shared_state import message_queue, message_queue_lock
                                with message_queue_lock:
                                    message_queue.append({
                                        "id": f"sm_{int(time.time())}_{cond.name}",
                                        "text": msg,
                                        "trigger": cond.name,
                                        "priority": cond.priority,
                                        "created_at": datetime.now().isoformat(),
                                    })
                            logger.info(f"[SM] {cond.name}: {msg[:80]}")
                            cond.mark_fired()
                except Exception as e:
                    logger.debug(f"[SM] {cond.name} error: {e}")
            self._stop.wait(10)

    def start(self):
        t = threading.Thread(target=self._run, daemon=True)
        t.start()
        return t

    def stop(self):
        self._stop.set()
