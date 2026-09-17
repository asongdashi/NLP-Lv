# 生成器时间感知 & 追补机制

## 一、时间感知

### 1.1 时间来源

生成器不依赖系统持续运行，每次启动时从**两个来源**获取"今天是什么日子"：

| 来源 | 获取方式 | 用途 |
|------|---------|------|
| OS 系统时钟 | `datetime.now()` | 主时钟，判断今天是几号、星期几、几点 |
| 交叉校验 | 调 `get_current_time` 工具 | 防止用户手动改系统时间导致异常 |

启动时对比两个值，偏差 > 1 天则信任工具返回的时间（因为系统时间可能被用户调整过）。

### 1.2 上次运行时间

持久化在 `data/life/state.json`：

```json
{
  "last_known_date": "2026-05-18",
  "last_generated_period": "evening",
  "last_startup": "2026-05-18T22:30:00"
}
```

每次成功生成一个时段日志后更新。这个文件是生成器判断"上次跑到哪了"的唯一依据。

---

## 二、追补机制

### 2.1 启动流程

```
生成器启动
    │
    ▼
① 读 state.json → 获取 last_known_date
② datetime.now() → 获取 today
③ 工具 cross-check → 确认 today 无误
    │
    ▼
④ today > last_known_date？
    │
    ├── 否 → 同一天，跳到"今日追补"
    │
    └── 是 → 有缺口，进入追补流程
```

### 2.2 追补决策树

```
缺口天数 = today - last_known_date
    │
    ├── 1 天  → 生成完整的缺失日日志（4段）
    │
    ├── 2~7 天 → 生成一段"周摘要"，覆盖缺口
    │            "这几天是期末复习周，每天早起去学校，下午在图书馆待到6点..."
    │            同时检查缺口内有无时间表事件
    │
    ├── 7~30 天 → 生成一段"阶段摘要"，更粗略
    │            "这一个月过得很快，期末考试结束了，暑假开始了..."
    │            缺口内的时间表事件逐一处理
    │
    └── 30+ 天 → 生成一段"状态迁移摘要"
                 "从高二下学期直接跳到了高三..."
                 时间表事件批量处理
                 习惯可能已大幅变化
```

### 2.3 各情况示例

**缺口 1 天（最常见——晚上睡觉关机，第二天下午开）**：

```
last_known_date: 2026-05-18
today:           2026-05-19
当前时间:         14:00

处理:
  1. 生成 2026-05-19 的 morning 日志 (07:00事件已过)
  2. 生成 2026-05-19 的 noon 日志    (12:00事件已过)
  3. 检查 2026-05-18 的日志是否需要压缩（距今天>1周→压缩为周摘要）
  4. 调度 afternoon 在 16:30 生成
```

**缺口 5 天（周末旅行回来）**：

```
last_known_date: 2026-05-15 (周五)
today:           2026-05-20 (周三)
当前时间:         10:00

处理:
  1. 生成 2026-05-16 ~ 2026-05-19 的"周末/周一/周二摘要"
     LLM prompt: "Monika 从5月15日周五晚上到5月20日周三早上，
                  中间隔了4天。这4天是周末+周一二。
                  她的习惯是周末睡懒觉、可能有社团活动。
                  请生成一段摘要描述她这4天大概在做什么。"
  2. 检查缺口内有无时间表事件 → 无
  3. 生成今天的 morning 日志
  4. 压缩 2026-05-15（今天-5天，仍在一周内，不压缩）
```

**缺口 40 天（暑假结束）**：

```
last_known_date: 2026-07-10
today:           2026-08-20
当前时间:         20:00

处理:
  1. 检查缺口内的时间表事件:
     2026-07-15: "期末考试结束"    → 处理
     2026-07-20: "暑假开始"        → 处理
     2026-08-01: "补习班开始"      → 处理
     （按时间顺序逐一应用，更新 world.json 和 habits.json）
     
  2. 生成"暑假40天摘要"（基于最新 world 和 habits）
  
  3. 生成今天的 morning/noon/afternoon/evening（今天的全部已错过，一次性生成）
  
  4. 月度习惯评估: 检查7月日志是否需要压缩+评估习惯变化
  
  5. 压缩一切超过30天的旧日志
```

### 2.4 时间表事件在缺口中的处理

这是最关键的部分——如果时间表上的重大事件正好落在缺口期间：

```python
def process_timeline_events_in_gap(from_date, to_date):
    events = load_timeline()  # 从 timeline.json 加载
    gap_events = [e for e in events if from_date < e["date"] <= to_date]
    
    for event in sorted(gap_events, key=lambda e: e["date"]):
        if event["type"] == "season_change":
            world["season"] = event["new_season"]
            habits.apply_seasonal_shift(event["new_season"])
            save_world()
            save_habits()
            
        elif event["type"] == "grade_promotion":
            world["grade"] = event["new_grade"]
            habits.apply_grade_change(event["new_grade"])  # 高三→更早起、更晚睡
            save_world()
            save_habits()
            
        elif event["type"] == "school_change":
            world["school"] = event["new_school"]
            world["city"] = event.get("new_city", world["city"])
            habits.rebuild_for_new_school()  # 大学→全新的习惯
            save_world()
            save_habits()
        
        # ... 其他事件类型
```

事件是**顺序处理**的——先发生的事件先改 world，后面的事件基于改过的 world 继续。

---

## 三、今日追补

即使没有跨天缺口，同一天内也可能有"过了点时还没生成"的情况。

### 3.1 时段追补

```
当前时间 vs 各时段触发时间:
  - 07:00 morning   → 已过 → 立即生成
  - 12:00 noon      → 已过 → 立即生成  
  - 16:30 afternoon → 未到 → 调度在 16:30 生成
  - 18:30 evening   → 未到 → 调度在 18:30 生成
```

### 3.2 时段已部分生成

如果 state.json 显示 `last_generated_period: "noon"`，那就只追补 afternoon（如果已过）和 evening，不重复生成 morning 和 noon。

---

## 四、压缩时机

追补完成后立即检查是否需要压缩：

```
压缩触发条件:
  - 任一日志距今 > 7 天 → 压缩为周摘要
  - 任一周摘要距今 > 30 天 → 压缩为月摘要
  - 任一月摘要距今 > 90 天 → 压缩为"那段时间"的一句话印象
```

压缩在追补完成后一次性批量执行，不产生大量积压。

---

## 五、状态文件

`data/life/state.json` 完整结构：

```json
{
  "last_known_date": "2026-05-18",
  "last_generated_period": "evening",
  "last_startup": "2026-05-18T22:30:00",
  "last_compression": {
    "weekly": "2026-05-11",
    "monthly": "2026-04-01"
  },
  "last_habits_evaluation": "2026-05-01"
}
```

---

## 六、边界情况

| 情况 | 处理 |
|------|------|
| 用户手动把系统时间调到了过去 | 工具交叉校验发现偏差 → 拒绝运行，日志警告 |
| 用户手动把系统时间调到了未来 | 正常生成到"未来那天"，但缺少真实世界数据（天气等），日志标注 `time_source: "unreliable"` |
| state.json 损坏/丢失 | 从现有日志文件推断 last_known_date（最新日志的日期），追补从那天到今天 |
| 没有任何日志文件 | 首次运行，从 world.json 的 initial_date 开始生成至今 |
| 缺口恰好跨过年 | 年份变化需要特殊处理（季节序列、学期序列中都有年号），用 datetime 库自然处理 |
