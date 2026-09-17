"""
Salience System — 记忆显著性评分
=================================
四因子加权: 情感强度×0.4 + 关系变化×0.3 + 新颖度×0.2 + 用户关注×0.1
同时应用于长期记忆储存和短期记忆检索
"""

import re
from datetime import datetime

EMOTION_STRONG = [
    "开心", "难过", "生气", "害怕", "感动", "激动", "震惊", "绝望", "幸福",
    "崩溃", "兴奋", "心疼", "爱", "恨", "想你", "担心"
]
EMOTION_MODERATE = [
    "不错", "还好", "还行", "有点", "期待", "希望", "想要", "喜欢"
]
RELATIONSHIP_MARKERS = [
    "我们", "关系", "一直", "永远", "陪伴", "记得", "想你", "相遇",
    "认识", "第一次", "那天", "以前", "当初", "约定", "承诺"
]


def compute(user_msg, assistant_reply=None, created_at=None):
    """
    计算一条对话的显著性分数 (0.0-1.0)。
    同时适用于长期记忆保存和短期记忆检索。
    created_at: 可选 epoch 时间戳，用于时间衰减。
    """
    text = user_msg
    if assistant_reply:
        text += " " + assistant_reply

    # 1. 情感强度 (0.4)
    emotion_score = 0.0
    for w in EMOTION_STRONG:
        emotion_score += text.count(w) * 0.25
    for w in EMOTION_MODERATE:
        emotion_score += text.count(w) * 0.1
    emotion_score = min(1.0, emotion_score * 0.4)

    # 2. 关系变化 (0.3)
    relationship_score = 0.0
    for w in RELATIONSHIP_MARKERS:
        relationship_score += text.count(w) * 0.15
    relationship_score = min(1.0, relationship_score * 0.3)

    # 3. 新颖度 (0.2) — 基于话题关键词的罕见程度
    novelty_score = _compute_novelty(user_msg)
    novelty_score *= 0.2

    # 4. 用户关注 (0.1) — 消息长度和对话轮次
    focus_score = min(1.0, len(text) / 200) * 0.1

    score = emotion_score + relationship_score + novelty_score + focus_score

    # P21: 时间衰减 — 旧的记忆自然消退
    if created_at:
        import time as _t
        age_days = (_t.time() - created_at) / 86400.0
        decay = max(0.3, 1.0 - age_days / 90)
        score *= decay

    return round(score, 3)


_topic_cache = {}


def _compute_novelty(text):
    """基于话题新词率估算新颖度。"""
    words = re.findall(r'[\u4e00-\u9fff]{2,4}', text)
    if not words:
        return 0.3
    novel = 0
    for w in words:
        count = _topic_cache.get(w, 0)
        if count == 0:
            novel += 1
        _topic_cache[w] = count + 1
    # 缓存清理：超过 1000 个词时清理一半
    if len(_topic_cache) > 1000:
        keys = sorted(_topic_cache, key=_topic_cache.get)
        for k in keys[:500]:
            del _topic_cache[k]
    return min(1.0, novel / len(words))


def apply_to_memories(memories, query=None):
    """
    在检索结果中按显著性加权。
    返回 (weighted_memories, total_score)。
    用于短期记忆 RAG 检索和长期记忆搜索。
    """
    if not memories:
        return memories, 0.0

    total = 0.0
    for mem in memories:
        # 从内容中估算 salience
        content = mem if isinstance(mem, str) else mem.get("content", "")
        sal = compute(content) if content else 0.3
        mem["_salience"] = sal
        total += sal

    # 按 salience 降序排列
    if isinstance(memories, list) and len(memories) > 1:
        memories = sorted(memories, key=lambda m: m.get("_salience", 0) if isinstance(m, dict) else 0.3, reverse=True)

    return memories, total


def mark_for_storage(user_msg, assistant_reply=None):
    """
    存储前标记显著性，供长期记忆和短期记忆使用。
    返回 (salience_score, is_worth_keeping)。
    """
    score = compute(user_msg, assistant_reply)
    # 非必要不记忆：只有显著情感/关系变化才值得保存
    worth = score >= 0.25
    return score, worth
