"""
日志压缩器
==========
将旧日志逐层压缩：日 → 周摘要 → 月摘要 → 印象。
"""

import os
import json
from datetime import datetime, timedelta

from config import logger

_REALITY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY_DIR = os.path.join(_REALITY_DIR, "data", "life", "daily")
WEEKLY_DIR = os.path.join(_REALITY_DIR, "data", "life", "weekly")
MONTHLY_DIR = os.path.join(_REALITY_DIR, "data", "life", "monthly")


def compress_if_needed():
    """检查并执行需要的压缩。"""
    today = datetime.now().date()

    # 压缩 7 天前的日志为周摘要
    _compress_daily_to_weekly(today)

    # 压缩 30 天前的周摘要为月摘要
    _compress_weekly_to_monthly(today)


def _compress_daily_to_weekly(today):
    """将距今 7-14 天的日日志压缩为周摘要。"""
    cutoff = today - timedelta(days=7)
    # 收集需要压缩的日期
    to_compress = []
    for fname in os.listdir(DAILY_DIR):
        if not fname.endswith(".json") or fname.startswith("gap_"):
            continue
        try:
            date_str = fname.replace(".json", "")
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
            if d < cutoff:
                to_compress.append((date_str, d))
        except ValueError:
            continue

    if not to_compress:
        return

    # 按周分组
    from collections import defaultdict
    weeks = defaultdict(list)
    for date_str, d in to_compress:
        # ISO 周: 获取该日期所属周的周一
        monday = d - timedelta(days=d.weekday())
        week_key = monday.strftime("%Y-%m-%d")
        weeks[week_key].append(date_str)

    for week_start, dates in weeks.items():
        if len(dates) < 3:
            continue  # 不足 3 天不值得压缩

        # 读取这些天的日志
        all_text = []
        for date_str in sorted(dates):
            path = os.path.join(DAILY_DIR, f"{date_str}.json")
            try:
                with open(path, "r", encoding="utf-8") as f:
                    log = json.load(f)
                for ev in log.get("events", []):
                    s = ev.get("detail", "")
                    if s:
                        all_text.append(s)
            except Exception:
                pass

        if all_text:
            summary = _summarize_week(all_text, week_start, dates)
            if summary:
                week_end = (datetime.strptime(week_start, "%Y-%m-%d") + timedelta(days=6)).strftime("%Y-%m-%d")
                compressed = {
                    "type": "weekly",
                    "week_start": week_start,
                    "week_end": week_end,
                    "dates": sorted(dates),
                    "summary": summary,
                    "compressed_at": datetime.now().isoformat(),
                }
                os.makedirs(WEEKLY_DIR, exist_ok=True)
                wk_path = os.path.join(WEEKLY_DIR, f"{week_start}.json")
                with open(wk_path, "w", encoding="utf-8") as f:
                    json.dump(compressed, f, ensure_ascii=False, indent=2)

                # 删除原始日志（已压缩）
                for date_str in dates:
                    dp = os.path.join(DAILY_DIR, f"{date_str}.json")
                    if os.path.exists(dp):
                        os.remove(dp)

                logger.info(f"[COMPRESS] Week {week_start}: {len(dates)} days → 1 summary")


def _compress_weekly_to_monthly(today):
    """将距今 30 天前的周摘要压缩为月摘要。"""
    cutoff = today - timedelta(days=30)
    to_compress = []
    for fname in os.listdir(WEEKLY_DIR):
        if not fname.endswith(".json"):
            continue
        try:
            week_start_str = fname.replace(".json", "")
            d = datetime.strptime(week_start_str, "%Y-%m-%d").date()
            if d < cutoff:
                to_compress.append((week_start_str, d))
        except ValueError:
            continue

    if not to_compress:
        return

    # 按月分组
    from collections import defaultdict
    months = defaultdict(list)
    for ws, d in to_compress:
        month_key = d.strftime("%Y-%m")
        months[month_key].append(ws)

    for month_key, weeks in months.items():
        all_text = []
        for ws in sorted(weeks):
            path = os.path.join(WEEKLY_DIR, f"{ws}.json")
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                all_text.append(data.get("summary", ""))
            except Exception:
                pass

        if all_text:
            summary = _summarize_month(all_text, month_key)
            if summary:
                compressed = {
                    "type": "monthly",
                    "month": month_key,
                    "weeks": len(weeks),
                    "summary": summary,
                    "compressed_at": datetime.now().isoformat(),
                }
                os.makedirs(MONTHLY_DIR, exist_ok=True)
                mo_path = os.path.join(MONTHLY_DIR, f"{month_key}.json")
                with open(mo_path, "w", encoding="utf-8") as f:
                    json.dump(compressed, f, ensure_ascii=False, indent=2)

                for ws in weeks:
                    wp = os.path.join(WEEKLY_DIR, f"{ws}.json")
                    if os.path.exists(wp):
                        os.remove(wp)

                logger.info(f"[COMPRESS] Month {month_key}: {len(weeks)} weeks → 1 summary")


def _summarize_week(segments, week_start, dates):
    """用 LLM 生成周摘要。"""
    try:
        from deepseek_client import call_deepseek_with_tools
        combined = "\\n".join(segments[:20])
        prompt = (
            f"将以下 Monika 一周的生活片段压缩为一段 80-150 字的摘要，"
            f"保留关键事件和情绪变化，去掉重复的日常。\n"
            f"日期范围: {min(dates)} ~ {max(dates)}\n\n{combined[:3000]}"
        )
        msgs = [{"role": "user", "content": prompt}]
        return call_deepseek_with_tools(msgs, [], temperature=0.3, max_tokens=200, task="life_gen")
    except Exception:
        return "\\n".join(segments[:3])[:200]


def _summarize_month(segments, month_key):
    """用 LLM 生成月摘要。"""
    try:
        from deepseek_client import call_deepseek_with_tools
        combined = "\\n".join(segments)
        prompt = (
            f"将以下 Monika 一个月的生活周摘要压缩为一段 100-150 字的月摘要，"
            f"只保留最重要的 2-3 个事件和总体情绪。\n\n{combined[:2000]}"
        )
        msgs = [{"role": "user", "content": prompt}]
        return call_deepseek_with_tools(msgs, [], temperature=0.3, max_tokens=200, task="life_gen")
    except Exception:
        return segments[0][:150] if segments else ""
