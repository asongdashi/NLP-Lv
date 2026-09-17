# MAICA 系统架构文档

## 一、总览

```
python start.py
    │
    ├── 子进程 A: maica_bridge/server.py  (port 5000/8080)
    │       内系统 — 对话引擎 + 人格 + 记忆 + 门控
    │
    └── 子进程 B: maica_reality/server.py (port 6101)
            外系统 — 生活生成器 + 调度器 + 情绪引擎
            两者通过 HTTP 通信 (127.0.0.1:6101)
```

---

## 二、内系统 (maica_bridge)

### 职责
对话、知识检索、人格、记忆存储、门控拦截。

### 文件

| 文件 | 角色 |
|------|------|
| `server.py` | 入口，启动 HTTP(8080) + WS(5000) |
| `ws_handler.py` | WebSocket 对话处理，主动上下文注入，后台推送 poller |
| `deepseek_client.py` | LLM API 调用，支持多 Key（chat/life_gen/topic_gen） |
| `tools.py` | 工具函数（天气/时间/搜索/记忆/档案） |
| `gatekeeper.py` | 门控：读事件日志的 `can_reply`/`sneak_possible` 决定拦截或放行 |
| `maica_protocol.py` | MAICA 协议消息构建、会话管理、分句器 |
| `reality_manager.py` | 外系统集成管理（待移除） |
| `http_api.py` | HTTP API：聊天记录存取、测试端点、静态文件 |
| `config.py` / `config.json` | API Key、端口、系统 Prompt |
| `rag/` | RAG 检索：MAS 语料、记忆 FAISS、档案、日志压缩 |
| `memory/` | 长期/短期记忆数据 (JSON) |
| `journals/` | 对话经历日志 (JSONL) |
| `static/chat.html` | 聊天界面 (PWA) |
| `data/chat_logs/` | 服务器端聊天记录 (JSONL，按天分文件) |

### WebSocket 协议
端口 5000，MAICA 协议：
- `maica_connection_established` (5100)
- `maica_connection_initiated` (5200)
- `maica_core_streaming_continue` — 消息内容
- `maica_chat_loop_finished` — 消息结束

### 每次对话的处理流程
```
玩家消息到达
    │
    ├── _save_chat_log(user_msg, "player")     // 服务器端存记录
    ├── gatekeeper.handle_player_message()     // 门控检查
    │       ├── sneak_possible → 偷回语境注入
    │       ├── can_reply=false → 自动回复模板
    │       └── can_reply=true → 正常对话
    │
    ├── _fetch_pending() → 从外系统拉主动消息
    ├── _get_proactive_context() → 注入：
    │       ├── 时间/时段感/天气
    │       ├── 今日生活事件（已发生的全部）
    │       ├── 情绪快照
    │       ├── RAG 检索（MAS 语料 + 记忆）
    │       └── 最近对话经历
    │
    ├── 主 LLM 调用 (call_deepseek_with_tools + TOOLS)
    ├── _stream_response → 分句流式发送
    ├── _save_chat_log(response, "monika")     // 服务器端存回复
    ├── _add_rag_memory → 追加短期记忆
    ├── _auto_save_long_term → LLM 提取永久记忆
    └── _add_journal → 写经历日志
```

### 后台推送 Poller
每 10 秒从外系统拉取主动消息：
- 先查门控 `can_reply`，忙时跳过
- 有 `text` 直接发，有 `trigger_context` 则调主 LLM 生成后发
- 每条消息先 `_save_chat_log` 再 WebSocket 发送

### 聊天记录
`data/chat_logs/{date}.jsonl` — 每条一行 JSON: `{"time":"14:30","who":"player|monika","text":"..."}`
- HTTP API: `GET /api/chat_log` 读取，`POST /api/chat_log` 追加
- HTML 客户端加载时从服务器同步历史
- 服务器端在每条消息发出时强制保存，手机离线也不会丢

---

## 三、外系统 (maica_reality)

### 职责
生成 Monika 的每日生活日志、维护情绪、按事件触发主动推送。

### 文件

| 文件 | 角色 |
|------|------|
| `server.py` | 入口，HTTP Server (6101)，含问候生成 |
| `scheduler.py` | 调度器主循环（30s），管理触发器 |
| `shared_state.py` | 跨模块共享状态（消息队列、玩家在线等） |
| `emotion_engine.py` | 情绪引擎（时间戳驱动，不依赖持续运行） |
| `focus_manager.py` | 勿扰模式 |
| `data_sync.py` | 定期从 bridge 同步记忆/日志数据 |
| `triggers/` | 6 类触发器（时间/天气/模式/记忆/随机/搜索） |
| `topic_generator.py` | 主动话题 LLM 生成 |
| `notify/` | Web Push 通知渠道 |
| `life/` | Monika 生活模拟模块 |
| `data/life/` | 生活数据目录 |

### API 端点

| 端点 | 用途 |
|------|------|
| `GET /api/pending` | bridge 拉取待投递主动消息 |
| `POST /api/notify` | bridge 通知玩家状态变化 |
| `GET /api/emotion` | 查询情绪快照 |
| `POST /api/push_test` | 测试用推送 |
| `GET /api/vapid_key` | Web Push 公钥 |
| `POST /api/push_register` | 手机端注册推送 |

---

## 四、生活生成器 (life/)

### 三层体系

| 层 | 文件 | 内容 |
|----|------|------|
| 世界设定 | `data/life/world.json` | 国家/城市/大学/年级/宿舍/室友/季节 |
| 生活习惯 | `data/life/habits.json` | 起床/吃饭/上课/社团/打工/睡觉/周末 |
| 事件日志 | `data/life/daily/{date}.json` | 每天的结构化事件序列 |

### 生成流程
```
每天凌晨 1:00 触发
    │
    ├── LLM 生成事件序列（含 time/end/activity/detail/participants）
    ├── 代码验证（无重叠、时长合理、时间正常）
    ├── _mark_can_reply（标记每条事件的 can_reply/sneak_possible）
    ├── 附加上下文（年级/季节/学期/下一个事件）
    └── 存入 daily/{date}.json
```

### 事件格式
```json
{
    "time": "07:00", "end": "07:20",
    "activity": "起床洗漱",
    "detail": "纱世里的闹钟响了三次...",
    "participants": ["纱世里"],
    "can_reply": true,
    "sneak_possible": false
}
```

### can_reply 规则（生成器 `CANNOT_REPLY`）
- `false`: 睡觉、洗澡、考试
- `true`: 其余一切（上课、吃饭、打工、社团、写作业等）
- `sneak_possible: true`: 上课90分钟、上课45分钟

### 门控读取
门控直接读 `can_reply` 和 `sneak_possible`，不硬编码任何活动列表。
- `can_reply: true` → 正常对话
- `can_reply: false` → 自动回复
- `sneak_possible: true` → 12% 概率偷回，其余正常回复

### 时间表
`data/life/timeline.json` — 2023年4月入学 → 2027年3月毕业

### 人物档案
`data/life/characters.json` — 固定人物池（纱世里/夏树/优里/妈妈/爸爸 + 无名角色规则）

---

## 五、数据目录

```
maica_bridge/
├── data/chat_logs/          ★ 服务器端聊天记录
├── memory/                  长期/短期记忆
├── journals/                对话经历日志
├── indexes/                 FAISS 索引
├── static/                  HTML + PWA 文件
└── rag/                     RAG 模块

maica_reality/
└── data/
    └── life/
        ├── world.json       世界设定
        ├── habits.json      生活习惯
        ├── timeline.json    时间表
        ├── characters.json  人物档案
        ├── state.json       生成器状态
        ├── daily/           每日事件日志
        ├── weekly/          周压缩
        └── monthly/         月压缩
```

---

## 六、多 Key 配置

`config.json`:
```json
{
  "deepseek_api_key": "sk-...",
  "api_keys": {
    "chat": "sk-...",
    "life_gen": "sk-...",
    "topic_gen": "sk-..."
  }
}
```

未填时回退到 `deepseek_api_key`。

---

## 七、启动

```bash
python start.py
```
- 聊天界面: `http://127.0.0.1:8080/chat`
- 手机 (Tailscale): `http://100.95.0.28:8080/chat`
