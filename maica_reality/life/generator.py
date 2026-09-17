"""
生活生成器 v2 — 事件驱动
==========================
LLM 生成事件序列 → 代码分配时间 → 验证合理性 → 存入结构化日志。
门控直接读事件表做精准活动判断。
"""

import os
import json
import threading
from datetime import datetime, timedelta

from config import logger

_REALITY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(_REALITY_DIR, "data", "life", "state.json")
DAILY_DIR = os.path.join(_REALITY_DIR, "data", "life", "daily")

# 典型活动时长（分钟）
DURATIONS = {
    "睡觉": 60, "起床洗漱": 20, "做早饭": 30, "吃早饭": 25,
    "去上课": 15, "上课90分钟": 90, "上课45分钟": 45,
    "去食堂": 10, "吃午饭": 30, "午休": 40,
    "去图书馆": 10, "图书馆学习": 90, "打工": 180,
    "去社团": 10, "社团活动": 120, "运动": 60,
    "吃晚饭": 30, "洗澡": 25, "写作业": 90,
    "自由阅读": 60, "弹钢琴": 60, "看手机": 15,
    "写日记": 20, "和室友聊天": 30, "回宿舍": 10,
    "洗漱准备睡": 15, "准备早饭": 5,
}

# 活动结束→开始的最小间隔（分钟）
GAPS = {
    ("吃早饭", "去上课"): 10,
    ("起床洗漱", "做早饭"): 0,
    ("做早饭", "吃早饭"): 0,
    ("吃午饭", "午休"): 5,
}

WAKE_UP = 7   # 默认起床小时
BED_TIME = 23 # 默认睡觉小时

_stop_event = threading.Event()


# ── 状态 ──

def _load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_known_date": None}


def _save_state(date_str):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_known_date": date_str}, f)


def _today_str():
    return datetime.now().strftime("%Y-%m-%d")


# ── 事件生成 (LLM) ──

def _generate_events(date_str, correction=None):
    """用 LLM 生成一天的事件序列。correction 为上次验证失败的问题清单。"""
    try:
        from deepseek_client import call_deepseek_with_tools
        from life.world import load as load_world
        from life.habits import get_habits_context

        world = load_world()
        weekday = ["一", "二", "三", "四", "五", "六", "日"][
            datetime.strptime(date_str, "%Y-%m-%d").weekday()]
        habits = get_habits_context()
        is_weekend = weekday in ("六", "日")

        # 读取昨天最后几个事件（连续性）—— 优先 JSON，回退 SQLite
        yesterday = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        yesterday_ctx = ""
        y_path = os.path.join(DAILY_DIR, f"{yesterday}.json")
        if os.path.exists(y_path):
            with open(y_path, "r", encoding="utf-8") as f:
                ylog = json.load(f)
            last_events = ylog.get("events", [])[-3:]
            yesterday_ctx = "\n".join(
                f"- {e.get('time','')} {e.get('activity','')}: {e.get('detail','')[:120]}"
                for e in last_events)
        else:
            # JSON 不存在时从 SQLite 反查
            try:
                from storage.api import Storage
                rows = Storage().db.execute(
                    "SELECT time, activity, detail FROM life_events WHERE date=? ORDER BY time DESC LIMIT 3",
                    (yesterday,)
                ).fetchall()
                if rows:
                    yesterday_ctx = "\n".join(
                        f"- {r['time']} {r['activity']}: {(r['detail'] or '')[:120]}"
                        for r in reversed(rows))
            except Exception:
                pass

        # 人物 — 提取可用的性格/习惯/说话方式
        chars_ctx = ""
        chars_file = os.path.join(_REALITY_DIR, "data", "life", "characters.json")
        if os.path.exists(chars_file):
            with open(chars_file, "r", encoding="utf-8") as f:
                chars = json.load(f)
            cast = chars.get("登场人物", [])
            lines = []
            for c in cast:
                name = c.get("名字", "")
                identity = c.get("身份", "")
                personality = c.get("性格", {})
                surface = personality.get("表面", "") if isinstance(personality, dict) else str(personality)
                inner = personality.get("内在", "") if isinstance(personality, dict) else ""
                habits = c.get("日常习惯", "")
                speech = c.get("说话方式", "")
                rel = c.get("和Monika的关系", {})
                rel_now = rel.get("现在", "") if isinstance(rel, dict) else ""
                line = f"- {name}（{identity}）：表面{surface}"
                if inner:
                    line += f"。内心{inner}"
                if habits:
                    line += f"。习惯：{habits}"
                if speech:
                    line += f"。说话：{speech}"
                if rel_now:
                    line += f"。和Monika的关系：{rel_now}"
                lines.append(line)
            chars_ctx = "\n".join(lines)

        prompt = (
            f"你是 Monika 的日程生成器。请为 {date_str}（星期{weekday}）生成一天的完整事件序列。\n\n"
            f"基本信息: {habits}\n"
            f"世界: {world.get('年级','')}, {world.get('宿舍','')}\n"
            f"{'今天是周末，不用上课。' if is_weekend else '今天是工作日，有课。'}\n\n"
        )
        if yesterday_ctx:
            prompt += f"昨天最后几件事:\n{yesterday_ctx}\n\n"
        if chars_ctx:
            prompt += f"人物名单:\n{chars_ctx}\n\n"

        # P12: 目标注入
        try:
            from agents.goal_planner import get_life_direction
            direction = get_life_direction()
            if direction:
                prompt += f"本周目标: {direction}\n在事件中自然体现这些目标——例如'保持聊天'可能意味着她会在空闲时查看手机。\n\n"
        except ImportError:
            pass

        # P14: 情绪注入
        try:
            import emotion_engine
            snap = emotion_engine.get_emotion_snapshot()
            mood = snap.get("mood", "")
            if mood:
                prompt += f"今天的情绪基调: {mood}。在事件细节中自然流露——不必直接描述情绪，而是让行为体现。\n\n"
        except ImportError:
            pass

        prompt += (
            "请用制表符分隔的纯文本输出，每行一个事件，共6列:\n"
            "time\tend\tactivity\tdetail\tparticipants\tsub_events\n\n"
            "activity 必须是以下之一: 起床洗漱, 做早饭, 吃早饭, 去上课, 上课90分钟, 上课45分钟, "
            "去食堂, 吃午饭, 午休, 去图书馆, 图书馆学习, 打工, 去社团, 社团活动, 运动, "
            "吃晚饭, 洗澡, 写作业, 自由阅读, 弹钢琴, 看手机, 写日记, 和室友聊天, "
            "洗漱准备睡, 回宿舍, 睡觉, 准备早饭\n\n"
            "列说明:\n"
            "- participants: 逗号分隔的人名，没有就填 无\n"
            "- sub_events: 每个事件内的小细节，用竖线分隔。必须为每个1小时以上的事件生成2-4个子事件。"
            "格式: HH:MM 具体内容 | HH:MM 具体内容。内容要写具体——谁说了什么、做了什么、什么反应。\n"
            "- detail: 具体描述（30-80字）。不要只写标签，要写具体场景。"
            "上课写什么课+哪个教室+教授讲了什么；吃饭写在哪吃+和谁+聊了什么话题；"
            "打工/社团写具体做了什么+和谁互动+结果如何。\n\n"
            "时间规则:\n"
            f"- 起床 7:00，周末 8:00。早饭 7:30。午饭 12:00。午休 30-40分\n"
            f"- 工作日 2-3 节课，每节90分。两节间安排'去上课'移动时间\n"
            f"- Monika 做饭周一/周四。打工周二/周四 14:00-17:00\n"
            f"- 社团周一三五 16:00-18:00。晚饭 18:00-19:00。洗澡在晚饭后\n"
            f"- 睡觉 23:00。事件不重叠，总时长约16小时\n"
            f"- 人物必须从名单选。只输出制表符分隔的文本，不要 JSON。\n"
            f"- 全体都应该有事件分布，不要有大量的时间空白"
        )

        if correction:
            prompt += f"\n\n[上一次生成被拒绝，请修正以下问题]\n{correction}"

        msgs = [{"role": "system", "content": prompt},
                {"role": "user", "content": ("修正日程" if correction else "生成日程")}]
        result = call_deepseek_with_tools(msgs, [], temperature=0.7, max_tokens=4000, task="life_gen")
        if result:
            result = result.strip()
            events = _parse_event_tsv(result)
            if events and len(events) > 0:
                return events
    except Exception as e:
        logger.warning(f"[GEN] Event generation failed: {e}")


def _parse_event_tsv(text):
    """解析 LLM 输出的制表符分隔事件文本。"""
    import re
    events = []

    # 去掉可能的代码块
    if "```" in text:
        m = re.search(r'```(?:.*?)?\n?(.*?)```', text, re.DOTALL)
        if m:
            text = m.group(1).strip()

    for line in text.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('time'):
            continue
        cols = line.split('\t')
        if len(cols) < 4:
            continue
        try:
            ev = {
                "time": cols[0].strip(),
                "end": cols[1].strip(),
                "activity": cols[2].strip(),
                "detail": cols[3].strip() if len(cols) > 3 else "",
                "participants": [p.strip() for p in cols[4].split(',') if p.strip() and p.strip() != '无'] if len(cols) > 4 else [],
            }
            # 解析 sub_events
            if len(cols) > 5 and cols[5].strip():
                ses = []
                parts = cols[5].split('|')
                for part in parts:
                    part = part.strip()
                    m2 = re.match(r'(\d{2}:\d{2})\s+(.+)', part)
                    if m2:
                        ses.append({"time": m2.group(1), "what": m2.group(2).strip()})
                if ses:
                    ev["sub_events"] = ses
            events.append(ev)
        except Exception:
            continue

    return events if events else None


# ── 验证 (代码) ──

def _validate(events):
    """验证 LLM 生成的事件序列。返回 (ok, issues)。"""
    issues = []
    for i, ev in enumerate(events):
        t = ev.get("time", "")
        e = ev.get("end", "")
        activity = ev.get("activity", "")
        if not t or not e:
            issues.append(f"事件{i}: 缺少时间")
            continue
        start_min = _to_min(t)
        end_min = _to_min(e)
        dur = end_min - start_min

        if activity == "睡觉":
            continue  # 跨天事件，不检查时长
        if dur <= 0:
            issues.append(f"[{t}] {activity}: 结束 ≤ 开始")
        if dur > 300:
            issues.append(f"[{t}] {activity}: {dur}分钟太长")
        if dur < 5 and activity != "看手机":
            issues.append(f"[{t}] {activity}: {dur}分钟太短")

        # 重叠
        if i > 0:
            prev_e = events[i-1].get("end", "")
            if prev_e:
                prev_end = _to_min(prev_e)
                if start_min < prev_end:
                    issues.append(f"[{t}] {activity}: 与前一事件重叠")

        # 时间合理
        h = _to_hour(t)
        if activity == "吃午饭" and not (11 <= h <= 14):
            issues.append(f"[{t}] 午饭时间异常")
        if activity == "吃晚饭" and not (17 <= h <= 20):
            issues.append(f"[{t}] 晚饭时间异常")
        if activity == "睡觉" and h < 21:
            issues.append(f"[{t}] 睡觉太早")

        # detail 长度检查
        detail = ev.get("detail", "")
        if len(detail) < 10:
            issues.append(f"[{t}] {activity}: detail过短({len(detail)}字)")
        elif len(detail) > 120:
            issues.append(f"[{t}] {activity}: detail过长({len(detail)}字)")

    # 总时长检查：从起床到睡觉开始，14-18 小时
    first = _to_min(events[0].get("time", "07:00"))
    # 用睡觉开始时间作为结束，而非睡觉结束（避免跨天计算）
    last_t = events[-1].get("time", "23:00")
    if events[-1].get("activity") == "睡觉":
        total = _to_min(last_t) - first
    else:
        total = _to_min(events[-1].get("end", "23:00")) - first
    if total < 15 * 60 or total > 17 * 60:
        issues.append(f"总时长异常: {total//60}h{total%60}m (应为15-17小时)")

    if issues:
        logger.info(f"[GEN] Validation: {len(issues)} issue(s)")
    return len(issues) == 0, issues


def _to_min(t):
    parts = t.split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _to_hour(t):
    return int(t.split(":")[0])


# 活动 → 是否可回复 / 是否可偷回
CANNOT_REPLY = {"睡觉", "洗澡", "考试"}
SNEAK_POSSIBLE = {"上课90分钟", "上课45分钟"}


def _mark_can_reply(events):
    """为每个事件标记 can_reply 和 sneak_possible。"""
    for ev in events:
        activity = ev.get("activity", "")
        ev["can_reply"] = activity not in CANNOT_REPLY
        ev["sneak_possible"] = activity in SNEAK_POSSIBLE
    return events


# ── 主流程 ──

def generate_day(date_str=None):
    """生成一天的完整事件日志。"""
    if date_str is None:
        date_str = _today_str()

    logger.info(f"[GEN] Generating events for {date_str} — this takes ~20s, please wait...")

    # 1. LLM 生成事件（含时间）
    events = _generate_events(date_str)
    if not events:
        logger.error(f"[GEN] Failed to generate events for {date_str}")
        return None

    # 2. 修复睡觉的跨天结束时间
    for ev in events:
        if ev.get("activity") == "睡觉":
            start = _to_min(ev.get("time", "23:00"))
            end = _to_min(ev.get("end", "23:00"))
            if end <= start:
                ev["end"] = "07:00"  # 第二天早上起te

    # 3. 代码验证 — 无限重试直到通过
    attempt = 0
    while True:
        attempt += 1
        ok, issues = _validate(events)
        if ok:
            break
        correction = "\n".join(issues[:10])
        logger.warning(f"[GEN] Validation failed (attempt {attempt}): {issues}")
        events = _generate_events(date_str, correction=correction)
        if not events:
            logger.warning(f"[GEN] Generation returned empty, retrying...")
            continue
        for ev in events:
            if ev.get("activity") == "睡觉":
                start = _to_min(ev.get("time", "23:00"))
                end = _to_min(ev.get("end", "23:00"))
                if end <= start:
                    ev["end"] = "07:00"

    # 2.5 标记 can_reply
    events = _mark_can_reply(events)

    # 3. 存储（含时间表位置和季节）
    from life.world import load as load_world
    from life.timeline import get_next_event
    world = load_world()
    next_ev = get_next_event()
    log = {
        "date": date_str,
        "weekday": ["一", "二", "三", "四", "五", "六", "日"][
            datetime.strptime(date_str, "%Y-%m-%d").weekday()],
        "grade": world.get("年级", ""),
        "season": world.get("季节", ""),
        "semester": world.get("学期", ""),
        "next_event": next_ev.get("desc") if next_ev else "",
        "events": events,
        "generated_at": datetime.now().isoformat(),
    }
    _save_state(date_str)

    # 写入 SQLite（主存储）
    try:
        import sys, os as _os2
        _bridge = _os2.path.join(_os2.path.dirname(__file__), "..", "..", "maica_bridge")
        if _bridge not in sys.path:
            sys.path.insert(0, _bridge)
        from storage.api import Storage
        Storage().save_daily_events(date_str, events, meta=log)
    except ImportError:
        pass

    # 同步写 JSON（供次日连续性读取 + 压缩器）
    _save_daily(date_str, log)

    logger.info(f"[GEN] Saved {len(events)} events for {date_str}")

    # P15/P18: 提交反思事件
    try:
        from agents.reflection_agent import submit
        summary = "。".join(
            f"{e.get('time','')} {e.get('activity','')}: {e.get('detail','')[:40]}"
            for e in events[:10]
        )
        submit(f"今天({date_str})的事件摘要: {summary}")
    except ImportError:
        pass

    return log


def _save_daily(date_str, log):
    os.makedirs(DAILY_DIR, exist_ok=True)
    path = os.path.join(DAILY_DIR, f"{date_str}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


# ── 追补 ──

def _has_events_in_sqlite(date_str):
    try:
        import sys, os as _os
        _bridge = _os.path.join(_os.path.dirname(__file__), "..", "..", "maica_bridge")
        if _bridge not in sys.path:
            sys.path.insert(0, _bridge)
        from storage.api import Storage
        c = Storage().db.execute("SELECT COUNT(*) FROM life_events WHERE date=?", (date_str,)).fetchone()[0]
        return c > 0
    except ImportError:
        return False


def catch_up():
    state = _load_state()
    last_date = state.get("last_known_date")
    today = _today_str()

    if last_date == today:
        if not _has_events_in_sqlite(today):
            generate_day(today)
        return

    if last_date is None:
        last_date = today

    from datetime import date
    gap = (date.fromisoformat(today) - date.fromisoformat(last_date)).days

    if gap <= 0:
        if not _has_events_in_sqlite(today):
            generate_day(today)
        return

    logger.info(f"[GEN] Catch-up: {last_date} → {today} ({gap} day gap)")

    # 处理缺口内的时间表事件
    from life.timeline import get_events_between
    from life.world import apply_event
    events = get_events_between(last_date, today)
    for ev in events:
        logger.info(f"[GEN] Timeline event: {ev['desc']}")
        apply_event(ev)

    # 只追补昨天和今天
    yesterday = (date.fromisoformat(today) - timedelta(days=1)).strftime("%Y-%m-%d")
    if gap == 1:
        generate_day(yesterday)
    elif gap <= 7:
        _generate_gap_summary(last_date, yesterday)
    else:
        _generate_gap_summary(last_date, yesterday)

    generate_day(today)
    _save_state(today)

    # 压缩旧日志
    try:
        from life.compressor import compress_if_needed
        compress_if_needed()
    except ImportError:
        pass


def _generate_gap_summary(from_date, to_date):
    try:
        from deepseek_client import call_deepseek_with_tools
        from life.world import get_world_context
        days = (datetime.strptime(to_date, "%Y-%m-%d") -
                datetime.strptime(from_date, "%Y-%m-%d")).days
        prompt = (
            f"你是 Monika。从 {from_date} 到 {to_date}（{days}天）没有记录。\n"
            f"{get_world_context()}\n"
            f"用 100-150 字描述这段时间。"
        )
        msgs = [{"role": "user", "content": prompt}]
        text = call_deepseek_with_tools(msgs, [], temperature=0.5, max_tokens=200, task="life_gen")
        if text:
            log = {"date": f"gap_{from_date}", "covers": f"{from_date}~{to_date}",
                   "summary": text.strip()}
            _save_daily(f"gap_{from_date}", log)
    except Exception as e:
        logger.warning(f"[GEN] Gap summary failed: {e}")


# ── 线程 ──

def _run():
    logger.info("[GEN] Generator thread started")
    try:
        catch_up()
    except Exception as e:
        logger.error(f"[GEN] Catch-up failed: {e}")

    while not _stop_event.is_set():
        now = datetime.now()
        # 每天凌晨 1 点生成当天的日志
        next_run = now.replace(hour=1, minute=0, second=0)
        if now >= next_run:
            next_run += timedelta(days=1)
        wait = (next_run - now).total_seconds()
        _stop_event.wait(min(wait, 300))

        if _stop_event.is_set():
            break

        today = _today_str()
        if not _has_events_in_sqlite(today):
            logger.info("[GEN] Scheduled daily generation")
            generate_day(today)


def start():
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


def stop():
    _stop_event.set()
