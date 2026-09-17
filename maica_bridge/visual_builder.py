"""
展示数据构建器

从 MemorySystem + MAICABridge 中提取结构化数据，
附加到 5202 帧的 visual 字段，供 APP 端渲染。
"""

import time
import logging

from config import ENABLE_HEALTH_SYNC

logger = logging.getLogger("maica_bridge")

_EMOTION_ICONS = {
    "微笑": "smile", "开心": "happy", "担心": "worry", "思考": "think",
    "脸红": "blush", "惊讶": "surprise", "尴尬": "awkward", "生气": "angry",
    "伤心": "sad", "得意": "proud", "憧憬": "dream", "感动": "touched",
    "严肃": "serious", "害怕": "fear", "嫌弃": "disgust",
}


class VisualBuilder:
    def __init__(self, memory_system, bridge):
        self._ms = memory_system
        self._bridge = bridge

    def build(self, is_first: bool = False) -> dict:
        return {
            "emotion": self._build_emotion(),
            "activity": self._build_activity(),
            "context_peek": self._build_context_peek(),
            "stats": self._build_stats(),
        }

    # ── 情绪 ──

    def _build_emotion(self) -> dict:
        try:
            import requests
            resp = requests.get("http://127.0.0.1:6101/api/emotion", timeout=2)
            if resp.status_code == 200:
                data = resp.json()
                current = data.get("dominant", "微笑")
                strength = data.get("strength", 0.3)
                icon = _EMOTION_ICONS.get(current, "smile")
                return {"current": current, "strength": float(strength), "icon": icon}
        except Exception:
            pass
        return {"current": "微笑", "strength": 0.3, "icon": "smile"}

    # ── 当前活动 ──

    def _build_activity(self) -> str:
        from datetime import datetime
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        now_min = now.hour * 60 + now.minute
        try:
            from storage.api import Storage
            events = Storage().get_daily_events(today)
            for ev in events:
                t = ev.get("time", "00:00")
                ev_end = ev.get("end", "")
                act = ev.get("activity", "")
                detail = ev.get("detail", "")
                start_min = _parse_minutes(t)
                end_min = _parse_minutes(ev_end) if ev_end else start_min + 60
                if act == "睡觉" and end_min <= start_min:
                    end_min += 24 * 60
                check = now_min
                if act == "睡觉" and now_min < end_min:
                    check = now_min + 24 * 60
                if start_min <= check < end_min:
                    return detail or act
        except Exception:
            pass
        return ""

    # ── 上下文摘要 ──

    def _build_context_peek(self) -> dict:
        peek = {"health": {}, "memory_hint": "", "resume_flag": False}

        # 健康数据
        if ENABLE_HEALTH_SYNC:
            h = getattr(self._ms, '_health_data', {}) or {}
            for key, fn in [
                ("sleep", self._fmt_sleep),
                ("heart_rate", self._fmt_hr),
                ("steps", self._fmt_steps),
                ("blood_pressure", self._fmt_bp),
                ("stress", self._fmt_stress),
            ]:
                result = fn(h)
                if result:
                    peek["health"][key] = result

        return peek

    def _data_age(self) -> float:
        h = getattr(self._ms, '_health_data', {}) or {}
        ts = h.get("timestamp", 0)
        return time.time() - ts if ts else 0

    def _fmt_sleep(self, h: dict) -> dict:
        s = h.get("sleep", {})
        total = s.get("total_hours", 0)
        if not total:
            return {"label": "睡眠 -", "status": "missing"}
        deep = s.get("deep_hours", 0)
        label = f"昨晚 {total}h" + (f"（深睡 {deep}h）" if deep else "")
        return {"label": label, "status": "ready"}

    def _fmt_hr(self, h: dict) -> dict:
        hr = h.get("heart_rate", {})
        val = hr.get("current", 0)
        if not val:
            return {"label": "心率 -", "status": "missing"}
        age = self._data_age()
        if age > 600:
            return {"label": f"心率 {val}（{int(age/60)}分钟前）", "status": "stale"}
        return {"label": f"心率 {val}", "status": "ready"}

    def _fmt_steps(self, h: dict) -> dict:
        s = h.get("steps", {})
        val = s.get("today", 0)
        goal = s.get("goal", 8000)
        if not val:
            return {"label": "步数 -", "status": "missing"}
        pct = int(val / goal * 100) if goal else 0
        return {"label": f"{val}/{goal}（{pct}%）", "status": "ready"}

    def _fmt_bp(self, h: dict) -> dict:
        bp = h.get("blood_pressure", {})
        s_val = bp.get("systolic", 0)
        d_val = bp.get("diastolic", 0)
        if not s_val:
            return {"label": "血压 -", "status": "missing"}
        return {"label": f"{s_val}/{d_val}", "status": bp.get("status", "正常")}

    def _fmt_stress(self, h: dict) -> dict:
        st = h.get("stress", {})
        level = st.get("level", "")
        if not level:
            return {"label": "压力 -", "status": "missing"}
        return {"label": level, "status": "ready"}

    # ── 对话统计 ──

    def _build_stats(self) -> dict:
        try:
            from maica_protocol import get_session_duration_text
            duration = get_session_duration_text("1")
        except Exception:
            duration = "未知"
        return {"session_duration": duration}


def _parse_minutes(t: str) -> int:
    parts = t.split(":")
    if len(parts) >= 2:
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except Exception:
            pass
    return 0
