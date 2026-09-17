"""
Deepseek API 客户端

支持多 Key —— 不同任务类型使用独立 API Key，避免上下文干扰。
"""

import json
import requests

from config import DEEPSEEK_MODEL, DEEPSEEK_BASE, get_api_key, get_api_model, logger
from config import ENABLE_THINKING, REASONING_EFFORT

MAX_TOOL_ROUNDS = 3  # 最多连续调用 3 轮工具


def _headers(task="chat"):
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_api_key(task)}",
    }


def call_deepseek_chat_stream(messages, temperature=0.7, max_tokens=2048, task="chat"):
    """流式调用 Deepseek Chat API，yield 每个 token 文本块。"""
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "stream": True,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if ENABLE_THINKING:
        payload["reasoning_effort"] = REASONING_EFFORT
        payload["thinking"] = {"type": "enabled"}

    response = requests.post(
        f"{DEEPSEEK_BASE}/chat/completions",
        headers=_headers(task),
        json=payload,
        stream=True,
        timeout=120,
    )

    if response.status_code != 200:
        raise Exception(f"Deepseek API error: {response.status_code} {response.text}")

    for line in response.iter_lines():
        if not line:
            continue
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        if not line.startswith("data: "):
            continue
        data_str = line[6:]
        if data_str == "[DONE]":
            break
        try:
            data = json.loads(data_str)
            delta = data.get("choices", [{}])[0].get("delta", {})
            content = delta.get("content", "")
            if content:
                yield content
        except json.JSONDecodeError:
            continue


def call_deepseek_with_tools(messages, tools, temperature=0.7, max_tokens=2048, task="chat"):
    """
    支持 Function Calling 的 API 调用（带工具循环）。
    task: 任务类型 (chat/greeting/farewell/life_gen/topic_gen/memory/search)
    """
    from tools import execute_tool

    working_messages = list(messages)
    round_count = 0

    # 无 tools 的调用（摘要、自动记忆等）不需要 thinking
    _enable_thinking = ENABLE_THINKING and bool(tools)

    while round_count < MAX_TOOL_ROUNDS:
        round_count += 1

        payload = {
            "model": get_api_model(task),
            "messages": working_messages,
            "tools": tools,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if _enable_thinking:
            payload["reasoning_effort"] = REASONING_EFFORT
            payload["thinking"] = {"type": "enabled"}

        resp = requests.post(
            f"{DEEPSEEK_BASE}/chat/completions",
            headers=_headers(task),
            json=payload,
            timeout=600,
        )

        if resp.status_code != 200:
            logger.warning(f"[TOOLS] API error: {resp.status_code}")
            # 回退到无工具调用
            payload.pop("tools", None)
            payload.pop("reasoning_effort", None)
            payload.pop("thinking", None)
            payload["stream"] = True
            fallback = requests.post(
                f"{DEEPSEEK_BASE}/chat/completions",
                headers=_headers(task),
                json=payload,
                stream=True,
                timeout=600,
            )
            if fallback.status_code != 200:
                raise Exception(f"Deepseek API error: {fallback.status_code}")
            full = ""
            for line in fallback.iter_lines():
                if not line:
                    continue
                if isinstance(line, bytes):
                    line = line.decode("utf-8")
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    delta = data.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        full += content
                except json.JSONDecodeError:
                    continue
            return full or "抱歉，我现在无法回答，请稍后再试。"

        data = resp.json()
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})

        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls", [])

        # 有工具调用 → 即使同时有文本内容也要先执行工具，然后继续循环
        # （deepseek 经常在文字中说"我查查..."同时也发起了工具调用，
        #   如果只取 content 返回会打断对话，玩家不得不发无意义句子触发下一步）
        if tool_calls:
            working_messages.append({
                "role": "assistant",
                "content": content or None,
                "tool_calls": tool_calls,
            })

            for tc in tool_calls:
                fn = tc.get("function", {})
                fn_name = fn.get("name", "")
                try:
                    fn_args = json.loads(fn.get("arguments", "{}"))
                except (json.JSONDecodeError, TypeError):
                    fn_args = {}
                result = execute_tool(fn_name, fn_args)
                working_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": result,
                })

            continue

        # 只有文本内容、没有工具调用 → 完成
        if content:
            return content

        # 没有内容也没有工具调用 → 回退流式
        logger.warning("[TOOLS] No content or tool calls, falling back")
        payload.pop("tools", None)
        payload.pop("reasoning_effort", None)
        payload.pop("thinking", None)
        payload["stream"] = True
        fallback = requests.post(
            f"{DEEPSEEK_BASE}/chat/completions",
            headers=_headers(task),
            json=payload,
            stream=True,
            timeout=600,
        )
        full = ""
        for line in fallback.iter_lines():
            if not line:
                continue
            if isinstance(line, bytes):
                line = line.decode("utf-8")
            if not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str == "[DONE]":
                break
            try:
                data = json.loads(data_str)
                delta = data.get("choices", [{}])[0].get("delta", {})
                c = delta.get("content", "")
                if c:
                    full += c
            except json.JSONDecodeError:
                continue
        return full or "抱歉，我现在无法回答，请稍后再试。"

    # 达到最大轮次
    logger.warning("[TOOLS] Max tool rounds reached")
    return "抱歉，我需要一点时间来整理信息..."
