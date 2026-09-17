"""
经历日志管理模块

每次对话后，以第三人称客观叙事记录：
- 时间 / 地点 / 天气
- 对话摘要

格式：JSONL 每行一条记录
用途：让 Monika "回顾"过去的对话经历（时间范围查询、关键词搜索）
"""

import os
import json
import time
import logging

logger = logging.getLogger("maica_bridge.rag")

JOURNAL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "journals")
JOURNAL_PATH = os.path.join(JOURNAL_DIR, "experience.jsonl")


def _ensure_dir():
    os.makedirs(JOURNAL_DIR, exist_ok=True)


def add_entry(location: str = "", weather: str = "", summary: str = ""):
    """追加一条经历日志。"""
    _ensure_dir()
    from datetime import datetime, timezone, timedelta
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    weekday_zh = ["一", "二", "三", "四", "五", "六", "日"]
    wd = weekday_zh[now.weekday()]

    entry = {
        "time": f"{now.strftime('%Y-%m-%d %H:%M:%S')} 星期{wd}",
        "location": location,
        "weather": weather,
        "summary": summary,
    }
    with open(JOURNAL_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.info(f"Journal entry added: {summary[:80]}...")


def get_recent_entries(days: int = 7, keyword: str = "", max_count: int = 5):
    """获取最近若干天的经历条目（可选关键词过滤）。"""
    if not os.path.exists(JOURNAL_PATH):
        return []

    from datetime import datetime, timezone, timedelta
    tz = timezone(timedelta(hours=8))
    cutoff = (datetime.now(tz) - timedelta(days=days)).strftime("%Y-%m-%d")

    entries = []
    with open(JOURNAL_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if days > 0 and entry.get("time", "")[:10] < cutoff:
                    continue
                if keyword and keyword.lower() not in entry.get("summary", "").lower():
                    continue
                entries.append(entry)
            except json.JSONDecodeError:
                continue

    return entries[-max_count:]


def count_entries():
    """返回经历日志总条数。"""
    if not os.path.exists(JOURNAL_PATH):
        return 0
    count = 0
    with open(JOURNAL_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count
