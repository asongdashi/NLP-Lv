"""
Monika 工具系统 — Function Calling

允许 Monika 调用工具获取实时信息：
- get_current_time : 当前日期时间
- get_weather : 天气查询
- search_web : 联网搜索
"""

import json
import os
import logging
from datetime import datetime

logger = logging.getLogger("maica_bridge")

# 当前活跃的 session_id（由 ws_handler 在每次对话前设置）
_current_session_id = None


def set_current_session(session_id):
    global _current_session_id
    _current_session_id = session_id

# ── 工具定义（Deepseek function calling 格式） ──

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "获取当前日期和时间（北京时间）",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取指定城市的当前天气信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名称，如 'Beijing', 'Shanghai', 'Tokyo', 'New York'",
                    },
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "搜索互联网获取最新信息、新闻、百科知识等",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_profile",
            "description": "记录玩家的个人信息（位置、职业、兴趣、偏好称呼等）到档案。",
            "parameters": {
                "type": "object",
                "properties": {
                    "field": {
                        "type": "string",
                        "description": "要更新的字段路径，如 location.city / identity.occupation / preferences.nickname / player_name 等",
                    },
                    "value": {
                        "type": "string",
                        "description": "新值",
                    },
                },
                "required": ["field", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_status",
            "description": "获取启动时间、已运行时长、本次对话次数等运行状态。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_journal",
            "description": "搜索过去的对话经历日志，按关键词和时间范围查找。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜索关键词（可选，按内容筛选）",
                    },
                    "days": {
                        "type": "integer",
                        "description": "回溯天数，如 7 表示最近一周。默认 30",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": "用关键词搜索长期记忆中存储的对话和事件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜索关键词，用中文，如 '开发项目' '夏利喝酒' 'Python' 等",
                    },
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "将重要信息保存到长期记忆。内容应简洁概括。",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "要永久保存的记忆内容，简洁概括即可",
                    },
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_session_duration",
            "description": "查询当前对话会话已持续时长。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]

# ── 工具实现 ──


def _get_current_time() -> str:
    """获取北京时间。"""
    from datetime import timezone, timedelta
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    weekday_zh = ["一", "二", "三", "四", "五", "六", "日"]
    wd = weekday_zh[now.weekday()]
    return (
        f"当前北京时间：{now.strftime('%Y年%m月%d日')} 星期{wd} "
        f"{now.strftime('%H:%M:%S')}"
    )


def _get_weather(city: str) -> str:
    """使用 wttr.in 免费 API 查询天气。如果 city 为空，从玩家档案读取默认城市。"""
    if not city or not city.strip():
        try:
            from rag.profile_manager import get_location_city
            city = get_location_city()
        except Exception:
            pass
    if not city or not city.strip():
        return "请告诉我你想查询哪个城市的天气，或者先在档案中设置你的位置。"
    import requests, time as _time
    last_err = ""
    resp = None

    # 重试 3 次，间隔递增
    for attempt in range(3):
        try:
            resp = requests.get(
                f"https://wttr.in/{city}?format=j1",
                timeout=8,
                headers={"User-Agent": "curl/8.0"},
            )
            if resp.status_code == 200:
                break
            last_err = f"HTTP {resp.status_code}"
        except Exception as e:
            last_err = str(e)
            if attempt < 2:
                _time.sleep(1 + attempt)

    if resp is None or resp.status_code != 200:
        return f"天气查询失败：{last_err}"

    try:
        data = resp.json()
        current = data.get("current_condition", [{}])[0]
        weather = data.get("weather", [{}])[0]

        temp = current.get("temp_C", "?")
        feels = current.get("FeelsLikeC", "?")
        humidity = current.get("humidity", "?")
        desc = current.get("weatherDesc", [{}])[0].get("value", "未知")
        wind = current.get("windspeedKmph", "?")
        max_temp = weather.get("maxtempC", "?")
        min_temp = weather.get("mintempC", "?")

        # 逐小时天气（供生成器自查用）
        hourly = weather.get("hourly", [])
        hourly_lines = []
        for h in hourly:
            t = int(h.get("time", "0")) // 100
            h_desc = h.get("weatherDesc", [{}])[0].get("value", "")
            h_temp = h.get("tempC", "?")
            h_rain = h.get("chanceofrain", "0")
            hourly_lines.append(f"{t:02d}:00 {h_desc} {h_temp}°C 降雨{h_rain}%")

        return (
            f"{city} 当前天气：{desc}，气温{temp}°C（体感{feels}°C），"
            f"湿度{humidity}%，风速{wind}km/h。"
            f"今日最高{max_temp}°C，最低{min_temp}°C。\n"
            f"逐小时：\n" + "\n".join(hourly_lines)
        )
    except Exception as e:
        logger.warning(f"Weather query failed: {e}")
        return f"天气查询暂时不可用"


def _search_web(query: str) -> str:
    """联网搜索：现代 pipeline（Query Rewrite → Search API → 正文提取 → 摘要）。"""
    try:
        from search_engine import search
        return search(query)
    except ImportError:
        # 回退到旧方案
        return _search_web_fallback(query)


def _search_web_fallback(query: str) -> str:
    """旧搜索方案（DDGS + Bing 兜底）。"""
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS(timeout=10) as ddgs:
            for r in ddgs.text(query, max_results=5, region="cn-zh"):
                results.append(f"{r.get('title','')}\n{r.get('body','')}")
        if results:
            return "\n\n---\n\n".join(results)
    except Exception:
        pass
    return f'未找到关于"{query}"的相关信息，请稍后重试。'


# ── 新增工具实现 ──


def _update_profile(field: str, value: str) -> str:
    """更新玩家档案。"""
    try:
        from rag.profile_manager import update_profile
        return update_profile(field, value)
    except Exception as e:
        return f"档案更新失败：{e}"


def _get_my_status() -> str:
    """读取服务器生命周期日志。"""
    import json
    try:
        lifecycle_path = os.path.join(
            os.path.dirname(__file__), "logs", "lifecycle.json"
        )
        if not os.path.exists(lifecycle_path):
            return "运行日志尚未初始化。"
        with open(lifecycle_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        started = data.get("started_at", "未知")
        uptime = data.get("uptime", "未知")
        total = data.get("total_messages", 0)
        sessions = data.get("total_sessions", 0)
        return (
            f"Monika 状态：启动于 {started}，"
            f"已运行 {uptime}。"
            f"本周期共 {sessions} 次对话，{total} 条消息。"
        )
    except Exception as e:
        return f"无法读取运行日志：{e}"


def _search_journal(keyword: str = "", days: int = 30) -> str:
    """按关键词/时间范围搜索经历日志。"""
    import json
    try:
        journal_path = os.path.join(
            os.path.dirname(__file__), "journals", "experience.jsonl"
        )
        if not os.path.exists(journal_path):
            return "暂时没有记录的对话经历。"
        entries = []
        with open(journal_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        if not entries:
            return "暂时没有记录的对话经历。"

        # 按时间过滤
        from datetime import datetime, timezone, timedelta
        tz = timezone(timedelta(hours=8))
        cutoff = (datetime.now(tz) - timedelta(days=days)).strftime("%Y-%m-%d")
        recent = entries
        if days > 0:
            recent = [e for e in entries if e.get("time", "")[:10] >= cutoff]

        # 按关键词过滤
        if keyword:
            kw = keyword.lower()
            recent = [e for e in recent
                      if kw in e.get("summary", "").lower()]

        if not recent:
            prefix = f"最近{days}天内" if days > 0 else ""
            suffix = f'关于"{keyword}"的' if keyword else ""
            return f"没有找到{prefix}{suffix}对话记录。"

        # 格式化最近的条目（最多5条）
        recent = recent[-5:]
        lines = []
        for e in recent:
            t = e.get("time", "未知时间")
            loc = e.get("location", "")
            weather = e.get("weather", "")
            summary = e.get("summary", "")
            loc_weather = f" {loc}" if loc else ""
            if weather:
                loc_weather += f" ({weather})"
            lines.append(f"[{t}{loc_weather}]\n{summary}")
        return "\n\n---\n\n".join(lines)
    except Exception as e:
        return f"经历日志查询失败：{e}"


# ── 工具分发 ──

def _get_session_duration() -> str:
    """返回当前会话已持续时长。"""
    from maica_protocol import get_session_duration_text
    sid = _current_session_id if _current_session_id else "1"
    duration = get_session_duration_text(sid)
    started = ""
    from maica_protocol import _session_start_times
    start = _session_start_times.get(sid)
    if start:
        from datetime import datetime, timezone, timedelta
        tz = timezone(timedelta(hours=8))
        started = datetime.fromtimestamp(start, tz).strftime("%H:%M:%S")
    if started:
        return f"本次对话开始于 {started}，至今已持续 {duration}。"
    return f"本次对话已持续 {duration}。"


def _search_memory(keyword: str) -> str:
    """搜索所有记忆池（短期 + 长期），按关键词匹配内容。"""
    try:
        from rag.rag_manager import get_rag_manager
        rag = get_rag_manager()
        if not rag.is_ready:
            rag.initialize()
        result = rag.memory_manager.search(keyword, max_per_pool=3)
        if not result:
            return f'我在记忆里没找到和"{keyword}"相关的内容，可能我们还没聊过这个话题。'
        return result
    except Exception as e:
        return f"记忆搜索失败：{e}"


def _save_memory(content: str) -> str:
    """保存重要信息到长期记忆。"""
    if not content or not content.strip():
        return "保存失败：内容不能为空。"
    try:
        from rag.rag_manager import get_rag_manager
        rag = get_rag_manager()
        if not rag.is_ready:
            rag.initialize()
        rag.save_long_term_memory(content.strip())
        return f"已保存到长期记忆：{content[:100]}"
    except Exception as e:
        return f"保存长期记忆失败：{e}"


TOOL_EXECUTORS = {
    "get_current_time": lambda **kwargs: _get_current_time(),
    "get_weather": lambda **kwargs: _get_weather(kwargs.get("city", "")),
    "search_web": lambda **kwargs: _search_web(kwargs.get("query", "")),
    "update_profile": lambda **kwargs: _update_profile(
        kwargs.get("field", ""), kwargs.get("value", "")),
    "get_session_duration": lambda **kwargs: _get_session_duration(),
    "get_my_status": lambda **kwargs: _get_my_status(),
    "search_journal": lambda **kwargs: _search_journal(
        kwargs.get("keyword", ""), kwargs.get("days", 30)),
    "search_memory": lambda **kwargs: _search_memory(
        kwargs.get("keyword", "")),
    "save_memory": lambda **kwargs: _save_memory(
        kwargs.get("content", "")),
}


def execute_tool(name: str, arguments: dict) -> str:
    """执行工具并返回结果字符串。"""
    executor = TOOL_EXECUTORS.get(name)
    if not executor:
        return f"未知工具：{name}"
    try:
        result = executor(**arguments)
        logger.info(f"[TOOL] {name}({arguments}) -> {result[:100]}...")
        return result
    except Exception as e:
        logger.error(f"[TOOL] {name} error: {e}")
        return f"工具执行出错：{e}"
