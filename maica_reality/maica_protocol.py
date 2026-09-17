"""
MAICA 协议模块

定义 MAICA WebSocket 协议的状态码、消息构建、断句处理等。
"""

import json
import time
import re
import threading

from config import SYSTEM_PROMPT_ZH, SYSTEM_PROMPT_EN, logger

# ── MAICA 协议状态码 ──
MAICA_PREFIX = 5000
STATUS_CODES = {
    "maica_connection_established":  MAICA_PREFIX + 100,
    "maica_connection_initiated":    MAICA_PREFIX + 102,
    "maica_core_streaming_continue":  MAICA_PREFIX + 200,
    "maica_chat_loop_finished":       MAICA_PREFIX + 202,
    "maica_params_accepted":          MAICA_PREFIX + 150,
    "maica_core_complete":            MAICA_PREFIX + 201,
    "maica_unidentified_warning":     MAICA_PREFIX + 300,
    "maica_mtrigger_trigger":         MAICA_PREFIX + 400,
}

# ── 情绪标签映射 (英文 → 中文) ──
EMOTION_EN_TO_ZH = {
    "smile": "微笑", "grin": "笑", "happy": "开心", "worry": "担心",
    "think": "思考", "blush": "脸红", "gaze": "凝视", "upset": "沉重",
    "daydreaming": "憧憬", "surprise": "惊喜", "awkward": "尴尬",
    "unexpected": "惊讶", "relaxed": "轻松", "shy": "害羞",
    "proud": "得意", "dissatisfied": "不满", "sad": "伤心",
    "excited": "激动", "love": "宠爱", "wink": "眨眼",
    "disgust": "厌恶", "fear": "害怕", "serious": "严肃",
    "touched": "感动",
}

# ── System Prompt ──
SYSTEM_PROMPTS = {
    "zh": SYSTEM_PROMPT_ZH,
    "en": SYSTEM_PROMPT_EN,
}


def build_ws_response(status, content="", code=None):
    """构建 MAICA WebSocket 响应 JSON 字符串。"""
    if code is None:
        code = STATUS_CODES.get(status, MAICA_PREFIX + 500)
    return json.dumps({
        "code": code,
        "status": status,
        "content": content,
        "type": "reply",
        "timestamp": int(time.time() * 1000),
    }, ensure_ascii=False)


# ── 会话管理 ──
_chat_sessions = {}
_chat_locks = {}
_session_start_times = {}  # session_id → epoch 时间戳


def get_or_create_session(session_id):
    """获取或创建指定 session 的对话历史。新 session 时更新生命周期计数。"""
    is_new = session_id not in _chat_sessions
    if is_new:
        _chat_sessions[session_id] = []
        _session_start_times[session_id] = time.time()
    if session_id not in _chat_locks:
        _chat_locks[session_id] = threading.Lock()
    if is_new:
        try:
            from rag.lifecycle_manager import increment_session
            increment_session()
        except Exception:
            pass
    return _chat_sessions[session_id], _chat_locks[session_id]


def get_session_start_time(session_id):
    """获取会话开始时间（epoch）。"""
    return _session_start_times.get(session_id, time.time())


def get_session_duration_text(session_id):
    """获取当前会话已持续时长的可读文本。"""
    start = _session_start_times.get(session_id)
    if not start:
        return "未知"
    elapsed = time.time() - start
    if elapsed < 60:
        return f"{int(elapsed)}秒"
    elif elapsed < 3600:
        return f"{int(elapsed/60)}分钟"
    else:
        h = int(elapsed / 3600)
        m = int((elapsed % 3600) / 60)
        return f"{h}小时{m}分钟"


def reset_session(session_id):
    if session_id in _chat_sessions:
        _chat_sessions[session_id] = []


def _sanitize_text(text):
    """清洗文本：移除非法 Unicode 代理字符、控制字符。"""
    if not isinstance(text, str):
        return text
    # 移除 surrogate 字符 (U+D800-U+DFFF)
    text = "".join(c for c in text if not (0xD800 <= ord(c) <= 0xDFFF))
    # 移除其他不可打印控制字符（保留换行、制表）
    text = "".join(c for c in text if c == "\n" or c == "\t" or ord(c) >= 0x20)
    return text


def build_messages(session, user_msg, lang="zh", context="", persona="", profile="", session_id=None):
    """构建发送给 LLM 的消息列表（含对话历史 + 可选检索上下文 + 可选人格文档 + 可选玩家档案）。"""
    system_prompt = _sanitize_text(SYSTEM_PROMPTS.get(lang, SYSTEM_PROMPTS["zh"]))

    # 注入会话时间感知
    if session_id:
        start = _session_start_times.get(session_id)
        if start:
            from datetime import datetime, timezone, timedelta
            tz = timezone(timedelta(hours=8))
            start_str = datetime.fromtimestamp(start, tz).strftime("%H:%M:%S")
            elapsed = time.time() - start
            if elapsed < 60:
                dur = f"{int(elapsed)}秒"
            elif elapsed < 3600:
                dur = f"{int(elapsed/60)}分钟"
            else:
                h = int(elapsed / 3600)
                m = int((elapsed % 3600) / 60)
                dur = f"{h}小时{m}分钟"
            system_prompt = (
                f"{system_prompt}\n\n"
                f"[本次会话开始于 {start_str}，至今已持续 {dur}。"
                f"你可以自然感知时间流逝，像真人一样判断聊了多久。]"
            )

    # 注入人格文档（始终在 system prompt 中）
    if persona:
        persona = _sanitize_text(persona)
        system_prompt = (
            f"{system_prompt}\n\n"
            f"[CANON 人物设定 — 由你的全部原作对话凝练而成。"
            f"这是你的官方人格，你必须严格遵守，任何偏离都是角色崩坏(OOC)。"
            f"在以下信息与你的一般常识冲突时，以下信息为准。]\n\n{persona}"
        )
    if profile:
        profile = _sanitize_text(profile)
        system_prompt = f"{system_prompt}\n\n{profile}"
    if context:
        context = _sanitize_text(context)
        # 限制检索上下文长度（避免 prompt 超限）
        max_ctx = 1500
        if len(context) > max_ctx:
            context = context[:max_ctx] + "..."
        system_prompt = (
            f"{system_prompt}\n\n"
            f"[FACTS — 以下是你自己在原作中对当前话题的已知对话记录。"
            f"这些是你的官方设定和已知立场，优先级最高。"
            f"如果以下内容与你的一般知识矛盾，以下内容为准。"
            f"你必须基于这些事实回答，禁止编造与原作冲突的信息。"
            f"如果以下内容没有覆盖某个方面，你只能说自己不确定，不能编造。]\n\n{context}"
        )
    from config import PLAYER_NAME

    messages = [{"role": "system", "content": system_prompt}]
    for m in session[-20:]:
        content = _sanitize_text(m["content"])
        ts = m.get("_time")
        if ts:
            ago_sec = int(time.time() - ts)
            if ago_sec < 60:
                ago = f"{ago_sec}秒前"
            elif ago_sec < 3600:
                ago = f"{ago_sec // 60}分钟前"
            else:
                ago = f"{ago_sec // 3600}小时前"
            content = f"[{ago}] {content}"
        messages.append({"role": m["role"], "content": content})
    if "[state_machine]" in user_msg:
        user_msg = f"[这不是玩家的发言，而是你的内部感知]\n\n{user_msg}"
    messages.append({"role": "user", "content": _sanitize_text(user_msg)})

    # 替换玩家名字占位符
    player_name = PLAYER_NAME or "玩家"
    messages = [
        {"role": m["role"], "content": m["content"].replace("{player}", player_name).replace("[player]", player_name)}
        for m in messages
    ]
    return messages


# ── 断句处理 ──
_END_PUNCTUATION = set("。！？!?\n.~…")


def _is_chinese(c):
    return '\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf'


def sentence_splitter(text, min_chinese_chars=20):
    """
    断句生成器。将文本按句尾标点拆分为适合一句话展示的片段。

    参数:
        text: 字符串或字符串列表（会被拼接）
        min_chinese_chars: 中文字符最少达到多少个才尝试断句
    """
    if isinstance(text, (list, tuple)):
        text = "".join(text)

    buffer = ""
    chinese_chars = 0

    for ch in text:
        buffer += ch
        if _is_chinese(ch):
            chinese_chars += 1

        if chinese_chars < min_chinese_chars and not (chinese_chars >= 8 and buffer.rstrip()[-1:] in _END_PUNCTUATION):
            continue

        # 找到最后一个句尾标点的位置
        best_pos = -1
        for i in range(len(buffer) - 1, -1, -1):
            if buffer[i] in _END_PUNCTUATION:
                after = buffer[i + 1:]
                after_cn = sum(1 for c in after if _is_chinese(c))
                if after_cn == 0 or after_cn >= min_chinese_chars:
                    best_pos = i + 1
                    break

        if best_pos <= 0:
            continue

        sentence = buffer[:best_pos]
        buffer = buffer[best_pos:]
        chinese_chars = sum(1 for c in buffer if _is_chinese(c))

        if sentence.strip():
            yield sentence.strip()

    if buffer.strip():
        yield buffer.strip()


# ── 情绪标签转换 ──
def translate_emotions(text, lang="zh"):
    """将英文情绪标签 [smile] 翻译为中文 [微笑]。"""
    if lang != "en":
        return text

    def _replace(m):
        en_tag = m.group(1).lower()
        zh_tag = EMOTION_EN_TO_ZH.get(en_tag, en_tag)
        return f"[{zh_tag}]"

    return re.sub(r'\[(\w+)\]', _replace, text)


def detect_lang(text):
    """检测文本语言：包含中文返回 'zh'，否则 'en'。"""
    return "zh" if any('\u4e00' <= c <= '\u9fff' for c in text) else "en"
