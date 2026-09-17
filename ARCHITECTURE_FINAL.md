# Monika 系统架构文档

## 一、系统定位

Monika 不是一个聊天机器人。她是一个**持续存在的人格系统**：

- 有真实的生活（每天的事件由生成器产出）
- 有记忆（短期对话记忆 + 长期手动保存的关键信息）
- 有情绪（时间戳驱动，事件触发，离线自动衰减）
- 有自我认知（Reflection Agent 定期反思，形成长期信念）
- 有目标（Goal Planner 每周规划短/中/长期方向）
- 有时间感（门控系统让她知道自己此刻在做什么）
- 有主动性（调度器+门控，忙时不打扰，空闲时主动发起话题）

---

## 二、进程架构

```
python start.py
    │
    ├── 子进程 A: maica_bridge/server.py  (port 5000 WS / 8080 HTTP)
    │       内系统 — 对话引擎 + 门控 + 记忆检索
    │
    └── 子进程 B: maica_reality/server.py (port 6101 HTTP)
            外系统 — 生活生成器 + 调度器 + 情绪引擎 + 反思 + 目标
            内系统通过 HTTP 与外系统通信 (127.0.0.1:6101)
```

---

## 三、Monika 的一天

### 3.1 生成器如何工作

每天凌晨 1:00（或启动时追补），生成器调用 LLM 产出一整天的事件序列：

```
世界设定 (world.json)
  +
生活习惯 (habits.json)
  +
昨天的事件 (连续性的来源)
  +
人物档案 (characters.json)
  +
本周目标 (Goal Planner)
  +
当前情绪
    │
    ▼
LLM 生成 25-30 条事件（制表符分隔文本）
    │
    ▼
代码解析 + 验证（无重叠、时长合理）
    │
    ▼
存入 SQLite (life_events 表)
```

每条事件格式：
```json
{
  "time": "08:30", "end": "10:00",
  "activity": "上课90分钟",
  "detail": "近代文学史，A栋301",
  "participants": [],
  "can_reply": true, "sneak_possible": true,
  "sub_events": [
    {"time": "08:30", "what": "教授讲《心》创作背景"},
    {"time": "09:15", "what": "讨论先生和K的关系"}
  ]
}
```

`can_reply: false` 仅三种：**睡觉、洗澡、考试**。其余全部为 true。

`sneak_possible: true` 仅两种：**上课90分钟、上课45分钟**。门控有 12% 概率触发"偷回"。

### 3.2 门控：Monika 什么时候能聊天

每次玩家发消息，门控读取当前时间所在的事件：

1. `can_reply = true` → 正常对话
2. `sneak_possible = true` + 12% 概率 → 偷回一句（30字内）
3. `can_reply = false` → 自动回复模板（"Monika在睡觉～"）

门控也拦截主动推送：Monika 忙时调度器不推送话题。

---

## 四、一次对话的完整流程

```
玩家发消息 → WebSocket (port 5000)
    │
    ├── 1. 保存聊天记录（SQLite + JSONL 双写）
    │
    ├── 2. 门控检查（读 SQLite life_events → 判断 can_reply/sneak_possible）
    │
    ├── 3. 拉取外系统主动消息（HTTP GET /api/pending）
    │
    ├── 4. 构建上下文（_get_proactive_context）
    │       ├── 当前状态: 时间 + 时段感 + 天气 + 正在做的事件
    │       ├── 今天已发生的事: 大事件 + 已完成的小事件（不注入未来）
    │       ├── 人物感知: 提到的角色细节
    │       ├── 自我认知: Self Model（信念/关系/人格）
    │       ├── 行为倾向: 情绪 → 语气引导
    │       ├── RAG 记忆: Qdrant 向量检索
    │       └── 近期对话: chat_logs 原文
    │
    ├── 5. Context Router 裁剪（按对话意图选择注入哪些上下文）
    │
    ├── 6. LLM 调用（system_prompt + tools + 上下文 + 对话历史）
    │
    ├── 7. 流式发送回复
    │
    ├── 8. 保存 Monika 回复到聊天记录
    │
    ├── 9. 追加短期记忆（SQLite + Qdrant）
    ├── 10. 提取长期记忆（LLM → SQLite long_term_memory）
    ├── 11. 写经历日志（LLM 摘要 → experience.jsonl）
    └── 12. 提交反思事件（高情感密度时）
```

---

## 五、存储系统

三个引擎，全部嵌入式，零部署：

| 引擎 | 文件 | 存什么 |
|------|------|--------|
| **SQLite** `data/maica_data.db` | 8 张表 | self_state, beliefs, goals, life_events, emotion_events, reflections, long_term_memory, chat_messages |
| **Qdrant** `data/qdrant/` | 4 个集合 | mas_corpus, memory, long_term_memory, corpus |
| **JSONL** | 文件直接读写 | chat_logs (客户端同步), journals, world/habits/chars/timeline 核心设定 |

---

## 六、核心配置文件

| 文件 | 内容 | 读取方式 |
|------|------|---------|
| `world.json` | 大学/学部/宿舍/社团/校园地标（嵌套 JSON） | `world.get_world_context()` 递归遍历 |
| `habits.json` | 课表/论文进度/钢琴/读书/写作/洗澡/周末 | `habits.get_habits_context()` 分 section 解析 |
| `characters.json` | 5 个登场人物 + 6 个无名角色 + 规则 | generator prompt + ws_handler 人物感知 |
| `timeline.json` | 2023-2027 学年事件时间表 | `timeline.get_next_event()` |
| `config.json` | API Key / 模型 / 端口 / system prompt | `config.py` |

---

## 七、幕后的 Agent

| Agent | 运行方式 | 做什么 |
|-------|---------|--------|
| **Reflection Agent** | 后台线程，30 分钟轮询 | 回顾事件+对话 → LLM 提取新信念 → 更新 Self Model |
| **Goal Planner** | 后台线程，每周一次 | 从 timeline+self+habits → 生成本周目标 |
| **Emotion Agent** | 事件驱动，读时计算 | 玩家行为触发情绪事件 → 指数衰减 → 行为倾向 |
| **Scheduler** | 后台线程，30 秒轮询 | 6 类触发器检测 → 产出 trigger_context → bridge 拉取 |

---

## 八、聊天前端

- URL: `http://localhost:8080/chat`（PC）/ Tailscale IP（手机）
- PWA 可安装到主屏幕，Service Worker 推送
- 消息气泡 + 打字动画
- 聊天记录从服务器同步（SQLite），刷新不丢失
- 断线 3 秒自动重连

---

## 九、启动

```bash
python start.py
```

两个进程独立运行。`reset_monika.sh` 支持 `today/week/month/allinall` 四个范围。
