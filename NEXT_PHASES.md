# MAICA 下一批落地规划 (Phase 20-24)

## 已完成总览 (P1-P19)

19 个 Phase。从 bare chat 到完整的认知架构 + 情绪 + 反思 + 目标 + 检索管道。

---

## 当前系统瓶颈评估

| 维度 | 状态 | 瓶颈 |
|------|------|------|
| 上下文构建 | ✅ Router + Budget | TOTAL_BUDGET 未强制执行 |
| 记忆检索 | ✅ 四阶段 | Salience 不衰减 |
| 情绪系统 | ✅ 事件驱动 | 重启后事件状态丢失 |
| 搜索 | ✅ Tavily + 多轮 | 深度模式未启用 |
| 反思 | ✅ 异步 Worker | 启动后首次触发需等 30 分钟 |
| RAG | ✅ MAS + 记忆 | 闲聊时 MAS 语料是噪音 |
| 生成器 | ✅ 事件驱动 | 事件数量多但 detail 偏短 |

---

## Phase 20: TOTAL_BUDGET 强制执行

### 问题
`TOTAL_BUDGET = 2500` 定义了但在 `build()` 中从未检查。

### 方案
在 `build()` 返回前，扣减各段长度直到总和 < TOTAL_BUDGET。

```python
total = sum(len(s) for s in selected)
if total > TOTAL_BUDGET:
    # 从最不重要的段开始截断
    for key in ["journal", "past_events", "memory"]:
        if total <= TOTAL_BUDGET: break
        # ...
```

### 改动
- `context_router.py`: `build()` 末尾追加 15 行

---

## Phase 21: Salience 时间衰减

### 问题
Salience 评分是静态的。3 个月前的"重要对话"和昨天的"重要对话"同等权重。

### 方案
在 `compute()` 返回分数前乘以时间衰减因子：
```python
# 如果提供了 created_at 时间戳
age_days = (now - created_at) / 86400
decay = max(0.3, 1.0 - age_days / 90)  # 90天衰减到30%
score *= decay
```

### 改动
- `cognition/salience.py`: `compute()` 新增可选参数 `created_at`
- `rag/retriever.py`: 调用时传入时间戳

---

## Phase 22: Emotion Event 持久化衰减

### 问题
`emotion_agent.py` 的事件保存在 JSON 文件中，但 `decayed` 标记只在内存中更新。重启后所有事件重新变成活跃。

### 方案
`get_active_impacts()` 中计算衰减后，立即保存 `decayed` 状态到文件。

### 改动
- `agents/emotion_agent.py`: `get_active_impacts()` 末尾加 2 行

---

## Phase 23: RAG 意图感知（闲聊时跳过 MAS）

### 问题
无论什么对话，`_get_proactive_context` 都会调用 `rag.retrieve()` 搜索 7500 条 MAS 语料。闲聊时间也浪费 token。

### 方案
在 Context Router 分类后，闲聊意图跳过 MAS 检索（RAG 层），只保留记忆搜索。

### 改动
- `ws_handler.py`: RAG 检索前检查意图分类

---

## Phase 24: Reflection 启动加速

### 问题
Reflection Worker 有 30 分钟 `_stop.wait()` 延迟，启动后第一次反思要等很久。

### 方案
启动后先 `_stop.wait(60)`（只等 1 分钟），给系统时间加载数据，然后进入 30 分钟轮询。

### 改动
- `agents/reflection_agent.py`: `_run()` 首次 wait 改为 60s

---

## 优先级

| Phase | 价值 | 改动量 | 说明 |
|-------|------|--------|------|
| P20: TOTAL_BUDGET | 高 | ~15 行 | 防上下文失控 |
| P21: Salience 衰减 | 高 | ~10 行 | 旧记忆自然消退 |
| P22: Emotion 持久化 | 中 | ~2 行 | 重启不丢状态 |
| P23: 闲聊跳过 MAS | 中 | ~8 行 | 节省 token |
| P24: Reflection 加速 | 低 | ~2 行 | 首次反思更快 |

全部合计 ~37 行，属于"精修打磨"阶段。
