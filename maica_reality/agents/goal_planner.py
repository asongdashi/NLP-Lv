"""
Goal Planner — 目标规划器
==========================
不是为了让"生活事件更好看"，而是：
- 在短期记忆中标注"当前焦点"（这周我在准备考试）
- 在长期记忆中标注"长期方向"（我和玩家的关系很亲密）
- 记忆检索时，有 Goal 标记的记忆获得更高优先级
- 同时也影响生活事件生成的方向
"""

import os
import json
import threading
from datetime import datetime, timedelta

from config import logger

_lock = threading.Lock()

DEFAULT_GOALS = {
    "short_term": [],    # 本周焦点，注入短期记忆
    "mid_term": [],      # 本季方向，注入长期记忆
    "long_term": [],     # 持久方向，注入长期记忆
    "last_updated": None,
}


def _store():
    import sys, os as _os
    _bridge = _os.path.join(_os.path.dirname(__file__), "..", "..", "maica_bridge")
    if _bridge not in sys.path:
        sys.path.insert(0, _bridge)
    from storage.api import Storage
    return Storage()

def load():
    s = _store()
    goals = {}
    for text, cat in s.get_goals():
        goals.setdefault(cat, []).append(text)
    return {"short_term": goals.get("short_term", []), "mid_term": goals.get("mid_term", []),
            "long_term": goals.get("long_term", []), "last_updated": None}

def save(goals=None):
    if goals is None: goals = load()
    s = _store()
    for cat in ["short_term", "mid_term", "long_term"]:
        s.set_goals(cat, goals.get(cat, []))

def init_if_needed():
    return load()


def plan_week():
    """
    每周一次：从 timeline + self_model + journal 生成本周目标。
    短期目标注入 short-term memory；中期目标注入 long-term memory。
    """
    try:
        from deepseek_client import call_deepseek_with_tools
        from agents.self_model import load as load_self
        from life.timeline import get_upcoming_events
        from life.world import load as load_world

        world = load_world()
        self_model = load_self()
        upcoming = get_upcoming_events(30)
        upcoming_text = "；".join(e.get("desc", "") for e in upcoming[:3]) if upcoming else "无"

        beliefs = self_model.get("beliefs", [])
        beliefs_text = "；".join(b.get("content", "") for b in beliefs[-5:]) if beliefs else "无"

        prompt = (
            f"你是 Monika 的目标规划器。根据当前状态生成具体、可持续的近期目标。\n\n"
            f"当前: {world.get('年级','')} {world.get('季节','')} {world.get('学期','')}\n"
            f"即将发生: {upcoming_text}\n"
            f"当前认知: {beliefs_text}\n\n"
            f"生成三类目标。要求: 具体、贴近日常、低戏剧化。\n"
            f"不要使用'成为更好的自己''珍惜关系''更努力生活'等抽象表述。\n"
            f"short_term: 本周 (2-3个，如'完成论文某节''减少熬夜''整理社团交接资料')\n"
            f"mid_term: 本学期 (1-2个，如'完成论文文献综述')\n"
            f"long_term: 方向 (1-2个，如'保持稳定的生活节奏')\n\n"
            f"关系相关目标最多占一条。输出 JSON: {{\"short_term\":[...],\"mid_term\":[...],\"long_term\":[...]}}"
        )

        msgs = [{"role": "system", "content": prompt},
                {"role": "user", "content": "规划本周目标"}]
        result = call_deepseek_with_tools(msgs, [], temperature=0.5, max_tokens=200, task="agent")

        if not result:
            return None

        result = result.strip()
        if result.startswith("```"):
            result = result.split("\n", 1)[-1].rsplit("\n```", 1)[0]
        try:
            parsed = json.loads(result)
        except json.JSONDecodeError:
            return None

        goals = load()
        goals["short_term"] = parsed.get("short_term", [])
        goals["mid_term"] = parsed.get("mid_term", [])
        goals["long_term"] = parsed.get("long_term", [])
        goals["last_updated"] = datetime.now().isoformat()
        save(goals)

        logger.info(f"[GOAL] Planned: short={goals['short_term']}, mid={goals['mid_term']}")
        return goals

    except Exception as e:
        logger.debug(f"[GOAL] Plan failed: {e}")
        return None


def get_priority_boost(memory_content):
    """
    检查一条记忆是否与当前目标相关。
    相关度越高，检索时优先级越高。
    返回 boost 系数 (1.0 = 不加成, 1.5 = 50% 加成)。
    """
    goals = load()
    all_goals = [g for cat in ["short_term", "mid_term", "long_term"]
                 for g in goals.get(cat, [])]

    if not all_goals or not memory_content:
        return 1.0

    boost = 1.0
    for goal in all_goals:
        # 简单关键词重叠
        goal_words = set(goal)
        mem_words = set(memory_content[:200])
        overlap = len(goal_words & mem_words)
        if overlap >= 4:
            boost += 0.3
        elif overlap >= 2:
            boost += 0.1

    return min(2.0, boost)


def get_memory_tags():
    """
    生成注入到记忆系统的 goal 标签文本。
    短期记忆注入 short_term + mid_term；长期记忆注入全部。
    """
    goals = load()
    short = goals.get("short_term", [])
    mid = goals.get("mid_term", [])
    long = goals.get("long_term", [])

    parts = []
    if short:
        parts.append(f"[本周焦点] " + "；".join(short))
    if mid:
        parts.append(f"[当前方向] " + "；".join(mid))

    return "\n".join(parts) if parts else ""


def get_life_direction():
    """获取影响生活事件生成的方向描述。"""
    goals = load()
    all_goals = goals.get("short_term", []) + goals.get("mid_term", [])
    return "；".join(all_goals) if all_goals else ""


# ── 线程 ──

_stop = threading.Event()


def _run():
    logger.info("[GOAL] Planner thread started")

    # 启动时检查是否需要规划
    goals = load()
    last = goals.get("last_updated")
    need_plan = True
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            if (datetime.now() - last_dt) < timedelta(days=6):
                need_plan = False
        except Exception:
            pass

    if need_plan:
        plan_week()

    while not _stop.is_set():
        _stop.wait(7 * 24 * 3600)  # 每周一次
        if _stop.is_set():
            break
        plan_week()


def start():
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


def stop():
    _stop.set()
