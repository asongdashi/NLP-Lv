# 统一对话管道方案

## 问题

当前有两条互不相干的对话通路：

```
通路A（玩家消息）:
  玩家 → _handle_chat → LLM（完整上下文+session+工具） → stream

通路B（主动推送）:
  调度器 → poller → _build_proactive_message → 独立 LLM（无session, 无对话历史, 无工具上下文）→ stream
```

通路B 的问题：
1. 没有当前 session 的对话历史——Monika 不知道刚才在聊什么
2. 没有玩家档案和人格上下文
3. 生成的回复是孤立的、突兀的
4. 回复不会被添加到会话历史中——下次对话 Monika 不知道自己主动说过话

## 目标

```
玩家消息 ─┐
          ├──→ 统一管道 ──→ LLM（同 session + 同上下文 + 同工具）──→ WebSocket  
主动触发 ─┘
```

Monika 的所有发言，无论触发源，都经过同一条管道。像一个真实的聊天对象——她主动找你说话和你找她说话，用的是同一个大脑。

## 方案

### 1. 取消 `_build_proactive_message` 的独立 LLM 调用

不再让 poller 自己去调 LLM。poller 只负责从 reality 获取 trigger_context，然后**投喂给已有的 session**。

### 2. Poller 发现主动消息时

```
poller 收到 trigger_context
    │
    ├── 玩家最近 3 分钟内有消息 → 注入 trigger_contexts 列表（已实现）
    │
    └── 玩家空闲 → 构造一个虚拟的"系统事件"
            {
              "type": "system_event",
              "event": "trigger",
              "context": "Monika 想主动发起话题: ..."
            }
         → 调用 _handle_chat 的同款流程
         → 使用当前 WebSocket session
         → 生成回复 → 流式发送 → 追加到 session
         → 回复被正常保存到 chat_logs
```

### 3. 核心改动

只需要修改 `_proactive_poller` 中的投递逻辑：

```python
# 旧代码（独立 LLM）
text = self._build_proactive_message(ctx)
await websocket.send(build_ws_response(..., content=text))

# 新代码（走统一管道）
system_event = f"[系统事件] Monika 想主动发起话题: {ctx}"
# 复用 _handle_chat 的核心逻辑
await self._unified_chat(websocket, session_id, system_event, is_system_event=True)
```

### 4. `_handle_chat` 的逻辑拆分

将 `_handle_chat` 拆为两部分：
- `_build_pipeline`：构建完整上下文 + LLM 调用（纯逻辑，输入→输出）
- `_handle_chat` / `_handle_proactive`：WebSocket 交互层（调用 _build_pipeline + 流式发送）

这样主动推送直接调用 `_build_pipeline` 拿到回复，再自己流式发送。

### 5. 影响

| 模块 | 改动 |
|------|------|
| `ws_handler.py` `_build_proactive_message` | **删除**——不再用独立 LLM |
| `ws_handler.py` `_proactive_poller` | 投递逻辑改为调用统一管道 |
| `ws_handler.py` `_handle_chat` | 提取 `_build_response` 核心逻辑 |
| `ws_handler.py` `_build_response` | **新建**——构建上下文 + LLM 调用，返回 full |
