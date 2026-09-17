# Monika 提示词架构

## 一、完整流程

```
玩家消息 → _handle_chat
    │
    ├── gatekeeper.handle_player_message()   // 门控拦截
    │       └── 注入 trigger_contexts (sneak/自动回复等)
    │
    ├── _get_proactive_context(user_msg, emotion)  // ★ 核心：构建上下文
    │       │
    │       ├── 第1层: [你现在的状态]           ← 时间/天气/当前事件/时段感
    │       ├── 第2层: [你今天已经经历过的事]   ← past_events (end ≤ now)
    │       ├── 第3层: [你的心情]               ← 情绪引擎
    │       ├── 第4层: RAG 语料 + 记忆关键词    ← FAISS + memory search
    │       └── 第5层: [今天的对话经历]         ← journals/experience.jsonl
    │
    ├── build_messages(session, user_msg, lang, context, persona, profile, session_id)
    │       └── system prompt + context block + 对话历史 + 用户消息
    │
    └── call_deepseek_with_tools(messages, TOOLS)
```

## 二、各层数据源

| 层 | 来源 | 更新频率 | 可靠性 |
|----|------|---------|--------|
| 时间/时段感 | `datetime.now()` + 硬编码规则 | 每次对话 | ★★★★★ |
| 当前事件 | `maica_reality/data/life/daily/{date}.json` 事件表 | 每天生成一次 | ★★★★ (依赖LLM生成质量) |
| 过去事件 | 同上 | 同上 | ★★★★ |
| 天气 | `tools._get_weather()` wttr.in API | 每次对话 | ★★★ (API偶尔断) |
| 情绪 | 外系统 emotion_engine | 每次状态变化 | ★★★★ |
| RAG/MAS | FAISS 索引 (7597 chunks) | 启动时构建 | ★★★ |
| 对话记忆 | FAISS 关键词匹配 | 每次对话后更新 | ★★★ |
| 对话经历 | `journals/experience.jsonl` LLM摘要 | 每次对话后追加 | ★★ (摘要可能有偏差) |

## 三、当前事件判断逻辑

```
for 每个事件 in daily/{date}.json:
    start_min = parse(event.time)
    end_min   = parse(event.end)
    
    if 睡觉 and end ≤ start:  end += 24*60   // 跨天修正
    if 睡觉 and now < end:    now += 24*60   // 凌晨时修正
    
    now in [start, end) → current_activity  【你此刻正在做这件事】
    now ≥ end           → past_events       [你今天已经经历过的事]
    now < start         → upcoming_events   [接下来要做]
```

## 四、已知问题 & 冲突点

### 4.1 对话记忆污染

**症状**: Monika 说"刚上完近代文学课"，但实际还在上。

**原因**: 修复前的对话中 Monika 说了错误的话 → 被 journal 记录 → 对话记忆检索到 → 重复输出。journal 的 LLM 摘要本身也有偏差。

**方向**: 清除旧 journal 或降低 journal 权重。

### 4.2 硬编码时段感

`time_feel` 是硬编码的时间段描述（"上午精力充沛"），与生活日志的实际活动可能不一致。

### 4.3 天气双向查询

当前查的是 `get_location_city()`（玩家城市），但写日志时用的是东京。Monika 的"真实天气"没法获取——wttr.in 对日本城市的支持不稳定。

### 4.4 情绪与日志脱节

情绪引擎基于玩家行为，不基于日志内容。日志里"今天过得很糟"不会影响情绪。

### 4.5 记忆检索可能跑偏

`memory_manager.search(user_msg[:50])` 用前 50 个字符做关键词，可能匹配到陈旧的或错误的记忆。

## 五、改进方向

1. **journal 降权或清洗**: 对话经历摘要是 LLM 生成的二手信息，不如直接用 chat_logs 原文
2. **当前事件优先级提升**: 当前事件标记 `【你此刻正在做这件事，还没有结束】` 已加，但历史对话记忆可能覆盖它
3. **weather 稳定性**: 考虑换天气源或增加重试
