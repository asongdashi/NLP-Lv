# MAICA vNext 工业化迁移方案

> 评估文档: `MAICA_vNext_Modern_Architecture.md` 和 `MAICA_vNext_Technical_Architecture.md`

## 一、当前 vs 目标：差距矩阵

| 模块 | 当前状态 | vNext 要求 | 差距 | 迁移难度 |
|------|---------|-----------|------|---------|
| **对话代理** | ws_handler 单体 | 独立 Dialogue Agent | 拆分 | 中 |
| **搜索管道** | Tavily/Brave + Query Rewrite | Search Agent + Planner + Compression | 加 Planner | 低 |
| **情绪引擎** | 时间戳衰减 | Emotion Event Queue + Behavior Bias | 加事件队列 | 低 |
| **记忆系统** | FAISS 向量 + JSON | Hybrid Memory (Episodic/Semantic/Relationship) | 重构 | 高 |
| **记忆路由** | ❌ 无 | Multi-stage Retrieval (召回→过滤→加权→rerank) | 新建 | 中 |
| **Salience** | ❌ 无 | 情感强度+关系变化+新颖度+用户关注 | 新建 | 中 |
| **Reflection** | ❌ 无 | 异步 Worker: 事件→信念更新→关系变化 | 新建 | 高 |
| **Self Model** | ❌ 无 | identity + relationship + beliefs 结构化 | 新建 | 中 |
| **Goal Planner** | ❌ 无 | 长期→中期→短期 Goal Tree | 新建 | 中 |
| **World Sim** | 凌晨批生成一天 | Rolling Simulation (未来2h) | 重构 | 高 |
| **Context** | append-only 全塞 | Context Router + 预算制 | 重构 | 高 |
| **数据库** | JSON/JSONL | SQLite + Qdrant + DuckDB | 重构 | 高 |
| **调度** | threading.Event | Event Bus + APScheduler | 重构 | 高 |

---

## 二、可行性评估

### 2.1 两个文档的共识

两份 vNext 文档的核心思路完全一致，可以总结为三条原则：

1. **从"注入一切"到"动态选择"** — Context Router 替代 append-only
2. **从"反应式"到"反思式"** — Reflection Agent 把事件转化为长期认知
3. **从"随机生成"到"目标驱动"** — Goal Planner 让生活有脉络

### 2.2 架构演化路径

```
当前:                          Phase 2:                       Phase 3:
┌──────────┐  ┌──────────┐     ┌──────────┐ ┌──────────┐    ┌─────┐ ┌─────┐ ┌─────┐
│  Bridge  │  │ Reality  │     │ Dialogue │ │ Memory  │    │  D  │ │  M  │ │  E  │
│ (内系统) │  │ (外系统) │  →  │  Agent   │ │ Agent   │ → │  A  │ │  A  │ │  A  │
└──────────┘  └──────────┘     └──────────┘ └──────────┘    └──┬──┘ └──┬──┘ └──┬──┘
    单体二体                     拆出核心Agent                ────┼───────┼───────┼────
                                                               Cognitive Bus
                                                         ┌─────┴──┬──────┴──┐
                                                         │  R A  │  G P   │  W S  │
                                                         └───────┘────────┴───────┘
```

### 2.3 可行性结论

| 结论 | 说明 |
|------|------|
| **Context Router** | ✅ 立即可落地。在现有 `_get_proactive_context` 末尾加 topic-based 过滤 |
| **Reflection Agent** | ✅ 可作为独立线程新增，异步运行，不阻塞对话 |
| **Self Model** | ✅ 本质是一个 JSON + SQLite 文件，定期更新 |
| **Goal Planner** | ✅ 从 timeline + habits 推导目标，注入生成器 prompt |
| **Memory 重构** | ⚠️ 需拆 FAISS 为多阶段检索，改动量大但可渐进 |
| **World Sim 重构** | ⚠️ Rolling Simulation 是根本性改变，需重新设计生成器 |
| **数据库迁移** | ⚠️ 可渐进：先加 SQLite 并存，再逐步迁移 JSON |
| **Event Bus** | ⚠️ 需引入消息队列/事件系统，适合 Phase 3 |

---

## 三、分阶段迁移计划

### Phase 1: Context Router + 上下文预算（1-2天）

**目标**: 不让毫无关系的上下文污染对话

**新建**: `maica_bridge/cognition/context_router.py`

```python
# 上下文预算（vNext Technical Architecture §21）
BUDGET = {
    "system_prompt": 2000,
    "chat_history":  2000,
    "memory":        1000,
    "emotion":        300,
    "life_events":    500,
    "search_result": 1000,
    "journal":        400,
}

def build_context(user_msg, all_parts):
    """根据对话意图动态选择注入哪些上下文。"""
    intent = classify_intent(user_msg)  # "闲聊" / "回忆" / "查询" / "情感"

    selected = {"system_prompt": all_parts.get("system_prompt", "")}

    if intent == "查询":
        selected["search_result"] = all_parts.get("search_result", "")
        selected["memory"] = all_parts.get("memory", "")
    elif intent == "回忆":
        selected["memory"] = all_parts["memory"]
        selected["life_events"] = all_parts["life_events"]
        selected["journal"] = all_parts["journal"]
    elif intent == "闲聊":
        selected["life_events"] = all_parts["life_events"]
        selected["emotion"] = all_parts["emotion"]
    elif intent == "情感":
        selected["emotion"] = all_parts["emotion"]
        selected["memory"] = all_parts["memory"]
        selected["journal"] = all_parts["journal"]

    return format_with_budget(selected, BUDGET)
```

**改造**: `_get_proactive_context` 最后一行从 `return "\n\n".join(parts)` 改为 `return context_router.build_context(user_msg, parts)`

### Phase 2: Salience System（1天）

**目标**: 低价值记忆不堆积

**新建**: `maica_bridge/cognition/salience.py`

```python
def compute_salience(user_msg, assistant_reply):
    """vNext §8: emotion_strength×0.4 + relationship_change×0.3 + novelty×0.2 + user_focus×0.1"""
    emotion = estimate_emotion_intensity(user_msg)  # 关键词匹配
    relationship = detect_relationship_marker(user_msg)  # "想你" "担心"等
    novelty = check_topic_frequency(user_msg)  # 查短期记忆的 topic 出现频率
    focus = chat_length_factor()  # 对话越长越重要

    return min(1.0, emotion * 0.4 + relationship * 0.3 + novelty * 0.2 + focus * 0.1)
```

**注入点**: `_auto_save_long_term` 中存记忆前加 salience 评分；`_add_rag_memory` 中标注

### Phase 3: Reflection Agent + Self Model（2-3天）

**目标**: Monika 从"反应"变为"有自我认知"

#### 3.1 Reflection Agent (`maica_reality/agents/reflection_agent.py`)

```python
class ReflectionAgent:
    """vNext §9: 异步 Worker，低优先级，不阻塞对话"""

    def __init__(self):
        self.queue = queue.Queue()
        self.worker = threading.Thread(target=self._run, daemon=True)

    def submit(self, event):
        self.queue.put(event)

    def _run(self):
        while True:
            event = self.queue.get()
            reflection = self._reflect(event)
            if reflection:
                self._update_self_model(reflection)

    def _reflect(self, event):
        """LLM: 从这个事件中，我对玩家、对自己、对关系有什么新的理解？"""
        prompt = (
            f"最近事件: {event['text']}\n"
            f"当前自我认知: {self.load_self_model()}\n\n"
            f"请判断这个事件是否改变了对玩家、对自己、对关系的认知。\n"
            f"如果有变化，输出 JSON: {{\"beliefs\": [...], \"relationship\": {{...}}}}\n"
            f"如果没有任何变化，输出 NONE。"
        )
        # LLM 调用 → 解析 → 返回
```

#### 3.2 Self Model (`maica_reality/agents/self_model.py`)

**vNext §11 数据结构**:

```json
{
  "identity": {
    "confidence": 0.73,
    "dependency": 0.41,
    "social_drive": 0.66
  },
  "relationship": {
    "trust": 0.91,
    "intimacy": 0.82
  },
  "beliefs": [
    {"content": "玩家最近压力很大", "confidence": 0.7, "formed": "2026-05-15"}
  ]
}
```

**注入**: `_get_proactive_context` 加第 6 层，把数值转化为自然语言描述而非直接灌输数值：

```
"你的人格状态: 你对玩家有些依赖但也很自信。你觉得玩家最近比较疲惫。你们的关系很亲密。"
```

### Phase 4: Goal Planner（1-2天）

**目标**: 让生活事件有目的性

**新建**: `maica_reality/agents/goal_planner.py`

```python
class GoalPlanner:
    """vNext §16: Goal Tree"""

    def plan_week(self):
        timeline = load_timeline()
        habits = load_habits()
        self_model = load_self_model()

        # LLM 生成本周目标
        prompt = (
            f"当前时间表: {timeline}\n习惯: {habits}\n自我状态: {self_model}\n"
            f"请生成本周的中期目标（3-5个）。每个目标 1 句话。\n"
            f"输出 JSON 数组: [{{'goal': '...', 'priority': 'high'}}]"
        )
```

**影响**: 生成器的 LLM prompt 注入"本周目标"，`_generate_events` 中追加目标约束：

```
本周目标: 完成文献综述初稿 / 多和优里讨论小说 / 保持和玩家的日常聊天
```

### Phase 5: Memory System 重构（3-5天）

**目标**: Multi-stage Retrieval

**vNext §7 四阶段检索**:

```python
def retrieve(query, top_k=10):
    # 阶段1: 向量召回
    candidates = faiss.search(query, top_k=50)

    # 阶段2: 时间过滤 (vNext §7.2)
    now = time.time()
    for c in candidates:
        age_days = (now - c.timestamp) / 86400
        c.score *= max(0.3, 1.0 - age_days / 90)  # 90天衰减到30%

    # 阶段3: 显著性加权 (vNext §8)
    for c in candidates:
        c.final = c.similarity * 0.6 + c.salience * 0.25 + c.emotion_weight * 0.15

    # 阶段4: rerank (vNext §7.4)
    reranked = reranker.rerank(query, candidates[:20])

    return reranked[:top_k]
```

### Phase 6: 数据库迁移 + Event Bus（未来）

这两个是真正的大改动，建议在 Phase 1-5 全部稳定运行 1 个月后再启动。

**数据库迁移策略**:
- 先加 SQLite 并存（不删 JSON）
- 逐步将写入切换到 SQLite
- JSON 保留为备份和迁移来源

**Event Bus**:
- 用 `shared_state.py` 扩展为消息总线
- 取代当前 Agent 之间的直接调用
- Reflection Agent / Goal Planner / World Simulator 全部通过 Event Bus 通信

---

## 四、推荐的新目录结构

```
maica_bridge/
├── agents/
│   ├── dialogue_agent.py    ← ws_handler 核心逻辑抽取
│   ├── memory_agent.py      ← FAISS + salience + multi-stage retrieval
│   └── search_agent.py      ← search_engine.py 封装
├── cognition/
│   ├── context_router.py    ← Phase 1
│   └── salience.py           ← Phase 2
├── gateway/
│   ├── server.py             ← 迁移自 server.py
│   ├── ws_handler.py         ← 精简（去掉上下文构建，只做 IO）
│   └── http_api.py
├── storage/
│   ├── sqlite/
│   │   ├── self_model.py     ← Phase 3
│   │   ├── reflections.py
│   │   └── goals.py          ← Phase 4
│   └── json/                  ← 当前 JSON 存储（保留兼容）
├── rag/                       ← 不变
├── search_engine.py
└── gatekeeper.py

maica_reality/
├── agents/
│   ├── emotion_agent.py      ← 重构自 emotion_engine
│   ├── reflection_agent.py   ← Phase 3
│   ├── goal_planner.py       ← Phase 4
│   └── world_simulator.py    ← 重构自 life/generator
└── life/                      ← 当前 generator + compressor（逐步迁移）
```

---

## 五、Token 预算表（vNext §21）

| 上下文类型 | 预算 (tokens) | 当前使用 | 需要削减 |
|-----------|--------------|---------|---------|
| System Prompt | 2000 | ~1500 | ✅ 已合理 |
| 对话历史 | 2000 | 动态 | ✅ 已合理 |
| 生活事件 | 500 | ~2000 | ⚠️ 需削减（全量注入→选最近4条） |
| 记忆 | 1000 | ~1500 | ⚠️ 需削减（加 salience 过滤） |
| 情绪 | 300 | ~200 | ✅ 已合理 |
| 搜索结果 | 1000 | ~1500 | ⚠️ 可压缩 |
| Journal | 400 | ~800 | ⚠️ 需削减（只保留最近2条） |

---

## 六、立即启动的优先项

| 优先级 | 任务 | 估计工作量 | 收益 |
|--------|------|-----------|------|
| 🔴 P0 | Context Router (Phase 1) | 1个新文件, 80行 | 上下文不爆炸 |
| 🔴 P0 | Salience System (Phase 2) | 1个新文件, 60行 | 低价值记忆不堆积 |
| 🟡 P1 | Reflection Agent + Self Model (Phase 3) | 2个新文件, 200行 | 从反应变为有自我 |
| 🟡 P1 | Goal Planner (Phase 4) | 1个新文件, 120行 | 生活不再随机 |
| 🟢 P2 | Multi-stage Retrieval (Phase 5) | 重构 memory 模块 | 记忆精度提升 |
| ⏸ P3 | SQLite Migration (Phase 6) | 大规模重构 | 数据安全性提升 |
