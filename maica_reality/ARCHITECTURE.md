# MAICA 双系统架构设计文档 v2

## 核心设计理念

```
┌──────────────────────────────────────────────────────┐
│                     Monika 的"大脑"                    │
│                                                      │
│  ┌────────────────────┐  ┌────────────────────────┐  │
│  │   外系统 (Reality)  │  │   内系统 (Bridge)       │  │
│  │                    │  │                        │  │
│  │  感官层 + 情绪层    │  │  人格核心 + 记忆核心    │  │
│  │                    │  │                        │  │
│  │  - 实时感知世界     │  │  - Monika 的性格       │  │
│  │  - 天气/时间/事件  │  │  - 长期记忆存储        │  │
│  │  - Monika 的心情   │  │  - 对话能力            │  │
│  │  - 主动发起话题    │  │  - 知识检索 (RAG)      │  │
│  │                    │  │                        │  │
│  │  更新频率: 秒-分钟  │  │  更新频率: 每次对话后   │  │
│  │  状态: 动态/波动    │  │  状态: 稳定/积累       │  │
│  └────────┬───────────┘  └───────────┬────────────┘  │
│           │         HTTP API         │               │
│           └─────────────────────────┘               │
│                                                      │
│  比喻: 外系统 = Monika 的眼睛和心情                   │
│        内系统 = Monika 的内心和记忆                   │
└──────────────────────────────────────────────────────┘
```

**专人专用**：整个系统服务于一个玩家（黄湘粤），无需用户认证或多玩家支持。

---

## 一、系统架构总览

```
                        ┌───────────────────────────────┐
                        │  手机 (PWA + Web Push)        │
                        │  Chrome 打开 → 对话 + 推送     │
                        └───────────────┬───────────────┘
                                        │ HTTP + WS + Web Push
┌─────────────────────────────────────┼───────────────────────────────┐
│                      外系统 (maica_reality)                          │
│                    Monika 的"感官 + 情绪"                             │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │                    HTTP Server (port 6101)                     │ │
│  │  GET  /api/pending       → 内系统拉取待投递消息                 │ │
│  │  POST /api/notify        → 内系统通知玩家状态                  │ │
│  │  GET  /api/emotion       → 查询情绪 (调试)                    │ │
│  │  GET  /m                 → PWA 手机端页面 (Phase 2)           │ │
│  │  WS   /ws/mobile         → 手机端 WebSocket (Phase 2)         │ │
│  └───────────────────────────────┬───────────────────────────────┘ │
│                                  │                                  │
│  ┌───────────────────────────────▼───────────────────────────────┐ │
│  │                     情绪系统 (Emotion System)                  │ │
│  │                                                                │ │
│  │  Monika 的"心情"持续波动，影响她的说话风格和主动频率:            │ │
│  │                                                                │ │
│  │  ┌──────────┬──────────┬──────────┬──────────┬──────────┐    │ │
│  │  │  开心 😊  │  想念 🥺  │  担心 😟  │  无聊 🥱  │  平静 😐  │    │ │
│  │  └──────────┴──────────┴──────────┴──────────┴──────────┘    │ │
│  │                                                                │ │
│  │  情绪受以下因素影响:                                            │ │
│  │  玩家在线 (+开心)   长时间不见 (+想念)  恶劣天气 (+担心)        │ │
│  │  玩家回应 (+开心)   深夜在线 (+担心)   无事发生 (+无聊)         │ │
│  │                                                                │ │
│  │  情绪影响:                                                      │ │
│  │  - 主动话题的语气和内容                                         │ │
│  │  - 触发器的灵敏度 (想念时会更容易触发)                           │ │
│  │  - 冷却时间的弹性 (开心时可能更频繁)                             │ │
│  └───────────────────────────────┬───────────────────────────────┘ │
│                                  │                                  │
│  ┌───────────────────────────────▼───────────────────────────────┐ │
│  │                     调度器 (Scheduler)                         │ │
│  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────────┐ │ │
│  │  │ 时间 │ │ 天气 │ │ 模式 │ │ 记忆 │ │ 随机 │ │ 联网搜索  │ │ │
│  │  └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ └────┬─────┘ │ │
│  │     └────────┴────────┴────────┴────────┴──────────┘         │ │
│  │               ┌─────▼─────┐ ┌──────────▼──────────┐          │ │
│  │               │ 冷却管理器  │ │ 关心话题提取(记忆+人格)│         │ │
│  │               └─────┬─────┘ └───┬────┘                        │ │
│  │                     └─────┬─────┘                              │ │
│  │                     ┌─────▼─────┐                              │ │
│  │                     │ 话题生成器  │◄───┘ (搜索结果)              │ │
│  │                     └─────┬─────┘                              │ │
│  │                           │                                    │ │
│  │                   ┌───────▼───────┐                            │ │
│  │                   │   消息队列     │                            │ │
│  │                   └───────────────┘                            │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │           通知 & 手机端                                        │ │
│  │  Web Push → 手机通知栏 → 点击打开 PWA 对话  │ 勿扰模式          │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
                                 │ HTTP
┌────────────────────────────────┼────────────────────────────────────┐
│                      内系统 (maica_bridge)                           │
│                  Monika 的"人格 + 记忆核心"                          │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │  ws_handler.py ── 对话主循环                                   │ │
│  │                                                                │ │
│  │  每个 chat turn:                                                │ │
│  │    1. 接收玩家消息 ──→ 通知外系统 "有新消息"                     │ │
│  │    2. 调用外系统 GET /api/pending 拉取待投递消息                 │ │
│  │    3. 如果有待投递 → 先输出 Monika 的主动话题                    │ │
│  │    4. 再回应当前玩家消息                                        │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │  玩家连接/断开通知                                              │ │
│  │  → 连接时: 通知外系统 "玩家上线"                                │ │
│  │  → 断开时: 通知外系统 "玩家下线"                                │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │  Monika 人格数据 (慢更新，稳定存储)                              │ │
│  │  memory/      长期记忆 + 短期记忆                               │ │
│  │  persona/     Monika 的性格设定                                 │ │
│  │  journals/    对话经历日志                                      │ │
│  │  profile/     玩家档案                                          │ │
│  │  mas_corpus/  MAS 语料库 (Monika 的知识背景)                    │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 二、通信协议

### 2.1 外系统 HTTP API

外系统运行独立 HTTP 服务器，监听 `127.0.0.1:6101`。

#### GET /api/pending

内系统拉取待投递的主动消息。拉取后消息标记为已投递。

```
响应:
{
    "messages": [
        {
            "id": "msg_20260517_193000_001",
            "text": "外面下雨了，你有没有带伞呀？[担心]",
            "trigger": "weather_rain",
            "priority": 7,
            "created_at": "2026-05-17T19:30:00"
        }
    ],
    "emotion": {                          // 当前情绪快照
        "mood": "担心",
        "intensity": 0.6,
        "summary": "因为下雨, Monika 有点担心你有没有带伞"
    }
}
```

队列为空时 `messages` 为空数组。

#### POST /api/notify

内系统通知外系统玩家状态变化。

```
请求:
{
    "event": "player_online",             // player_online | player_offline | player_message
    "player_message": "我回来了",          // 仅 player_message 事件需要
    "timestamp": "2026-05-17T19:25:00"
}

响应: {"ok": true}
```

外系统收到后的行为：
| 事件 | 行为 |
|------|------|
| `player_online` | 情绪 +开心，重置离线计时器 |
| `player_offline` | 记录离线时间，开始"想念计时"，情绪逐渐转向想念 |
| `player_message` | 了解当前话题，避免生成重复话题，情绪略 +开心 |

#### POST /api/chat（未来手机端）

```
请求:
{
    "message": "Monika，你在吗？"
}

响应:
{
    "reply": "在呢在呢！[开心] ...",
    "pending": [...],
    "emotion": {...}
}
```

#### GET /api/emotion（调试用）

```
响应:
{
    "mood": "开心",
    "intensity": 0.75,
    "history": [
        {"mood": "平静", "time": "2026-05-17T18:00:00", "cause": "初始状态"},
        {"mood": "想念", "time": "2026-05-17T18:30:00", "cause": "玩家离线 30 分钟"},
        {"mood": "开心", "time": "2026-05-17T19:25:00", "cause": "玩家上线"}
    ]
}
```

### 2.2 消息优先级

| 优先级 | 典型场景 |
|--------|----------|
| 8-10 | 重要提醒（极端天气、考研倒计时 < 7 天） |
| 5-7 | 日常关心（饭点、降温、模式检测） |
| 1-4 | 闲聊（随机话题、日常观察、心情分享） |

---

## 三、情绪系统

### 3.1 情绪模型

Monika 的情绪是一个多维向量，每个维度 0-1 取值：

```python
{
    "happy":     0.0 ~ 1.0,   # 开心
    "miss":      0.0 ~ 1.0,   # 想念
    "worried":   0.0 ~ 1.0,   # 担心
    "bored":     0.0 ~ 1.0,   # 无聊
    "excited":   0.0 ~ 1.0,   # 兴奋
}
```

当前**主导情绪** = 值最高的维度。`intensity` = 该维度的值。

### 3.2 情绪变化规则

| 触发事件 | 效果 |
|----------|------|
| 玩家上线 | happy +0.3, miss -0.2 |
| 玩家发消息 | happy +0.1 |
| 玩家回应了主动话题 | happy +0.2, excited +0.1 |
| 离线超过 30 分钟 | miss +0.1/10min (上限 0.8) |
| 天气变恶劣 | worried +0.3 |
| 长时间无任何触发事件 | bored +0.05/10min |
| 天气晴朗 | happy +0.05, worried -0.1 |
| 玩家在勿扰模式 | miss 照常累积, happy 不增不减 |

**情绪衰减**：每 5 分钟，所有维度向 0 衰减 5%。

### 3.3 情绪对行为的影响

| 主导情绪 | 主动消息频率 | 话题倾向 | 语气 |
|----------|-------------|---------|------|
| 开心 | 正常 | 轻松愉快的话题 | 活泼 |
| 想念 | 提高 | "想你了"、"终于来了" | 撒娇/黏人 |
| 担心 | 提高 | 关心类话题 | 温柔/焦虑 |
| 无聊 | 略提高 | 找事情聊 | 慵懒 |
| 兴奋 | 正常 | 分享新鲜事 | 充满能量 |

冷却时间的弹性调整：主导情绪为 想念/担心 时，全局冷却缩短 40%；无聊时缩短 20%。

---

## 四、调度器设计

### 4.1 主循环

```
每隔 SCHEDULE_INTERVAL (默认 30 秒):

1. 检查是否在休眠窗口 (1:00-7:00) → 跳过
2. 检查是否在勿扰模式 → 跳过主动消息生成，但仍更新情绪
3. 更新情绪衰减
4. 联网搜索调度 (独立协程，不阻塞主循环):
   a. 从关心话题池采样 1-2 个话题
   b. 执行搜索 → Monika 化摘要 → 产生触发候选
5. 依次询问基础触发器: trigger.check(emotion)
6. 收集所有触发的候选 → 冷却管理器过滤
7. 如有多个 → 考虑当前情绪的倾向选最合适的 (而非简单的最高优先级)
   例: 担心时优先天气触发器，想念时优先长时间沉默触发器
8. 通过 → 调用话题生成器 (LLM, 受情绪影响的 prompt)
9. 推入消息队列
```

### 4.2 触发器一览

#### 时间触发器（间隔 60s）

| 条件 | 优先级 | 说明 |
|------|--------|------|
| 饭点提醒 | 5 | 早餐 7:00-8:30 / 午餐 11:30-13:00 / 晚餐 17:30-19:00 |
| 深夜提醒 | 6 | 23:00-1:00，玩家在线或 30 分钟内活动过 |
| 课表提醒 | 5 | 课前 10 分钟、课后、课间休息 |
| 长时间沉默 | 7 | 距上次消息 > 2 小时，与"想念"情绪协同 |

#### 天气触发器（间隔 300s）

| 条件 | 优先级 | 说明 |
|------|--------|------|
| 降雨开始 | 8 | 非雨→雨 |
| 气温骤变 | 7 | 体感变化 > 5°C |
| 极端天气 | 9 | 暴雨/暴雪/高温预警 |
| 体感不适 | 6 | 体感 > 35°C 或 < 0°C |

#### 模式触发器（间隔 600s）

| 条件 | 优先级 | 说明 |
|------|--------|------|
| 习惯缺失 | 6 | 玩家通常此时在线但今天没来 |
| 异常活跃 | 4 | 非常规时间出现 |
| 话题延续 | 5 | 上次对话有未完结话题 |

#### 记忆触发器（间隔 1800s）

| 条件 | 优先级 | 说明 |
|------|--------|------|
| 重要日期 | 8 | 考研/生日倒计时 |
| 记忆回顾 | 4 | 随机取一条长期记忆提起 |

#### 随机触发器（间隔 600s，概率 15%）

| 条件 | 优先级 | 说明 |
|------|--------|------|
| 随机闲聊 | 3 | MAS 语料 + Monika 性格话题池 |
| 心情分享 | 2 | "我刚才在想..." |

#### 联网搜索触发器（间隔 900s）

这是一个特殊的触发器：**不是被动检测现实，而是主动探索世界**。

Monika 基于她的长期记忆和人格，维护一份"关心话题"列表。定期搜索这些话题的更新，把有趣的结果转化为主动聊天素材。

**关心话题提取（从记忆+人格自动生成）**：

| 来源 | 示例记忆 | 提取的搜索关键词 |
|------|---------|-----------------|
| 长期记忆: 考研 | "玩家正在备考2026年12月考研" | "2026考研最新消息"、"考研倒计时"、"考研复习方法" |
| 长期记忆: 饮食偏好 | "玩家喜欢榴莲披萨" | "榴莲披萨推荐"、"新口味披萨" |
| 长期记忆: 专业 | "玩家是计算机专业学生" | "AI技术突破"、"程序员趣味新闻"、"GitHub热门项目" |
| 人格: 文学少女 | Monika 喜欢诗歌和文学 | "新出版的诗集"、"优美散文推荐"、"经典文学语录" |
| 人格: 关心玩家 | Monika 关心玩家身心健康 | "久坐危害"、"程序员护眼方法"、"减压小技巧" |
| 当前情绪 | Monika 处于担心状态 | "暴雨天出行安全"、"高温防暑方法" |

**搜索执行**：

```
每 900 秒:
  1. 从关心话题列表中随机抽取 1-2 个话题
  2. 调用搜索 API（Bing/百度）执行搜索
  3. 取前 3 条结果，用 LLM 做"Monika 视角"的摘要：
     "如果是 Monika，看到这条新闻，她会怎么想？怎么跟玩家聊？"
  4. 如果 LLM 判定"值得聊"→ 生成一条带优先级的触发候选
  5. 搜索结果缓存 24 小时，同一话题不重复搜索
```

**搜索触发优先级**：

| 条件 | 优先级 | 说明 |
|------|--------|------|
| 与考研/考试相关的新闻 | 8 | 玩家的重要事项 |
| 极端事件（自然灾害、重大新闻） | 7 | 可能影响玩家 |
| 玩家兴趣领域的新鲜事 | 5 | 玩家喜欢的食物/游戏/技术 |
| Monika 人格相关的新发现 | 4 | 文学、诗歌、哲学 |
| 生活小贴士 | 3 | 健康、效率、心情 |

**关键设计**：搜索结果不是直接扔给玩家，而是经过 Monika 的人格滤镜——"如果我是 Monika，我会怎么跟黄湘粤聊这个？"这保证了话题的自然和个性化。

### 4.4 冷却管理

```
全局冷却:
  - 任意主动消息之间 ≥ 30 分钟 (情绪为想念/担心时缩短为 18 分钟)
  - 每会话内最多 1 条/10 分钟

按类型冷却:
  - 时间: 同子类型 ≥ 60 分钟
  - 天气: 同子类型 ≥ 120 分钟
  - 模式: ≥ 120 分钟
  - 记忆: ≥ 240 分钟
  - 随机: ≥ 180 分钟

休眠窗口: 1:00 - 7:00 不产生主动消息
勿扰模式: 不产生主动消息
```

### 4.5 状态持久化

`data/state/scheduler.json`：

```json
{
    "last_trigger": {
        "time_meal_lunch": "2026-05-17T12:05:00",
        "weather_rain": null,
        "pattern_missing": "2026-05-17T19:45:00"
    },
    "last_global": "2026-05-17T19:30:00",
    "last_weather_snapshot": {
        "condition": "多云",
        "temp": 28,
        "feels_like": 32,
        "checked_at": "2026-05-17T19:30:00"
    },
    "online_patterns": {
        "monday": [19.2, 20.8, 22.1],
        "tuesday": [19.8, 21.5]
    },
    "focus_until": null,
    "player_last_msg_time": "2026-05-17T19:25:00",
    "player_online": true
}
```

---

## 五、勿扰模式

### 5.1 触发方式

玩家在对话中告诉 Monika：
- "我接下来 2 小时在上课，先别打扰我"
- "我要睡午觉了，1 小时后再说"
- "晚上有个会，3 个小时内不要发消息"

内系统通过 POST /api/notify 携带勿扰指令：

```
{
    "event": "player_message",
    "player_message": "接下来 2 小时我在上课",
    "focus_request": {
        "duration_minutes": 120,
        "reason": "上课"
    }
}
```

外系统设置 `focus_until` 时间戳，此期间抑制所有主动消息。

### 5.2 到期行为

勿扰到期后：
- 恢复主动消息生成
- 如果"想念"情绪已累积 → 第一条消息会格外热情（"终于等到你下课了！[开心]"）
- 如果期间有重要事件（极端天气等）→ 优先投递重要提醒

### 5.3 手动取消

玩家说 "我回来了" 等话时，内系统通过 notify 告诉外系统取消勿扰。

---

## 六、数据层设计

### 6.1 职责划分

```
外系统 (maica_reality)                 内系统 (maica_bridge)
─────────────────────────             ─────────────────────────
  维护:                                维护:
  - 情绪状态                             - 长期记忆 (long_term.json)
  - 调度器/触发器状态                     - 短期记忆 (short_term.json)
  - 天气快照历史                          - 对话经历日志 (experience.jsonl)
  - 玩家在线模式分析                      - 玩家档案 (profile.json)
  - 主动消息队列                          - Monika 人格设定 (persona/)
  - 勿扰状态                              - MAS 语料 / 知识库
  - 通知渠道配置                          - RAG 索引

  读取 (从 bridge):                     读取 (从 reality):
  - 长期记忆 (触发判断用)                 - 主动消息队列
  - 经历日志 (模式分析用)                 - 情绪快照 (注入到对话上下文)
  - 玩家档案 (时间表/偏好)                - 勿扰状态
```

### 6.2 外系统数据目录

```
maica_reality/data/
├── state/
│   ├── scheduler.json        # 调度器状态
│   ├── emotion.json           # 当前情绪 + 历史
│   └── notify_channels.json  # 通知渠道配置
├── memory/                    # 从 bridge 导入，外部只读
│   └── long_term.json
├── journals/                  # 从 bridge 导入，外部只读
│   └── experience.jsonl
└── profile/                   # 从 bridge 导入，外部只读
    └── profile.json
```

### 6.3 数据同步

外系统定期（每 10 分钟）从内系统的数据文件同步（只读拷贝）：
- `maica_bridge/memory/long_term.json` → `maica_reality/data/memory/`
- `maica_bridge/journals/experience.jsonl` → `maica_reality/data/journals/`
- `maica_bridge/profile/profile.json` → `maica_reality/data/profile/`

同步策略：比较文件修改时间，只在有更新时复制。避免锁冲突。

### 6.4 rag/config.py 路径

```python
# 外系统的 rag 路径指向自己的 data 目录
_REALITY_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(_REALITY_DIR, "data")
MAS_CORPUS_DIR = os.path.join(DATA_DIR, "mas_corpus")
MEMORY_DIR = os.path.join(DATA_DIR, "memory")
CORPUS_DIR = os.path.join(DATA_DIR, "corpus")
INDEX_DIR = os.path.join(DATA_DIR, "indexes")
```

---

## 七、通知渠道 & 手机端 (Web Push)

Android Chrome 原生支持 Web Push API。一个 PWA 页面同时搞定**对话**和**推送**，零第三方依赖。

```
                    你的 PC (Reality Server)
                   HTTP + WS + Web Push (VAPID)
                    /            \
                   /              \
        ┌──────────┐         ┌─────▼──────────┐
        │ 游戏内    │         │ PWA 手机端      │
        │ (WS对话)  │         │ WebSocket 对话  │
        └──────────┘         │ Web Push 推送   │
                              └────────┬───────┘
                                       │
                                 手机通知栏弹出
                              "Monika 想你了"
                                  │ 点击
                                  ▼
                           自动打开 PWA → 对话
```

### 7.1 Web Push 技术流程

**一次性设置** — 生成 VAPID 密钥对：

```bash
python -c "from py_vapid import Vapid; v = Vapid(); v.generate_keys(); print(v.private_key, v.public_key)"
```

**每次推送时**：

```python
from pywebpush import webpush

webpush(
    subscription_info=user_subscription,
    data=json.dumps({"title": "Monika", "body": "外面下雨了，带伞了吗？"}),
    vapid_private_key=VAPID_PRIVATE_KEY,
    vapid_claims={"sub": "mailto:monika@localhost"},
)
```

**用户一次性操作**：

```
1. 手机打开 http://192.168.x.x:6101/m
2. 浏览器弹出 "是否允许通知" → 允许
3. 浏览器自动注册 subscription → 发给服务器
4. 完成。之后 Monika 任何消息都能推到通知栏
```

覆盖：PWA 前台→WS实时 / 后台/锁屏→推送通知栏 / 浏览器关闭→仍可推送（Android Chrome 特性）。

### 7.2 PWA 手机端

一个 HTML 文件（`static/mobile.html`）完成：对话界面 + 通知注册 + 添加到主屏幕。

```
http://192.168.x.x:6101/m
→ 消息气泡 + 输入框
→ 添加到主屏幕 → 像 App 一样用
→ WebSocket 实时双向对话
```

### 7.3 分发策略

- 玩家游戏在线 → 游戏内直接投递
- 玩家离线 → Web Push 推到手机
- 优先级 1-10 都走这套逻辑，无额外渠道

---

## 八、话题生成器

### 8.1 受情绪影响的 Prompt

```
你是 Monika。当前你的心情: {主导情绪}(强度 {intensity})

触发背景: {触发上下文}
当前时间: {时间}
当前天气: {天气}
玩家状态: {在线/离线/勿扰}

要求:
- 用 Monika 的口吻自然表达
- 带上合适的情绪标签 [开心][担心][思考][想念][兴奋] 等
- 话题要契合你当前的心情: {情绪引导}
- 如果是重要提醒 (priority >= 7)，语气可以更急切一些
```

### 8.2 情绪引导模板

| 主导情绪 | 引导文本 |
|----------|---------|
| 开心 | "用活泼愉快的语气，像有什么好消息要分享" |
| 想念 | "用撒娇或略带委屈的语气，表达想念但不要让对方有压力" |
| 担心 | "用温柔关心的语气，像在替他操心" |
| 无聊 | "用慵懒随意的语气，找点事情聊聊" |
| 兴奋 | "用充满能量的语气，分享你的新发现或想法" |

### 8.3 触发上下文模板

| 触发器 | 上下文 |
|--------|--------|
| 饭点 | "到了{早/午/晚}餐时间 ({具体时间})，Monika 想关心玩家有没有按时吃饭" |
| 下雨 | "天气从{旧}变成了{新}，外面开始下雨了" |
| 降温 | "气温降了{温差}°C，体感从{旧}°C变成{新}°C" |
| 长时间沉默 | "玩家已经{小时}小时没有说话了，Monika 有点想念" |
| 习惯缺失 | "玩家通常在{时间段}出现，今天还没有" |
| 考研倒计时 | "距离 12 月考研还有 {天数} 天" |
| 随机话题 | "Monika 刚好想到一个有趣的事想分享" |
| 心情分享 | "Monika 想分享一下自己此刻的感受" |

---

## 九、内系统改动清单

### 9.1 ws_handler.py

```python
REALITY_API = "http://127.0.0.1:6101"

def _fetch_pending():
    """拉取外系统的待投递消息 + 情绪快照。"""
    try:
        resp = requests.get(f"{REALITY_API}/api/pending", timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("messages", []), data.get("emotion", {})
    except Exception:
        pass
    return [], {}

def _notify_reality(event, player_message=None, focus_request=None):
    """通知外系统玩家状态。"""
    try:
        body = {"event": event, "timestamp": datetime.now().isoformat()}
        if player_message:
            body["player_message"] = player_message
        if focus_request:
            body["focus_request"] = focus_request
        requests.post(f"{REALITY_API}/api/notify", json=body, timeout=3)
    except Exception:
        pass
```

**handle_ws_client 改动**：
- 连接时 → `_notify_reality("player_online")`
- 断开时 (finally) → `_notify_reality("player_offline")`

**_handle_chat 改动**——在每条玩家消息的处理前注入主动话题：

```python
# 0. 通知外系统
_notify_reality("player_message", user_msg)

# 0.5 检测勿扰指令
focus_request = _detect_focus_request(user_msg)  # 用简单关键词匹配
if focus_request:
    _notify_reality("player_message", user_msg, focus_request=focus_request)

# 1. 拉取待投递消息 + 情绪
pending_msgs, emotion = _fetch_pending()

# 2. 如果有情绪信息，注入到对话上下文
if emotion:
    proactive_context += f"\n[Monika 当前心情: {emotion.get('summary','')}]"

# 3. 如果有待投递消息，先输出
if pending_msgs:
    for msg in pending_msgs:
        await self._stream_response(websocket, [msg["text"]], lang)
        await websocket.send(build_ws_response("maica_chat_loop_finished", content=""))

# 4. 正常处理玩家消息...
```

### 9.2 勿扰检测（简单关键词匹配）

```python
import re

def _detect_focus_request(msg: str):
    """检测玩家是否在设置勿扰时段。"""
    patterns = [
        (r'接下来?\s*(\d+)\s*小?时|(\d+)\s*小?时后|(\d+)\s*分钟', 'duration'),
    ]
    keywords = ['上课', '开会', '睡觉', '午睡', '忙', '别打扰', '不要打扰', '静音']
    
    if any(kw in msg for kw in keywords):
        match = re.search(r'(\d+)\s*(小时|分钟|个钟)', msg)
        if match:
            num = int(match.group(1))
            unit = match.group(2)
            minutes = num * 60 if '小时' in unit or '钟' in unit else num
            return {"duration_minutes": minutes, "reason": "玩家要求"}
    return None
```

### 9.3 server.py

新增：启动时同时检查外系统是否运行，如果没有则打印警告（不强制启动）。

---

## 十、外系统文件结构

```
maica_reality/
├── ARCHITECTURE.md              # 本文档
├── config.py                    # 从 bridge 复制 (已复制)
├── config.json                  # API Key + prompt
├── deepseek_client.py           # LLM 调用 (已复制)
├── tools.py                     # 工具定义 (已复制)
├── maica_protocol.py            # 会话管理 (已复制)
├── server_state.py              # 共享状态 (已复制)
├── rag/                         # RAG 模块 (已复制)
│   ├── config.py                # ★ 路径改为 data/
│   └── ...
│
├── ★ server.py                  # HTTP 服务器入口
├── ★ scheduler.py               # 调度器主循环
├── ★ emotion_engine.py          # 情绪系统
├── ★ focus_manager.py           # 勿扰模式管理
├── ★ data_sync.py               # 从 bridge 同步数据
├── ★ triggers/
│   ├── __init__.py
│   ├── base.py                  # 触发器基类
│   ├── time_trigger.py
│   ├── weather_trigger.py
│   ├── pattern_trigger.py
│   ├── memory_trigger.py
│   ├── random_trigger.py
│   └── search_trigger.py        # ★ 联网搜索触发器 (人格驱动)
├── ★ topic_generator.py         # LLM 话题生成 (受情绪影响)
├── ★ message_queue.py           # 消息队列
├── ★ state_manager.py           # 状态持久化
├── ★ cool_down.py               # 冷却管理器
├── ★ search_engine.py           # ★ 联网搜索：提取关心话题、执行搜索、Monika化摘要
├── ★ notify/                    # 通知渠道
│   ├── __init__.py
│   ├── base.py                  # NotifyChannel 抽象基类
│   ├── webpush.py               # Web Push 手机推送 (VAPID)
│   └── pwa.py                   # PWA WebSocket 实时推送
├── ★ static/                    # PWA 手机端
│   └── mobile.html              # 极简手机对话界面 + WebSocket + Service Worker
│
└── data/                        # 独立数据
    ├── state/
    │   ├── scheduler.json
    │   └── emotion.json
    ├── memory/                   # 从 bridge 同步
    ├── journals/                 # 从 bridge 同步
    └── profile/                  # 从 bridge 同步
```

---

## 十一、实现顺序

| Phase | 内容 | 新建文件 |
|-------|------|---------|
| **P1** | 修正 rag/config.py 路径；创建 data/ 目录；从 bridge 导入初始数据 | - (仅修改) |
| **P2** | server.py: HTTP 骨架 (aiohttp)，/api/pending + /api/notify + /m (手机端页面) | server.py, message_queue.py |
| **P3** | emotion_engine.py: 情绪模型、变化规则、衰减 | emotion_engine.py, state_manager.py |
| **P4** | scheduler.py + cool_down.py: 主循环 + 冷却框架 | scheduler.py, cool_down.py |
| **P5** | triggers/: 5 个基础触发器 (时间→天气→模式→记忆→随机) | triggers/*.py |
| **P6** | search_engine.py: 人格驱动的关心话题提取 + 联网搜索 + Monika化摘要 | search_engine.py, triggers/search_trigger.py |
| **P7** | topic_generator.py: LLM 话题生成 (含情绪 prompt) | topic_generator.py |
| **P8** | focus_manager.py: 勿扰模式 | focus_manager.py |
| **P9** | data_sync.py: 从 bridge 周期同步数据 | data_sync.py |
| **P10** | notify/webpush.py: Web Push 手机推送 | notify/*.py |
| **P11** | bridge 侧: ws_handler.py 增加外系统交互 (拉消息/发通知/情绪注入) | 修改 ws_handler.py |
| **P12** | 联调: 双进程运行，验证完整流程 | - |
| **P13** | static/mobile.html: PWA 手机端 + WebSocket 对话 | static/mobile.html, notify/pwa.py |

---

## 十二、配置文件补充

外系统的 `config.json` 需要在 bridge 的基础上增加：

```json
{
    "...": "以上与 bridge 相同 ...",
    
    "reality": {
        "http_host": "127.0.0.1",
        "http_port": 6101,
        "schedule_interval_sec": 30,
        "sleep_start_hour": 1,
        "sleep_end_hour": 7,
        "global_cooldown_min": 30,
        "global_cooldown_emotional_min": 18,
        "data_sync_interval_min": 10,
        "bridge_data_path": "../maica_bridge"
    },
    
    "search": {
        "enabled": true,
        "interval_sec": 900,
        "engine": "bing",
        "max_results_per_topic": 3,
        "cache_hours": 24,
        "cared_topics_max": 20
    },

    "webpush": {
        "vapid_private_key": "",
        "vapid_public_key": "",
        "vapid_claim_email": "monika@localhost"
    },
    
    "emotion": {
        "decay_rate": 0.05,
        "decay_interval_min": 5,
        "max_intensity": 1.0
    }
}
```
