"""
Context Router — 上下文路由
============================
根据对话意图动态选择注入哪些上下文，替代 append-only 全注入。
"""

import re
import time as _time

# 上下文缓存（10秒内同一会话复用）
_cache = {"key": "", "result": "", "ts": 0}

# Token 预算（1 中文字符 ≈ 1 token，1 英文词 ≈ 0.75 token）
BUDGET = {
    "current_state":   500,   # 时间+天气+当前事件
    "past_events":     800,   # 已发生的生活事件
    "emotion":         300,   # 情绪状态
    "memory":          800,   # 记忆检索（RAG）
    "journal":         300,   # 对话经历
    "search_result":  1000,   # 搜索结果
}
TOTAL_BUDGET = 2500  # 上下文总 token 上限（不含 system prompt + 对话历史）

# 意图分类关键词
INTENT_PATTERNS = {
    "query":    r'(搜索|查|找|搜|是什么|什么时候|多少|谁的|怎么样|为什么|哪个|哪里)',
    "recall":   r'(记得|之前|上次|以前|那天|曾经|你说过|我说过|聊过|提到)',
    "emotion":  r'(想你|爱你|喜欢|讨厌|难过|开心|担心|害怕|生气|无聊|孤独|寂寞)',
    "casual":   r'(好啊|好呀|好吧|好的|早啊|嗯嗯|哦哦|哈哈|嘿嘿)',
}


def classify_intent(user_msg):
    """分类对话意图。"""
    scores = {}
    for intent, pattern in INTENT_PATTERNS.items():
        matches = re.findall(pattern, user_msg)
        scores[intent] = len(matches)
    if not any(scores.values()):
        return "casual"
    return max(scores, key=scores.get)


def _trim(text, max_chars):
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    # 在句子边界截断
    cut = text.rfind("。", 0, max_chars)
    if cut > max_chars // 2:
        return text[:cut + 1]
    return text[:max_chars] + "…"


def build(user_msg, parts):
    """
    根据对话意图动态构建上下文。
    parts: {"current_state": str, "past_events": str, "emotion": str,
            "memory": str, "journal": str, "search": str}
    """
    # 缓存检查：10 秒内同一意图复用
    intent = classify_intent(user_msg)
    now = _time.time()
    if _cache["key"] == intent and now - _cache["ts"] < 10:
        return _cache["result"]
    selected = []

    # 当前状态 → 总是注入（时间+天气+正在做的事是所有对话的基础）
    state = parts.get("current_state", "")
    if state:
        selected.append(state)

    if intent == "query":
        # 查询类：搜索 > 记忆，不需要 journal
        for key in ["memory"]:
            v = parts.get(key, "")
            if v:
                selected.append(_trim(v, BUDGET.get(key, 500)))
        for key in ["search"]:
            v = parts.get(key, "")
            if v:
                selected.append(v)

    elif intent == "recall":
        # 回忆类：记忆 + 事件 + journal
        for key in ["memory", "past_events", "journal"]:
            v = parts.get(key, "")
            if v:
                selected.append(_trim(v, BUDGET.get(key, 500)))

    elif intent == "emotion":
        # 情感类：情绪 + 记忆 + journal
        for key in ["emotion", "memory", "journal"]:
            v = parts.get(key, "")
            if v:
                selected.append(_trim(v, BUDGET.get(key, 500)))

    else:
        # 闲聊：事件 + 情绪，不需要记忆和 journal
        for key in ["past_events", "emotion"]:
            v = parts.get(key, "")
            if v:
                selected.append(_trim(v, BUDGET.get(key, 300)))

    result = "\n\n---\n\n".join(selected)

    # P20: TOTAL_BUDGET 强制执行——从低优先段开始截断
    total = len(result)
    if total > TOTAL_BUDGET:
        for priority_key in ["journal", "past_events", "memory"]:
            if total <= TOTAL_BUDGET:
                break
            for i, s in enumerate(selected):
                if priority_key in s and len(s) > 100:
                    cut = max(50, TOTAL_BUDGET - total + len(s))
                    selected[i] = _trim(s, cut)
                    total = sum(len(x) for x in selected)
        result = "\n\n---\n\n".join(selected)

    _cache["key"] = intent
    _cache["result"] = result
    _cache["ts"] = now
    return result
