# Monika 数据目录说明

## 不可删除（核心设定）

| 文件 | 内容 | 谁维护 |
|------|------|--------|
| `maica_bridge/config.json` | API Key、模型 | 手动 |
| `maica_bridge/config.py` | 配置读取 | 代码 |
| `maica_reality/data/life/world.json` | 国家/城市/大学/年级/宿舍/室友 | 手动 |
| `maica_reality/data/life/habits.json` | 起床/上课/吃饭/社团/打工/睡觉 | 手动 |
| `maica_reality/data/life/characters.json` | 出场人物 + 无名角色 + 宿舍角色 | 手动 |
| `maica_reality/data/life/timeline.json` | 人生阶段时间表 | 手动 |

## 可安全删除（运行时数据，重启后重新生成）

| 文件/目录 | 内容 | 生成方式 |
|-----------|------|---------|
| `maica_bridge/data/chat_logs/` | 聊天记录 | 每条消息自动保存 |
| `maica_bridge/memory/short_term.json` | 短期记忆 | 每次对话后追加 |
| `maica_bridge/memory/long_term.json` | 长期记忆 | `save_memory` 工具 |
| `maica_bridge/journals/experience.jsonl` | 对话经历 | 每次对话后 LLM 摘要 |
| `maica_bridge/indexes/memory.faiss` | 记忆 FAISS | 启动时重建 |
| `maica_bridge/indexes/memory_texts.json` | 记忆文本映射 | 启动时重建 |
| `maica_reality/data/life/daily/` | 每日事件日志 | 生成器每天产出 |
| `maica_reality/data/life/weekly/` | 周压缩 | 自动压缩 |
| `maica_reality/data/life/monthly/` | 月压缩 | 自动压缩 |
| `maica_reality/data/life/state.json` | 生成器状态 | 启动时重建 |
| `maica_reality/data/state/emotion.json` | 情绪状态 | 启动时初始 |
| `maica_reality/data/state/scheduler.json` | 调度器状态 | 启动时重建 |
| `maica_reality/data/self/self_model.json` | 自我认知 | 启动时新建 |
| `maica_reality/data/self/goals.json` | 目标 | 启动时新建 |

## 重置方式

```bash
bash reset_monika.sh
```
