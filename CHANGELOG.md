# MAICA 开发日志

## Phase 1-4: 认知基础架构 (2026-05-19)

### P1: Context Router
**新建**: `maica_bridge/cognition/context_router.py`

- 对话意图分类（查询/回忆/情感/闲聊），关键词匹配
- 按意图类型选择性注入上下文：查询→记忆+搜索，闲聊→事件+情绪
- Token 预算硬上限：memory 800, events 500, journal 300, 总计 2500

### P2: Salience System
**新建**: `maica_bridge/cognition/salience.py`

- 四因子评分：情感强度×0.4 + 关系变化×0.3 + 新颖度×0.2 + 用户关注×0.1
- 接入 `_auto_save_long_term`：低显著性直接跳过 LLM 调用
- 接入 `_add_rag_memory`：存储时标注 salience

### P3: Reflection Agent + Self Model
**新建**: `maica_reality/agents/reflection_agent.py`, `maica_reality/agents/self_model.py`

- Self Model: identity/relationship/beliefs 结构化存储
- Reflection Agent: 异步 Worker，每天回顾事件→更新信念→调整关系值
- 对话注入：数值→自然语言（"你对玩家有些依赖但也很自信"）

### P4: Goal Planner
**新建**: `maica_reality/agents/goal_planner.py`

- 短/中/长三期目标（焦点/方向/持久）
- `get_priority_boost()` 用于记忆检索加权
- `get_memory_tags()` 注入记忆系统标注当前焦点

---

## Phase 5-7: 检索与上下文优化 (2026-05-19)

### P5: Multi-stage Retrieval
**修改**: `maica_bridge/rag/memory_manager.py`

- 原：`_score_by_keyword` 关键词 + 时间衰减
- 现：关键词 → 时间衰减 → salience×0.3 + goal_boost → 重排序
- 四个阶段全部在 `search()` 方法内完成

### P6: Context Budget Enforcement
**修改**: `maica_bridge/cognition/context_router.py`

- memory: 1000→800, journal: 400→300
- 新增 `TOTAL_BUDGET = 2500`

### P7: Sub-event Injection Verification
**验证**: `maica_bridge/ws_handler.py`

- 确认大事件-小事件嵌套注入正确
- 进行中事件只注入已完成小事件（不预知）
- 已结束事件注入全部小事件

---

## Phase 8-11: 情绪与性能优化 (2026-05-19)

### P8: Emotion Event Queue
**新建**: `maica_reality/agents/emotion_agent.py`

- 事件驱动模型：每个事件有 impact + half_life
- 指数衰减：`remaining = e^(-ln(2) × elapsed / half_life)`
- 12 种预设事件类型（player_online/offline/message, weather_bad/good/extreme, silence_2h/6h, etc.）
- 过期事件自动清理
- 与旧 `emotion_engine` 并行运行，事件提交时同步更新

### P9: Emotion → Behavior Bias
**修改**: `maica_bridge/ws_handler.py` `_get_proactive_context`

- 原：`[你的心情] 当前主导心情是「开心」（强度 0.3）`
- 现：`你有点想念玩家——回应可以比平时更热切一些，但不要抱怨。`
- 数值完全隐藏，只暴露行为倾向描述

### P10: Search Compression
**修改**: `maica_bridge/search_engine.py`

- 搜索结果 > 2000 字时，LLM 压缩到 300 字摘要
- `_compress_results()` 追加在 `search()` 返回前

### P11: Context Cache
**修改**: `maica_bridge/cognition/context_router.py`

- 同一意图 10 秒内复用缓存结果
- 避免同一轮对话中重复构建相同上下文

---

## 新增文件汇总

| 文件 | Phase |
|------|-------|
| `maica_bridge/cognition/__init__.py` | P1 |
| `maica_bridge/cognition/context_router.py` | P1 |
| `maica_bridge/cognition/salience.py` | P2 |
| `maica_reality/agents/__init__.py` | P3 |
| `maica_reality/agents/self_model.py` | P3 |
| `maica_reality/agents/reflection_agent.py` | P3 |
| `maica_reality/agents/goal_planner.py` | P4 |
| `maica_reality/agents/emotion_agent.py` | P8 |
| `reset_monika.sh` | — |

## 修改文件汇总

| 文件 | Phase |
|------|-------|
| `maica_bridge/ws_handler.py` | P2, P3, P7, P9 |
| `maica_bridge/rag/memory_manager.py` | P5 |
| `maica_bridge/search_engine.py` | P10 |
| `maica_bridge/cognition/context_router.py` | P6, P11 |
| `maica_reality/server.py` | P3, P4 |

## 待办

| 项目 | 文件 |
|------|------|
| P12: 日志质量闭环 | `generator.py`, `reflection_agent.py` |
| P13: SQLite 渐进迁移 | `storage/sqlite/` |
| P14: Rolling Simulation | `life/generator.py` 重大重构 |
