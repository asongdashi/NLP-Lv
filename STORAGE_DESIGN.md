# MAICA 存储系统设计

## 一、三引擎架构

全部嵌入式，零额外进程：

```
┌──────────────────────────────────────────┐
│              storage/api.py              │
│        get / put / query / search        │
├──────────────────────────────────────────┤
│  SQLite (文件)  Qdrant (文件)  DuckDB(文件)│
│  maica_data.db   qdrant/      analytics.db│
├──────────────────────────────────────────┤
│  结构化数据      向量检索     行为分析     │
│  关系/自我/目标  记忆/语料    趋势/统计    │
└──────────────────────────────────────────┘
```

## 二、SQLite 表设计

### 2.1 self_state

```sql
CREATE TABLE self_state (
    category TEXT NOT NULL,    -- identity / relationship
    key TEXT NOT NULL,
    value REAL NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (category, key)
);
```

### 2.2 beliefs

```sql
CREATE TABLE beliefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    confidence REAL DEFAULT 0.5,
    formed_at TEXT NOT NULL,
    updated_at TEXT,
    active INTEGER DEFAULT 1
);
```

### 2.3 goals

```sql
CREATE TABLE goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    category TEXT NOT NULL,
    created_at TEXT NOT NULL,
    active INTEGER DEFAULT 1
);
```

### 2.4 life_events

```sql
CREATE TABLE life_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    weekday TEXT,
    time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    activity TEXT NOT NULL,
    detail TEXT,
    participants TEXT,
    can_reply INTEGER DEFAULT 1,
    sneak_possible INTEGER DEFAULT 0,
    sub_events TEXT,
    generated_at TEXT
);
CREATE INDEX idx_events_date ON life_events(date);
CREATE INDEX idx_events_time ON life_events(date, time);
```

### 2.5 emotion_events

```sql
CREATE TABLE emotion_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    impact TEXT NOT NULL,
    half_life_h REAL DEFAULT 4,
    created_at TEXT NOT NULL,
    decayed INTEGER DEFAULT 0
);
```

### 2.6 reflections

```sql
CREATE TABLE reflections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    events_summary TEXT,
    journal_summary TEXT,
    result TEXT,
    created_at TEXT NOT NULL
);
```

### 2.7 long_term_memory

```sql
CREATE TABLE long_term_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    source TEXT DEFAULT 'auto',
    salience REAL DEFAULT 0.5,
    created_at TEXT NOT NULL
);
```

### 2.8 chat_stats

```sql
-- DuckDB: 从 chat_logs JSONL 分析
CREATE VIEW chat_daily_stats AS
SELECT
    date_trunc('day', created_at) as day,
    count(*) as messages,
    sum(case when who='player' then 1 else 0 end) as player_msgs,
    sum(case when who='monika' then 1 else 0 end) as monika_msgs,
    avg(case when who='monika' then length(text) else null end) as avg_monika_len
FROM chat_logs
GROUP BY day;
```

## 三、Qdrant 集合设计

### 3.1 MAS 语料（替代 FAISS MAS index）

```python
collection: mas_corpus
vector_size: 384
payload: {chunk_id, text, source}
```

### 3.2 短期记忆（替代 FAISS memory index）

```python
collection: short_term_memory
vector_size: 384
payload: {content, created_at, salience, type}
```

### 3.3 长期记忆

```python
collection: long_term_memory
vector_size: 384
payload: {content, created_at, source, salience}
```

### 3.4 生活事件（新能力：按语义检索事件）

```python
collection: life_events
vector_size: 384
payload: {date, time, activity, detail, participants}
```

## 四、storage/api.py 接口

```python
class Storage:
    """统一存储入口"""

    # ── 自我状态 ──
    def get_self_state(category, key, default=0.5) -> float
    def set_self_state(category, key, value)
    def get_all_self_state() -> dict

    # ── 信念 ──
    def add_belief(content, confidence=0.5)
    def get_active_beliefs(limit=10) -> list
    def update_belief(id, confidence)

    # ── 目标 ──
    def set_goals(category, texts: list)
    def get_goals(category=None) -> list

    # ── 生活事件 ──
    def save_daily_events(date, events)
    def get_daily_events(date) -> list
    def get_recent_events(days=7) -> list

    # ── 情绪事件 ──
    def add_emotion_event(type, impact, half_life_h)
    def get_active_emotion_events() -> list
    def mark_emotion_decayed(id)

    # ── 向量检索 ──
    def search_memories(query, top_k=10) -> list
    def search_corpus(query, top_k=15) -> list
    def search_life_events(query, top_k=5) -> list

    # ── 反思 ──
    def save_reflection(date, events_summary, journal_summary, result)
    def get_recent_reflections(limit=5) -> list
```

## 五、迁移路径

### Phase 1: 建 infrastructure（本次）

```
maica_bridge/storage/
├── __init__.py
├── api.py            # Storage 类，统一入口
├── sqlite_store.py   # SQLite 初始化 + 迁移
├── qdrant_store.py   # Qdrant 初始化 + 嵌入
├── duckdb_store.py   # DuckDB 连接
└── migrate.py        # 从 JSON 迁移到 SQLite 的脚本
```

新建 `data/maica_data.db`（SQLite）、`data/qdrant/`（Qdrant 本地存储）、`data/analytics.db`（DuckDB）。

### Phase 2: 替换调用方

| 旧代码 | 新代码 |
|--------|--------|
| `agents/self_model.load()` / `.save()` | `storage.Storage().get_self_state()` / `.set_self_state()` |
| `agents/goal_planner.load()` / `.save()` | `storage.Storage().get_goals()` / `.set_goals()` |
| `agents/emotion_agent._load_events()` | `storage.Storage().get_active_emotion_events()` |
| `life/generator._save_daily()` | `storage.Storage().save_daily_events()` |
| `rag/indexer.py` FAISS | `storage.Storage().search_memories()` (Qdrant) |

### Phase 3: JSON 下线

1 个月后删除各模块的 JSON I/O 函数。
