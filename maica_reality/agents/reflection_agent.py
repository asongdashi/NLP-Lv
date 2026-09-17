"""
Reflection Agent — 反思代理
============================
异步 Worker，定期回顾事件和对话，更新 Self Model。
不阻塞聊天，低优先级后台运行。
"""

import os
import json
import queue
import threading
import time as time_module
from datetime import datetime, timedelta

from config import logger

_REALITY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY_DIR = os.path.join(_REALITY_DIR, "data", "life", "daily")

_event_queue = queue.Queue()
_stop = threading.Event()


def submit(event):
    """提交一个事件到反思队列。"""
    _event_queue.put(event)
    qsize = _event_queue.qsize()
    logger.info(f"[REFLECTION] Event queued (total={qsize}): {event[:80]}...")


def start():
    """启动反思 Worker 线程。"""
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    logger.info("[REFLECTION] Worker started")
    return t


def stop():
    _stop.set()


def _run():
    """主循环：首次1分钟后检查，之后每30分钟。"""
    first_run = True
    while not _stop.is_set():
        _stop.wait(60 if first_run else 30 * 60)
        first_run = False
        if _stop.is_set():
            break

        events = _drain_queue()
        if not events:
            _check_daily_reflection()
            continue

        _reflect_on_events(events)


def _drain_queue():
    events = []
    while True:
        try:
            events.append(_event_queue.get_nowait())
        except queue.Empty:
            break
    return events


def _check_daily_reflection():
    """每天做一次整体回顾。"""
    now = datetime.now()
    from agents.self_model import load, mark_reflection

    model = load()
    last = model.get("last_reflection")
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            if (now - last_dt) < timedelta(hours=20):
                return  # 不到一天，不重复反思
        except Exception:
            pass

    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    # 从 SQLite 读事件
    try:
        import sys, os as _os
        _bridge = _os.path.join(_os.path.dirname(__file__), "..", "..", "maica_bridge")
        if _bridge not in sys.path:
            sys.path.insert(0, _bridge)
        from storage.api import Storage
        events = Storage().get_daily_events(yesterday)
        if not events:
            return
        events_text = "。".join(
            f"{e.get('time','')} {e.get('activity','')}: {e.get('detail','')[:60]}"
            for e in events[:15]
        )
    except ImportError:
        return

    # 聊天记录 (JSONL 保留兼容)
    journal_text = ""
    journal_path = os.path.join(_REALITY_DIR, "..", "maica_bridge", "journals", "experience.jsonl")
    if os.path.exists(journal_path):
        entries = []
        with open(journal_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    if yesterday in e.get("time", ""):
                        entries.append(e.get("summary", "")[:150])
                except Exception:
                    pass
        if entries:
            journal_text = "。".join(entries[-5:])

    if not events_text and not journal_text:
        return

    _do_reflection(events_text, journal_text, yesterday)


def _reflect_on_events(events):
    """对队列中的事件进行反思。"""
    text = "。".join(events[-5:])
    _do_reflection(text, "", datetime.now().strftime("%Y-%m-%d"))


def _do_reflection(events_text, journal_text, date_str):
    """执行 LLM 反思调用，更新 Self Model。"""
    try:
        from deepseek_client import call_deepseek_with_tools
        from agents.self_model import (load, save, add_belief, update_relationship,
                                        update_roommate, get_all_roommates, mark_reflection)

        model = load()
        beliefs = model.get("beliefs", [])
        belief_text = "；".join(b.get("content", "") for b in beliefs[-5:]) if beliefs else "无"

        # 当前室友关系状态
        roommates = get_all_roommates()
        rm_state = "；".join(
            f"{'纱世里' if k=='sayori' else '夏树' if k=='natsuki' else '优里'}:{v:.2f}"
            for k, v in roommates.items())

        prompt = (
            f"你是 Monika。你在低频回顾近期经历。\n\n"
            f"目标不是总结剧情，而是判断:\n"
            f"- 是否形成了稳定认知\n"
            f"- 是否出现了持续趋势\n"
            f"- 关系是否有缓慢变化\n\n"
            f"今天的生活:\n{events_text[:500] if events_text else '无记录'}\n\n"
            f"今天的对话:\n{journal_text[:500] if journal_text else '无记录'}\n\n"
            f"你目前的认知:\n{belief_text}\n\n"
            f"室友亲密度（0.5=疏远 1.0=亲密）: {rm_state}\n\n"
            f"大部分时候什么都不会改变。不要戏剧化。不要生成瞬时巨大变化。\n"
            f"如果有新认知，输出 JSON: {{\"beliefs\": [\"...\"], \"relationship\": {{\"player_intimacy\": +0.1}}, "
            f"\"roommate_relationship\": {{\"sayori\": +0.02, \"natsuki\": -0.01}}}}\n"
            f"如果今天与室友的互动让你感觉更亲近或更疏远了谁，在 roommate_relationship 中给出 ±0.01~0.05 的微小调整。"
            f"没有涉及室友的事件就不要输出 roommate_relationship。\n"
            f"如果没有任何变化，只输出 NONE。\n"
            f"信念用第一人称，简短自然，如'玩家最近压力很大'。"
        )

        msgs = [{"role": "system", "content": prompt},
                {"role": "user", "content": "反思"}]
        result = call_deepseek_with_tools(msgs, [], temperature=0.3, max_tokens=200, task="agent")

        if not result or "NONE" in result.upper():
            return

        # 解析 JSON
        result = result.strip()
        if result.startswith("```"):
            result = result.split("\n", 1)[-1].rsplit("\n```", 1)[0]
        try:
            parsed = json.loads(result)
        except json.JSONDecodeError:
            logger.debug(f"[REFLECTION] JSON parse failed: {result[:100]}")
            return

        # 更新 Self Model
        if "beliefs" in parsed:
            for b in parsed["beliefs"]:
                if isinstance(b, str) and len(b) > 3:
                    add_belief(b, 0.6)
                    logger.info(f"[REFLECTION] New belief: {b}")

        if "relationship" in parsed:
            rel = parsed["relationship"]
            for key, delta in rel.items():
                if isinstance(delta, (int, float)):
                    update_relationship(key, float(delta))
                    logger.info(f"[REFLECTION] Relationship {key}: {delta:+.2f}")

        if "roommate_relationship" in parsed:
            rm = parsed["roommate_relationship"]
            for name, delta in rm.items():
                if name in ("sayori", "natsuki", "yuri") and isinstance(delta, (int, float)):
                    d = float(delta)
                    if 0.01 <= abs(d) <= 0.05:
                        update_roommate(name, d)
                        logger.info(f"[REFLECTION] Roommate {name}: {d:+.2f}")

        # 存档原始反思
        try:
            from storage.api import Storage
            Storage().save_reflection(date_str, events_text[:500], journal_text[:500], result)
        except Exception:
            pass

        mark_reflection()
        logger.info("[REFLECTION] Completed")

    except Exception as e:
        logger.debug(f"[REFLECTION] Failed: {e}")


def _summarize_events(log):
    events = log.get("events", [])
    return "。".join(
        f"{e.get('time','')} {e.get('activity','')}: {e.get('detail','')[:60]}"
        for e in events[:15]
    )


def flush():
    """立即消费反思队列——用于玩家断连或中途退出时调用。
    不影响后台线程，只是提前执行排队的反思。"""
    events = _drain_queue()
    if events:
        logger.info(f"[REFLECTION] Flush: processing {len(events)} event(s) immediately")
        _reflect_on_events(events)
    else:
        logger.debug("[REFLECTION] Flush: queue empty")
