# 当前存储架构

## 三引擎

| 引擎 | 文件 | 存什么 |
|------|------|--------|
| **SQLite** `data/maica_data.db` | `storage/sqlite_schema.py` | self_state, beliefs, goals, life_events, emotion_events, long_term_memory, chat_messages |
| **Qdrant** `data/qdrant/` | `storage/qdrant_client.py` (共享单例) | 向量：mas_corpus, memory, corpus |
| **JSONL** | 直接文件读写 | chat_logs (客户端同步用), journals, world/habits/chars/timeline 核心设定 |

## 谁在用哪个

| 模块 | 读写方式 |
|------|---------|
| `self_model.py` | → `storage/api.py` → SQLite |
| `goal_planner.py` | → `storage/api.py` → SQLite |
| `emotion_engine.py` | → `storage/api.py` → SQLite |
| `emotion_agent.py` | → `storage/api.py` → SQLite |
| `generator.py` | → `storage/api.py` → SQLite (life_events) + JSON 备份 |
| `ws_handler.py` | → SQLite (chat_messages) + JSONL (chat_logs) |
| `rag_manager.save_long_term` | → SQLite (long_term_memory 文本) + Qdrant 增量 upsert (向量) |
| `rag_manager._add_rag_memory` | → 短期 JSON 文件 + Qdrant 全量重建 (memory 集合) |
| `rag_manager.retrieve` | → Qdrant (mas_corpus + memory 集合) |
| `gatekeeper.py` | → 直接读 `data/life/daily/{date}.json` |
| `reset_monika.sh` | → TRUNCATE SQLite 表 + 删 Qdrant 目录 + 删 JSON 文件 |

## 调用路径（一条聊天消息为例）

```
玩家发消息 → ws_handler._handle_chat
    │
    ├── gatekeeper.handle_player_message()
    │       └── 直接读 daily/{date}.json (不受存储系统管理)
    │
    ├── _get_proactive_context()
    │       ├── 直接读 daily/{date}.json (事件注入)
    │       ├── self_model.to_prompt_context() → SQLite
    │       ├── emotion_agent.get_state_text() → SQLite
    │       ├── rag.retrieve() → Qdrant (mas_corpus + memory)
    │       └── 直接读 journals/ + chat_logs/
    │
    ├── LLM 调用
    │       └── 工具调用:
    │           ├── save_memory → SQLite + Qdrant 增量
    │           ├── search_memory → Qdrant
    │           └── _add_rag_memory → JSON + Qdrant 全量重建
    │
    └── _save_chat_log → SQLite + JSONL 双写
```

## 问题

1. **gatekeeper 和生产环境注入直接读 JSON**，没走 Storage API
2. **Qdrant 全量重建 vs 增量** 混用（长期记忆增量，短期记忆全量）
3. **JSON 备份残留** — 生成器双写 SQLite + JSON
