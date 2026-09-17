# 存储迁移遗留问题审计

## HIGH — 会直接导致功能断裂

| 文件 | 行号 | 问题 |
|------|------|------|
| `life/compressor.py` | 全文件 | 读 daily/weekly/monthly JSON 文件。生成器已停止写 JSON，压缩器会空转 |
| `agents/reflection_agent.py` | L84 | `json.load(open(DAILY_DIR/{yesterday}.json))` — 读已不存在的 JSON |
| `data_sync.py` | L29-36 | sync_map 全是旧路径（memory/*.json, profile/*.json 已迁移到 SQLite） |

## MEDIUM — 绕过了 Storage API

| 文件 | 行号 | 问题 |
|------|------|------|
| `life/generator.py` | L485 | `os.path.exists(DAILY_DIR/{today}.json)` — JSON 存在性检查 |
| `triggers/search_trigger.py` | L59 | 直接读 `data/memory/long_term.json` |
| `triggers/memory_trigger.py` | L97 | 同上 |
| `triggers/time_trigger.py` | L145 | 同上 |
| `triggers/pattern_trigger.py` | L94 | 直接读 `data/journals/experience.jsonl` |

## LOW — 废弃常量，无功能影响

`gatekeeper.py`, `emotion_engine.py`, `emotion_agent.py`, `goal_planner.py` 保留了 JSON 路径常量但不再使用。

## 修复策略

1. **compressor + reflection_agent** → 改用 SQLite 读事件
2. **generator L485** → 改查 SQLite
3. **data_sync** → 删掉整个文件（数据已在 SQLite 统一）
4. **triggers** → 改用 Storage API 读记忆/日志
5. **LOW** → 删除废弃常量
