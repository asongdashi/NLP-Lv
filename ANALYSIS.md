# MAICA 全系统审计报告

## CRITICAL（会导致功能完全失效或数据损坏）

### 1. 昨日连续性永久断裂 — `generator.py`

`_generate_events()` 从 `DAILY_DIR/{yesterday}.json` 读取昨天的最后 3 个事件作为 LLM 提示词连续性上下文。但 `generate_day()` 的存储路径是 SQLite（`Storage().save_daily_events()`），**从不调用 `_save_daily()`**。所以 `{yesterday}.json` 永远不存在。生成器生成每天事件时没有任何前一天的记忆。

**影响**: Monika 的每日日程之间没有连续性连接。每天都是从零开始生成。

**涉及**: `generator.py:80-90`（读）, `generator.py:372`（写 SQLite，不写 JSON）, `generator.py:392`（`_save_daily` 定义但从不调用）

---

### 2. 生活习惯上下文完全失效 — `habits.py`

`get_habits_context()` 用错误的 key 路径访问 `habits.json` 的嵌套结构。函数从顶层 key 取数据，但实际数据嵌套更深：

| 函数访问 | 实际位置 | 结果 |
|---|---|---|
| `h.get("早饭", {})` | `h["早晨流程"]["早饭"]` | 空 dict |
| `h.get("论文", {})` | 根本不存在 | 空 dict |
| `h.get("钢琴", {})` | `h["自由时间"]["活动"]["弹钢琴"]` | 空 dict |
| `h.get("洗澡", {})` | `h["晚上"]["洗澡"]` | 空 dict |
| `h.get("手机和网络", {})` | 实际叫 `"手机浏览"` | 空 dict |
| `h.get("季节的影响", {})` | 根本不存在 | 空 dict |
| `上课.get("课程列表", {})` | 实际叫 `"Monika的课程"` | 空 dict |

**影响**: LLM 看到的习惯上下文大多是 `论文: 题目《》。进度。` 之类的一串空占位符。生成器对 Monika 的日常习惯几乎一无所知。

**涉及**: `habits.py:187-227`

---

### 3. 情绪事件存在性爆炸 — `emotion_agent.py`

`_save_events()` 对列表中的**所有**未衰减事件执行盲 `INSERT`。每次 `submit()` 时，旧事件被重新插入。`add_emotion_event` 是无去重的 `INSERT`，不是 `INSERT OR REPLACE`。

**影响**: 几次提交后，`emotion_events` 表被重复行填满。`get_active_emotion_events()` 返回所有行。情绪代理将它们全部加总，情绪值随着重复而膨胀。

**涉及**: `emotion_agent.py:136-142`, `storage/api.py:147-153`

---

### 4. `short_term_memory` 表从未创建 — `rag_manager.py` / `sqlite_schema.py`

`rag_manager.add_memory()` 执行 `INSERT INTO short_term_memory(...)`，但 `sqlite_schema.py` 的 `SCHEMA` 中**没有此表**。已存在的表是：`self_state`, `beliefs`, `goals`, `life_events`, `emotion_events`, `reflections`, `long_term_memory`, `chat_messages`。

**影响**: 运行时 `add_memory()` 会因 `sqlite3.OperationalError: no such table` 导致数据库错误。

**涉及**: `rag/rag_manager.py:212-218`, `storage/sqlite_schema.py`（缺 `short_term_memory`）

---

### 5. sneak 门控分支完全失效 — `ws_handler.py`

`sneak` 分支（第 403 行）使用 `trigger_contexts.append(ctx)`，但 `trigger_contexts = []` 在下文 8 行之后（第 411 行）才定义。结果是 `NameError`，被外层宽泛的异常处理静默吞掉。

**影响**: 任何时候闸门尝试通过 sneak 响应注入上下文（如"在上课时看了一眼手机"），都会崩溃。此功能完全失效。

**涉及**: `ws_handler.py:403`（使用未定义变量）, `ws_handler.py:411`（定义在此之后）

---

### 6. `reflections` 表从未写入 — 死 schema

`Storage.save_reflection()` 和 `Storage.get_recent_reflections()` 被定义但**在代码库中从未被调用**。`reflections` 表存在于 schema 中，但从未有数据进入。同时，`reflection_agent.py` 进行反思并存储结果到 `beliefs` 和 `self_state`，但**原始反思内容（事件摘要、日志摘要、LLM 输出）从不保存**。

**影响**: 反思的历史记录永久丢失。无法审核 Monika 关于自身得出的结论。

**涉及**: `storage/api.py:173-184`, `sqlite_schema.py:67-74`

---

## HIGH（功能显著受损或存在矛盾）

### 7. 时间轴存在矛盾的重复日期 — `timeline.py`

两个事件共用 `"2026-04-01"`：
- `"学期开始": "大三最后一学期。毕业论文正式启动。"`
- `"升级": "升入大四。从桜文会正式卸任。"`

`apply_event()` 会将 `world["年级"]` 设为事件中出现的最后一个年级 —— 影响 Monika 对自己所处人生阶段的认知。

**涉及**: `timeline.py:37` 与 `timeline.py:42` 冲突

---

### 8. `data_sync.py` 引用不存在的文件

同步 `bridge/memory/long_term.json` 和 `bridge/memory/short_term.json`。这些文件在磁盘上**不存在**（实际存在的是 `memory_archive.json` 和 `short_term_archive.json`）。同步因 `os.path.exists()` 检查而静默跳过 —— 不崩溃，但也不同步任何内容。

**影响**: 记忆同步完全无效。reality 的 `data/memory/` 不会获得更新。

**涉及**: `data_sync.py:29-32`

---

### 9. 缺失间隙时状态未持久化 — `generator.py`

当 `gap > 1` 时，`catch_up()` 调用 `_generate_gap_summary()`，后者写入 JSON 文件但**不调用 `_save_state()`**。因此 `state.json` 保留旧的 `last_known_date`。在下一次生成器重启时，`catch_up()` 会重新检测到同一个缺失间隙，并重新生成相同的摘要。如果没有生成器重启，`last_known_date` 永远不推进。

**涉及**: `generator.py:414-461`

---

### 10. Storage 的 Qdrant 方法是死代码

四个方法（`rebuild_memory_index`、`search_memory`、`search_corpus`、`_embed`）在 `storage/api.py` 中定义但**从未被调用**。所有 Qdrant 操作都通过 `rag/rag_manager.py`、`rag/indexer.py` 和 `rag/retriever.py` 完成。Storage 的 Qdrant 封装是遗留代码。

**涉及**: `storage/api.py:198-224`

---

### 11. `self_model.save()` 和 `mark_reflection()` 是空操作

两个函数都是 no-op（`save` 有注释"保留兼容"，`mark_reflection` 有注释"不再需要持久化"）。但两者都从 `reflection_agent.py` 被导入并调用。调用不产生任何效果——反思结果部分存储到 `beliefs` / `self_state`（通过专门的更新函数），但原始反思数据从不归档。

**涉及**: `self_model.py:47-49`（`save`）, `self_model.py:97-98`（`mark_reflection`）

---

### 12. `emotion_agent.get_state_text()` 逻辑错误

```python
active_types = [e.get("type") for e in impacts if not hasattr(e, 'get') or impacts]
```

`impacts` 是类似 `{"happy": 0.3, "miss": -0.1}` 的 dict。迭代 dict 得到**键**（字符串）。字符串有 `.get()`，所以 `hasattr("happy", 'get')` = `True`。`not True or impacts` = `impacts`，且非空 dict 为真。所以**条件永远为真**。`"happy".get("type")` 返回 `None`。`active_types` 变成 `[None, None, ...]`。

**影响**: "最近触发你情绪的事件" 行无意义。

**涉及**: `emotion_agent.py:115-117`

---

## MEDIUM（特定场景下的 bug 或未对齐问题）

### 13. 验证失败不阻止存储 — `generator.py`

`_validate()` 返回 `(False, issues)` 只记录警告。执行继续进行：`_mark_can_reply`、`_save_state`、SQLite 写入和反思提交全都以无效数据运行。

**影响**: 重叠时间、错误用餐时段或超出范围的总时长的损坏事件被静默存储。状态机和其他消费者读取并信任这些无效数据。

**涉及**: `generator.py:339-342`

---

### 14. 其他条件使用 SQLite 而 WeatherCondition 读取 JSON

`WeatherCondition._check()` 直接读取 `data/state/last_weather.json`。每隔一个条件（包括 GoalCondition、DormCondition）都通过 `Storage().get_daily_events()` 使用 SQLite。代码库中**没有任何代码写入** `last_weather.json` —— 可能由外部天气获取工具管理，但无法保证存在。

**涉及**: `state_machine.py:76-94`

---

### 15. 双存储路径：JSON vs SQLite — `generator.py`

系统有两条并行的存储机制：
- **SQLite** — 由 `generate_day()` 使用，由状态机、反思代理读取
- **JSON 文件** — 旨在由 `_generate_events()`（昨日连续性）和压缩器读取

这些路径不同步。`_generate_events()` 期望 JSON，但只有 SQLite 被写入。压缩器期望 JSON，但从不接收数据。这是问题 1 和压缩器问题的根因。

**涉及**: `generator.py:372`（SQLite 写入）, `generator.py:392`（JSON 写入从不调用）

---

### 16. `_bridge_poller` 重复实现 — `ws_handler.py`

存在两个几乎完全相同的桥接轮询器：
- `MAICABridge._bridge_poller(self, ...)` — 类方法，**死代码，从未被调用**
- `start_bridge_poller(monika_loop, ...)` — 模块级函数，**活跃，由 server.py 使用**

应移除类方法以避免混淆。

**涉及**: `ws_handler.py:259-298`（死代码）, `ws_handler.py:890-931`（活跃）

---

### 17. 闸门字符串结果未保存到 chat_log — `ws_handler.py`

当闸门返回普通字符串（非 dict）时，回复被流式传输到玩家但**从不调用 `_save_chat_log`**。玩家的消息被保存，但 Monika 的回复在聊天日志中缺失。Dict 类型的 `auto_reply` 路径（第 397 行）正确地调用了 `_save_chat_log`。

**涉及**: `ws_handler.py:404-407`

---

### 18. 无 detail 长度验证 — `generator.py`

LLM 提示词指定：`"detail: 具体描述（30-80字）"`。但 `_validate()` 从不检查 detail 长度。LLM 可以输出空、5 字符或缺失的 detail 而没有任何验证错误。

**涉及**: `generator.py:237-290`（验证）

---

### 19. `_generate_events` 遗留的 `[` 剥离逻辑

提示词要求 TSV 输出，但第 179-183 行的代码仍剥离第一个 `[` 前的所有内容（来自先前的 JSON 格式）。如果 LLM 在 detail 字段内输出包含 `[` 的 TSV（如"在[近代文学]课上..."），开头会被截断。

**涉及**: `generator.py:179-183`

---

### 20. 情绪衰减标记在 `submit()` 调用前不持久化

`get_active_impacts()` 在内存中根据经过的时间计算衰减并将事件标记为 `decayed=True`，但**仅在 `submit()` 内部调用 `_save_events()`**。如果长时间没有新事件，衰减标记永远不会提交到 SQLite。下次启动时，所有事件再次显示为未衰减。

**涉及**: `emotion_agent.py:64-90`

---

### 21. `deepseek_client.py` 和 `tools.py` 在内外系统间重复

两个文件在 `maica_reality/` 和 `maica_bridge/` 中都是以近乎完全相同的副本存在。任何未来的更改都必须两处同步，造成维护漂移风险。

**涉及**: `deepseek_client.py`（两处）, `tools.py`（两处）

---

### 22. 遗留的 JSON 路径常量

三个代理定义了不再使用的 JSON 文件路径常量（数据已迁移到 SQLite）：`goal_planner.py` 中的 `GOALS_FILE`、`emotion_agent.py` 中的 `EVENT_FILE`、`emotion_engine.py` 中的 `STATE_FILE`。

---

## LOW（代码质量或次要设计问题）

### 23. casual 意图模式过于宽泛

`context_router.py` 中的 casual 模式匹配**任何地方的** `好` 和 `吧`。这些出现在无数非 casual 句子中（"我今天心情很好"、"你做得真好"）。由于 `classify_intent` 使用 `max(scores)`，casual 在包含多个 casual 标记的中等长度消息中经常获胜——阻止记忆和日志注入，而此时提供帮助可能会更好。

**涉及**: `context_router.py:29`

---

### 24. 记忆搜索总是运行 — 对 casual 意图是浪费

`rag_manager.memory_manager.search()` 在 `_get_proactive_context`（第 755 行）中对每条消息都执行，然后结果被 context_router 的 casual 分支丢弃。浪费了 I/O。

**涉及**: `ws_handler.py:751-758`

---

### 25. 生成器轮询循环浪费：~288 次不必要的唤醒/天

生成器的后台线程在生成完成后每 300 秒就唤醒一次，检查 SQLite，发现事件已存在，然后重新睡眠。24 小时内约有 288 次不必要的唤醒。微不足道的资源浪费，但表明应使用基于调度器的设计或仅在目标时间休眠。

**涉及**: `generator.py:494-509`

---

### 26. `_has_events_in_sqlite` 和 `catch_up` 存在时间窗口竞争

如果 `catch_up` 在 `generate_day` 几乎同时运行时被调用，两者的 `_has_events_in_sqlite` 检查都可能返回 `False`，导致双边都试图生成。`catch_up` 的 `generate_day` 调用（第 479 行，`_has_events_in_sqlite` 返回 `False` 时）与计划循环（第 489-497 行）没有互斥。

至少，计划循环中的 `_has_events_in_sqlite` 检查（第 494 行）如果 `catch_up` 同时运行将产生 `True`，防止生成重复的事件。但如果 `catch_up` 在计划的 `_has_events_in_sqlite` 返回 `False` 之后、`generate_day` 调用之前的空窗期运行，两者都会生成同一天的事件（第二个会被 SQLite 的 `DELETE WHERE date` + `INSERT` 覆盖）。

**涉及**: `generator.py`：`catch_up`（第 414-461 行）与 `start`（第 489-497 行）

---

### 27. `Storage._instances` 单例模式泄漏但从未使用

`_instances` dict 以 `name` 为键存储第一个构建的实例，但从不读回。每次 `Storage()` 调用都会创建一个新对象（尽管 `init_db()` 和 `get_conn()` 使用线程本地存储，所以数据库连接是共享的）。被存储但从未读取的第一个实例是死代码。

**涉及**: `storage/api.py:15-23`

---

### 28. `reality/tools.py` rag 导入依赖脆弱的路径注入

`from rag.profile_manager import ...` 等语句之所以有效，是因为其他模块将 `maica_bridge/` 注入 `sys.path` 后才导入工具。如果 `tools.py` 在任何 `_store()` 调用之前被导入，`ModuleNotFoundError` 将被 `try/except` 块（并非为处理此情况而设计）捕获。

**涉及**: `reality/tools.py:202,296,402,419`

---

## 总结

| 严重程度 | 数量 | 主题 |
|---|---|---|
| CRITICAL | 6 | 昨日连续性、习惯上下文、情绪重复、缺少表、sneak 死代码、反思存储 |
| HIGH | 6 | 时间轴冲突、数据同步、状态持久化、死 Storage 方法、空操作、情绪逻辑 |
| MEDIUM | 10 | 验证、WeatherCondition、双存储、重复代码、日志保存、detail 验证、衰减 |
| LOW | 6 | casual 匹配、浪费的搜索、轮询循环、竞争条件、单例泄漏、路径注入 |
