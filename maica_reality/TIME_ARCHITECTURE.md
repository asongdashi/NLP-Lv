# Monika 的时间感知架构

## 核心原则

**Monika 不需要一个永远在跑的时钟。她只需要在醒来时看一眼"现在几点了"，然后算出"我错过了什么"。**

```
系统启动 → datetime.now() → "现在是 2026-05-19 14:00 周三"
    │
    ├── 上次关机记录是 2026-05-18 22:30 → 我"睡了"15.5 小时
    │   这期间错过了: 早晨日志、上午日志、中午日志
    │   → 追补
    │
    ├── 上次玩家消息是 2026-05-18 19:00 → 玩家 19 小时没找我了
    │   → 情绪: 想念 +0.19
    │
    └── 上次调度器触发是 2026-05-18 20:15 → 调度器继续从此刻运行
          不需要追补错过的触发
```

关键：**一切时间相关的计算，都基于绝对时间戳做减法，不依赖运行中的计数器。**

---

## 一、两类时间依赖

### 1.1 需要追补的（生成器）

Monika 的"生活"发生了，日志应该有记录。

| 事件 | 追补策略 |
|------|---------|
| 错过了今天的早晨日志 | 立即生成 |
| 错过了昨天一整天 | 生成昨日摘要 |
| 错过了整个寒假 | 生成"寒假摘要" + 处理时间表事件（升年级等） |
| 错过了习惯月度评估 | 立即评估 |

### 1.2 不需要追补的（一切其他系统）

没运行就是没发生，不需要"假装"。

| 事件 | 处理 |
|------|------|
| 调度器错过的主动推送 | 不追补——关机时 Monika 也没法说话 |
| 错过的"饭点提醒" | 不追补——已经过了 |
| 错过的天气变化 | 追补：天气数据是客观事实，需要对比上次快照 |
| 情绪衰减 | 不追补复杂的逐分钟模拟，用"离线时长"一次性计算 |

---

## 二、时间戳替代计数器

### 2.1 当前架构的问题

```python
# 错误：依赖运行中的循环
last_decay = time.time()        # 运行时间
emotion["miss"] += 0.1          # 每次 tick 累加

# 问题：关机 2 天，miss 值没变
```

### 2.2 修正方案

```python
# 正确：只存绝对时间，读取时计算
last_player_message = datetime.fromisoformat("2026-05-18T19:00:00")
now = datetime.now()
elapsed_hours = (now - last_player_message).total_seconds() / 3600

if elapsed_hours > 0.5:
    miss_delta = min(0.8, elapsed_hours * 0.1)
    emotion["miss"] = miss_delta
```

**不存"当前值"，只存"上次更新时的时间戳和值"。每次读取时重算。**

### 2.3 情绪引擎改造

```json
// emotion.json 改为存时间戳
{
  "values": {
    "happy": 0.3, "miss": 0.1, "worried": 0.0, "bored": 0.2, "excited": 0.0
  },
  "last_update": "2026-05-18T22:30:00",
  "decay_per_hour": {
    "happy": 0.06, "miss": 0.02, "worried": 0.06, "bored": 0.02, "excited": 0.08
  },
  "events_since_update": []
}
```

读取时：
```python
def get_emotion():
    data = load_emotion_state()
    last = datetime.fromisoformat(data["last_update"])
    now = datetime.now()
    hours = (now - last).total_seconds() / 3600
    
    # 衰减：每小时各维度衰减 decay_per_hour
    for dim, rate in data["decay_per_hour"].items():
        data["values"][dim] = max(0, data["values"][dim] - rate * hours)
    
    data["last_update"] = now.isoformat()
    save_emotion_state(data)
    return data["values"]
```

### 2.4 离线想念

```
上次玩家消息: 2026-05-18T19:00:00
现在:          2026-05-20T10:00:00
相隔:          39 小时

miss 值 = max(0.8, 39 * 0.1 / 24) ≈ 0.16
（不是"每分钟增加 0.1"，是"每小时增加一点点"）
```

### 2.5 调度器的 last_run

调度器每个触发器的 `last_run` 也改为存绝对时间戳。启动时：

```python
for trigger in _triggers:
    last_run = load_last_trigger_time(trigger.name)  # 存的是 ISO 时间戳
    if not last_run:
        last_run = datetime.now()
    elapsed = (datetime.now() - last_run).total_seconds()
    
    if elapsed >= trigger.interval_sec:
        # 该检查了
        trigger.last_run = datetime.now()
        result = trigger.check()
```

**不需要知道"关机了多久"**——直接用 `now - last_run >= interval` 判断。

---

## 三、生成器的追补

### 3.1 启动时一次性追补

```
生成器启动
    │
    ▼
读 state.json:
  last_known_date: "2026-05-18"
  last_generated_period: "evening"
    │
    ▼
datetime.now() → today = "2026-05-20", current_time = 10:00
    │
    ▼
gap_days = (today - last_known_date).days = 2  # 2026-05-19 缺失
    │
    ├── 处理 2026-05-19（缺口 1 天）→ 生成完整昨日日志
    │
    ├── 处理 2026-05-20（今天）→ 追补 morning（7:00 已过）
    │
    └── 调度 afternoon（16:30）、evening（18:30）
```

### 3.2 追补不算"实时运行"

追补的日志在启动的几秒内一次性生成完，而不是"假装 Monika 在实时经历那段时光"。生成的日志标注：

```json
{
  "date": "2026-05-19",
  "generated_at": "2026-05-20T10:00:05",
  "generation_type": "catch_up",
  "gap_from": "2026-05-18T22:30:00"
}
```

---

## 四、整个框架的时间契约

| 组件 | 时间来源 | 离线行为 |
|------|---------|---------|
| 生成器 | datetime.now() | 追补缺失的日志 |
| 情绪引擎 | datetime.now() - last_update | 衰减重算 |
| 调度器 | datetime.now() - trigger.last_run | 该查就查 |
| 门控 | 读日志文件 | 不运行就不拦 |
| 数据同步 | 比较文件 mtime | 有更新就同步 |
| Web Push | 即时 | 离线丢了就丢了 |

**整个系统没有一处依赖"持续运行了多久"——所有时间判断都是"现在是什么时候"减去"上次是什么时候"。**

---

## 五、实现影响

需要改的地方：

1. **emotion_engine.py**: 去掉 `_emotion_lock` + 运行时衰减循环，改为"读取时计算"
2. **scheduler.py**: 每个 trigger 的 `last_run` 从 `time.time()` 改为 datetime.now() 存 ISO 时间戳
3. **生成器**: 新增 startup 时的追补函数
4. **state.json**: 所有状态文件用 ISO 时间戳，不用 epoch
