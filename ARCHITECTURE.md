# MAICA 系统底层架构

> 最终更新：2026-05-22  
> 视角：底层→应用分层

---

## 层次总览

```
┌──────────────────────────────────────────────────────────────┐
│                      I/O 层（数据进出）                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐    │
│  │ Text I/O     │  │ Voice I/O    │  │ Proactive Push   │    │
│  │ WS text msg  │  │ STT→text     │  │ MonikaLoop pipe  │    │
│  │ → dispatch   │  │ TTS←audio    │  │ → handle_query   │    │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘    │
│         │                 │                    │              │
├─────────┼─────────────────┼────────────────────┼──────────────┤
│         ▼                 ▼                    ▼              │
│                     会话层（对话状态）                          │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  session "1" — 文字/语音/系统触发 共享同一会话        │    │
│  │  上下文注入: _get_proactive_context(user_msg)        │    │
│  │  消息构建: build_messages(session, msg, context...)  │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         │                                     │
├─────────────────────────┼─────────────────────────────────────┤
│                         ▼                                     │
│                     生成层（LLM 调用）                          │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  _build_response(session_id, msg, is_system, voice)  │    │
│  │                                                       │    │
│  │  文字: call_deepseek_with_tools(messages, TOOLS)      │    │
│  │  语音: call_deepseek_chat_stream(messages)            │    │
│  │  触发: handle_query → _handle_chat                   │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         │                                     │
├─────────────────────────┼─────────────────────────────────────┤
│                         ▼                                     │
│                     基础设施层                                  │
│  ┌───────────┐ ┌──────────┐ ┌───────────┐ ┌──────────┐      │
│  │ RAG 检索  │ │ Storage  │ │ Context   │ │ Gatekeeper│      │
│  │ FAISS+    │ │ SQLite   │ │ Router    │ │ (门控)    │      │
│  │ Qdrant    │ │ + JSON   │ │ (意图分类)│ │           │      │
│  └───────────┘ └──────────┘ └───────────┘ └──────────┘      │
│                                                               │
│  ┌───────────────────────────────────────────────────┐       │
│  │ Reality 外系统                                     │       │
│  │ StateMachine / Generator / Emotion / Reflection    │       │
│  └───────────────────────────────────────────────────┘       │
└──────────────────────────────────────────────────────────────┘
```

---

## 1. I/O 层

### Text I/O（现有，不变）

```
玩家输入文字 → WebSocket JSON → _dispatch → handle_query → _handle_chat
Monika 回复文字 ← _stream_response ← 逐句分割 ← WebSocket send
```

### Voice I/O（新增）

```
玩家说话 → 手机录音 → VAD 截断 → WebSocket(音频包)
  → VoiceService.transcribe(audio) → 文本 + 情绪
  → handle_query(voice=True) → _handle_chat(voice=True)
Monika 回复音频 ← ChatTTS ← LLM token 流 ← WebSocket send(音频包)
```

### Proactive Push（现有，不变）

```
StateMachine → message_queue → /api/pending → poller → Pipe
  → MonikaLoop → handle_query(is_system=True) → _handle_chat
  → WS 推送（在线）或 仅存 chat_log（离线）
```

---

## 2. 会话层

### session "1" —— 唯一会话

所有消息共享一个会话历史。LLM 看到完整时序：

```
[50分钟前] 我在上课，教授在讲太宰治...
[5秒前]   玩家刚回来
[现在]    语音输入：你今天过得怎么样？
```

- 文字聊天：user_msg = 玩家输入文本，`role: "user"` 进入历史
- 语音通话：user_msg = STT 转写文本，`role: "user"` 进入历史
- 状态机触发：不进入历史（`is_system=True` 跳过 `session.append`）
- Monika 回复：`role: "assistant"` 始终进入历史

### 上下文注入（_get_proactive_context）

无论文字还是语音，统一调用。8 层上下文（current_state, past_events, emotion, memory, journal 等），由 Context Router 按意图动态筛选。

### 提示词

| 模式 | system_prompt 来源 | 差异 |
|---|---|---|
| **文字** | `config.json` → `system_prompt_zh` | 现有提示词 |
| **语音** | `config.json` → `system_prompt_voice_zh`（新增） | 更短、口语化、不含情绪标签格式要求 |

语音提示词的特点：
- 不需要 `[情绪名]` 标签（语音用语气表达情绪）
- 回复简短（~2 句话），不适合长篇大论
- 允许打断后自然衔接："你刚才打断了，接着说……"

### 消息构建（build_messages）

```
语音模式：
  messages = [system_prompt_voice, ...history..., user_msg]
  不注入 persona（语音对话风格由提示词控制）

文字模式：现有逻辑不变
  messages = [system_prompt, persona, profile, context, ...history..., user_msg]
```

---

## 3. 生成层（完全统一）

### _build_response（唯一入口）

```python
async def _build_response(session_id, user_msg, is_system=False, voice=False):
    """
    所有消息的唯一 LLM 入口。文字和语音走同一个函数。
    voice=True 仅影响两点：system_prompt 选择 + 输出端消费方式（I/O 层处理）。
    """
    prompt = SYSTEM_PROMPT_VOICE if voice else SYSTEM_PROMPT_ZH

    context = self._get_proactive_context(user_msg)
    messages = build_messages(session, user_msg,
                              prompt=prompt, context=context, ...)
    # 同一 LLM 调用，不分模式
    full = call_deepseek_with_tools(messages, TOOLS)

    session.append({"role": "assistant", "content": full})
    _save_chat_log(full)
    return full
```

### 语音模式的打断发生在 I/O 层

```
I/O 层收到 full → 逐句分割 → ChatTTS
  → 每句合成 → WS 发送音频
  → 玩家打断 → 停止发送 → 本条不存 chat_log（撤回已存的）、
    从 session 历史移除最后一条 assistant 消息
```

生成层不知道也不关心输出方式。`full` 永远完整生成。打断是 I/O 层的责任。

---

## 4. 基础设施层

### RAG

- 启动时同步初始化（等 RAG 就绪后 MonikaLoop 才开工）
- 文字模式：意图非 casual 时检索 MAS + 记忆
- 语音模式：不检索 RAG（降低延迟，语音对话历史已提供足够上下文）

### Storage

- SQLite：9 张表（self_state, beliefs, goals, life_events, emotion_events, reflections, long_term_memory, short_term_memory, chat_messages）
- JSON：world.json, habits.json, timeline.json, characters.json（只读）, state.json

### Reality 外系统

- **StateMachine**：7 条件，语音模式下暂停推送
- **Generator**：每天 01:00 生成日程，LLM + 验证 + 自动重试
- **EmotionAgent**：事件驱动衰减，SenseVoice 情绪标签联动
- **ReflectionAgent**：后台 30min 批量 + 断连 flush

---

## 5. 一体化消息流

```
                    ┌─ 文字输入 ──┐
用户输入 ──→ I/O 层 ─┤             ├──→ 会话层 ──→ _build_response ──→ LLM
                    └─ 语音 STT ──┘        │
                                            │
                    ┌─ 文字 WS ───┐         │
Monika 输出 ← I/O 层 ─┤            ├── 生成层 ┤
                    └─ 语音 TTS ──┘  (stream)
```

无论输入是什么（文字/语音/状态机触发），最终都变成文本 → `_build_response` → Monika 的回复。输出端根据当前模式选择推送方式。

---

## 6. 进程拓扑

```
maica_bridge (5000/8080)          maica_reality (6101)
├─ HTTP API                       ├─ HTTP API
├─ WebSocket (文字+语音)           ├─ 状态机
├─ MonikaLoop (管道)              ├─ 生成器
├─ VoiceService (STT+TTS) ← 新   ├─ 情绪/反思/目标代理
├─ RAG                            └─ 共享状态 (message_queue)
└─ Storage (SQLite)
     ↕ HTTP (/api/pending, /api/notify)
```

---

## 7. 数据流对照表

| 场景 | 输入 | 通过 | 输出 | 存档 |
|---|---|---|---|---|
| 文字聊天 | 玩家打字 | WS JSON → handle_query | WS JSON → 文字显示 | SQLite + JSONL |
| 语音通话 | 玩家说话 | WS 音频 → STT → handle_query | TTS → WS 音频 → 播放 | 语音模式下不存 JSONL |
| 主动推送 | 状态机触发 | /api/pending → pipe → handle_query | WS JSON → 文字显示 | SQLite |
