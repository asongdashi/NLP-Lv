"""
统一存储 API
============
SQLite + Qdrant + JSONL 的统一入口。
所有模块通过 Storage 类读写，不再直接操作 JSON 文件。
"""

import os
import json
from datetime import datetime

from .sqlite_schema import init_db, get_conn
from .qdrant_client import get_client as qdrant_get_client

class Storage:
    def __init__(self):
        init_db()
        self.db = get_conn()

    # ═══ Self State ═══

    def get_self_state(self, category, key, default=0.5):
        row = self.db.execute(
            "SELECT value FROM self_state WHERE category=? AND key=?", (category, key)
        ).fetchone()
        return row["value"] if row else default

    def set_self_state(self, category, key, value):
        self.db.execute(
            "INSERT OR REPLACE INTO self_state(category, key, value, updated_at) VALUES(?,?,?,?)",
            (category, key, value, datetime.now().isoformat()),
        )
        self.db.commit()

    def get_all_self_state(self):
        rows = self.db.execute("SELECT category, key, value FROM self_state").fetchall()
        result = {"identity": {}, "relationship": {}}
        for r in rows:
            result.setdefault(r["category"], {})[r["key"]] = r["value"]
        return result

    # ═══ Beliefs ═══

    def add_belief(self, content, confidence=0.5):
        now = datetime.now().isoformat()
        # 去重
        existing = self.db.execute(
            "SELECT id, confidence FROM beliefs WHERE content LIKE ? AND active=1",
            (f"%{content[:30]}%",),
        ).fetchone()
        if existing:
            self.db.execute(
                "UPDATE beliefs SET confidence=MAX(?,confidence), updated_at=? WHERE id=?",
                (confidence, now, existing["id"]),
            )
        else:
            self.db.execute(
                "INSERT INTO beliefs(content, confidence, formed_at) VALUES(?,?,?)",
                (content, confidence, now),
            )
        self.db.commit()

    def get_active_beliefs(self, limit=10):
        rows = self.db.execute(
            "SELECT content, confidence FROM beliefs WHERE active=1 ORDER BY confidence DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [(r["content"], r["confidence"]) for r in rows]

    # ═══ Goals ═══

    def set_goals(self, category, texts):
        # deactivate old goals for this category
        self.db.execute("UPDATE goals SET active=0 WHERE category=?", (category,))
        now = datetime.now().isoformat()
        for t in texts:
            self.db.execute(
                "INSERT INTO goals(text, category, created_at) VALUES(?,?,?)",
                (t, category, now),
            )
        self.db.commit()

    def get_goals(self, category=None):
        if category:
            rows = self.db.execute(
                "SELECT text, category FROM goals WHERE active=1 AND category=? ORDER BY id",
                (category,),
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT text, category FROM goals WHERE active=1 ORDER BY id"
            ).fetchall()
        return [(r["text"], r["category"]) for r in rows]

    # ═══ Life Events ═══

    def save_daily_events(self, date_str, events, meta=None):
        # 删除旧数据
        self.db.execute("DELETE FROM life_events WHERE date=?", (date_str,))
        for ev in events:
            self.db.execute(
                """INSERT INTO life_events(date, weekday, time, end_time, activity, detail,
                   participants, can_reply, sneak_possible, sub_events, generated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    date_str,
                    meta.get("weekday", "") if meta else "",
                    ev.get("time", ""),
                    ev.get("end", ""),
                    ev.get("activity", ""),
                    ev.get("detail", ""),
                    json.dumps(ev.get("participants", []), ensure_ascii=False),
                    1 if ev.get("can_reply", True) else 0,
                    1 if ev.get("sneak_possible", False) else 0,
                    json.dumps(ev.get("sub_events", []), ensure_ascii=False),
                    datetime.now().isoformat(),
                ),
            )
        self.db.commit()

    def get_daily_events(self, date_str):
        rows = self.db.execute(
            "SELECT * FROM life_events WHERE date=? ORDER BY time", (date_str,)
        ).fetchall()
        events = []
        for r in rows:
            ev = {
                "time": r["time"], "end": r["end_time"], "activity": r["activity"],
                "detail": r["detail"],
                "participants": json.loads(r["participants"]) if r["participants"] else [],
                "can_reply": bool(r["can_reply"]),
                "sneak_possible": bool(r["sneak_possible"]),
            }
            if r["sub_events"]:
                ev["sub_events"] = json.loads(r["sub_events"])
            events.append(ev)
        return events

    # ═══ Emotion Events ═══

    def add_emotion_event(self, event_type, impact, half_life_h=4):
        self.db.execute(
            "INSERT INTO emotion_events(type, impact, half_life_h, created_at) VALUES(?,?,?,?)",
            (event_type, json.dumps(impact, ensure_ascii=False), half_life_h, datetime.now().isoformat()),
        )
        self.db.commit()

    def get_active_emotion_events(self):
        rows = self.db.execute(
            "SELECT * FROM emotion_events WHERE decayed=0 ORDER BY created_at"
        ).fetchall()
        return [
            {
                "id": r["id"], "type": r["type"],
                "impact": json.loads(r["impact"]), "half_life_h": r["half_life_h"],
                "created_at": r["created_at"], "decayed": bool(r["decayed"]),
            }
            for r in rows
        ]

    def mark_emotion_decayed(self, event_id):
        self.db.execute("UPDATE emotion_events SET decayed=1 WHERE id=?", (event_id,))
        self.db.commit()

    # ═══ Reflections ═══

    def save_reflection(self, date_str, events_summary, journal_summary, result):
        self.db.execute(
            "INSERT INTO reflections(date, events_summary, journal_summary, result, created_at) VALUES(?,?,?,?,?)",
            (date_str, events_summary, journal_summary, result, datetime.now().isoformat()),
        )
        self.db.commit()

    def get_recent_reflections(self, limit=5):
        rows = self.db.execute(
            "SELECT * FROM reflections ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ═══ Chat Messages ═══

    def save_chat_message(self, who, text, timestamp=None):
        ts = timestamp or datetime.now().isoformat()
        self.db.execute(
            "INSERT INTO chat_messages(timestamp, who, text) VALUES(?,?,?)",
            (ts, who, text),
        )
        self.db.commit()


# ── 全局单例 ──

def get_storage():
    return Storage()
