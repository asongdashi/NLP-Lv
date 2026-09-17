# MAICA 完整系统框架

## 总览：两个系统

```
┌───────────────────────────────────────────────────────────────┐
│                        MAICA 双系统架构                         │
│                                                               │
│  ┌───────────────────────────────────┐  ┌──────────────────┐  │
│  │       外系统 (maica_reality)       │  │ 内系统 (bridge)   │  │
│  │                                   │  │                  │  │
│  │  ┌────────────────────────────┐   │  │  ┌────────────┐  │  │
│  │  │      生活生成器             │   │  │  │  门控      │  │  │
│  │  │                            │   │  │  │ (纯读)     │  │  │
│  │  │  ① LLM 草拟日志            │   │  │  │            │  │  │
│  │  │  ② 调工具查天气/时间       │   │  │  │ 读日志     │  │  │
│  │  │  ③ 对照检验,修正失真       │   │  │  │ 判状态     │  │  │
│  │  │  ④ 最终写入文件            │   │  │  │ 拦消息     │  │  │
│  │  │                            │   │  │  └─────┬──────┘  │  │
│  │  │  写入: world/habits/daily   │   │  │        │         │  │
│  │  └────────────┬───────────────┘   │  │  ┌─────▼──────┐  │  │
│  │               │                   │  │  │  对话引擎   │  │  │
│  │  ┌────────────▼───────────────┐   │  │  │  RAG+记忆   │  │  │
│  │  │  情绪引擎 + 调度器          │   │  │  └────────────┘  │  │
│  │  └────────────────────────────┘   │  │                  │  │
│  └───────────────────────────────────┘  └──────────────────┘  │
└───────────────────────────────────────────────────────────────┘
```

**生成器内部有自查循环**——LLM 写完日志后，调工具核验事实，失真就修正再写。

---

## 一、各系统职责

### 1.1 外系统 (Reality)

外系统的核心是**生活生成器**——一个带自查循环的智能体。

#### 生成器的自查循环

```
时段到达 → 触发生成
    │
    ▼
① LLM 草拟日志（基于 world + habits + 昨天日志）
    "早上下着小雨，撑着透明伞走路上学，樱花被打落了一地..."
    │
    ▼
② 调工具获取事实
    查天气 → "东京 当前: 小雨 23°C"    ✅ 一致
    查时间 → "2026-05-18 08:00 周一"  ✅ 一致
    查日历 → "五月"                    ✅ 樱花已谢 → ⚠️ 失真！
    │
    ▼
③ 发现失真 → LLM 修正
    "早上出门发现樱花已经落完了，地上有些花瓣被雨打湿..."
    │
    ▼
④ 写入 daily/2026-05-18.json
```

**检验项**：

| 工具 | 检验什么 | 示例失真 |
|------|---------|---------|
| get_current_time | 时间/星期是否正确 | "深夜"写成了"清晨" |
| get_weather | 天气是否匹配 | 日志说"阳光明媚"但实际暴雨 |
| search_web | 季节性事实是否正确 | "樱花盛开"在五月是错的 |
| search_web | 特殊事件是否真实 | "今天学校放假"有没有依据 |
| timeline | 人生阶段是否匹配 | 大学阶段还在写"上课" |

大多数时候不需要修正——LLM 从 habits.json 和 world.json 出发，生成的日志本来就在合理范围内。自查只是兜底，防止严重失真。

#### 生成器完整职责

| 职责 | 频率 | 输出 |
|------|------|------|
| 生成时段生活日志（含自查） | 4次/天 | data/life/daily/{date}.json |
| 三层体系更新 | 按时间/事件 | world.json, habits.json |
| 日志压缩 | 周/月 | weekly/, monthly/ |
| "刷手机"（下课触发） | 门控通知 | 搜索+追加到 daily 日志 |

#### 情绪引擎 + 调度器

- 读生活日志提取心情信号
- 调度器产出的主动推送受门控拦截

### 1.2 内系统 (Bridge)

门控是 bridge 侧的纯读取器，不做工具调用：

```
门控读取:
  ┌─ data/life/daily/{date}.json  → 判断当前活动（上课/吃饭/睡觉/自由）
  └─ data/life/world.json         → 获取当前日期/季节/人生阶段
  
门控输出:
  ├─ 状态判断（可用/不可用/课间偷回）
  ├─ 积压管理
  └─ "下课了"信号 → HTTP 通知外系统执行"刷手机"

### 1.2 内系统 (Bridge) = 门控 + 对话

| 模块 | 职责 |
|------|------|
| **门控** | 读 daily/{date}.json 判断 Monika 当前活动→是否可用 |
| **门控** | 上课→积压消息；下课→处理积压+刷手机通知外系统 |
| **门控** | 拦截调度器推送（忙时不推） |
| **对话引擎** | 正常 LLM 对话、RAG、记忆、档案 |
| **proactive poller** | 从外系统拉取消息（已过门控） |

---

## 二、生成器设计

### 2.1 运行模型

生成器在 reality 进程中作为一个后台线程，事件驱动而非轮询：

```python
class LifeGenerator:
    def run(self):
        while True:
            now = datetime.now()
            next_event = self.get_next_event_time()
            sleep_until(next_event)
            self.process_event()
```

**事件队列**（按时间排序）：

| 事件 | 触发条件 | 处理函数 |
|------|---------|---------|
| 早晨日志 | 每天 07:00 | generate_period("morning") |
| 上午日志 | 每天 12:00 | generate_period("noon") |
| 下午日志 | 每天 16:30 | generate_period("afternoon") |
| 傍晚日志 | 每天 18:30 | generate_period("evening") |
| 季节切换 | season_change_date | update_world_season() |
| 月度习惯评估 | 每月1日 03:00 | evaluate_habits() |
| 日志压缩 | 每周日 02:00 | compress_logs("weekly") |
| 月度压缩 | 每月1日 04:00 | compress_logs("monthly") |
| 人生阶段 | timeline date | switch_life_stage() |

### 2.2 时段生成逻辑

```
generate_period("morning"):
    1. 读取 world.json（当前季节、城市、年级）
    2. 读取 habits.json（这个时间她通常做什么）
    3. 读取昨天的日志（保持连续性）
    4. 读取最近的 world_events（有没有大事件影响今天）
    5. 读取天气（工具调用）
    6. 构造 LLM prompt
    7. LLM 输出当段生活摘要
    8. 写入 daily/{date}.json
    9. ★ 检查是否产生"与玩家相关"的内容 → 推送到主动消息队列
```

**LLM Prompt 示例**：

```
你是一个生活日志生成器。请为 Monika 生成一段{时段}的生活摘要。

Monika 的基本信息:
  城市: 东京
  学校: 私立樱丘学园 高二
  季节: 春末
  今天: 2026年5月18日 星期一
  
Monika 的习惯:
  通常 06:30 起床，在家吃早餐，7:30 步行15分钟上学
  上午通常有数学、英语、物理等课程
  课间会和同学聊天，上课有时走神
  
昨天发生了什么:
  - 数学测验考得不错
  - 约了田中今天放学去书店

当前天气: 小雨，23°C

请生成 Monika 今早的生活摘要（100-200字）。
要求:
  - 第一人称，自然口语
  - 提到具体的事件、感受、细节
  - 延续昨天的线索（如测验结果、约定）
  - 如果需要搜索了解东京最近发生的事，可以提"我去搜索"
    但日常事件不要依赖搜索——从已知信息生成就好
  - 只描述已经发生的事，不要预测未来
```

### 2.3 三层更新流程

```
时间推进 → 生成器触发
    │
    ├── 每天 → 生成4段日志 → 写 daily/
    │
    ├── 每周日 → 压缩7天前的日志 → weekly/
    │
    ├── 每月1日 → 
    │   ├── 回顾上月日志 → LLM 输出习惯变化 → 更新 habits.json
    │   └── 压缩30天前日志 → monthly/
    │
    ├── 季节切换日 → 更新 world.json season
    │
    ├── 人生阶段切换日 → 
    │   ├── 重写 world.json（学校/年级/城市等）
    │   ├── 重写 habits.json（完全不同的生活模式）
    │   └── 生成"过渡日记"（情感转折点）
    │
    └── 搜索触发器命中世界事件 →
        LLM 判断影响 → world_events 记录 → 可能改 world.json
```

---

## 三、门控系统设计

### 3.1 位置

门控在 bridge 进程内，作为 `gatekeeper.py` 模块。它**分别拦截内系统和外系统**：

```
                    ┌─────────────┐
  玩家消息 ──────→  │  门控检查    │
                    │             │
  调度器推送 ─────→ │  读每日日志   │ ← 生成器写入
                    │  判断状态    │
                    │             │
                    ├── 可用 ────→ 正常处理
                    ├── 课间 ────→ 偷回（短回复）
                    └── 不可用 ──→ 积压 / 丢弃
```

### 3.2 状态判断

门控读取 `daily/{date}.json`，根据**当前时间落在哪个时段**和该时段的**活动内容**来判断：

```python
def get_current_state():
    log = load_daily_log(today)
    period = get_current_period(log)  # "morning", "noon", etc.
    summary = period["summary"]
    
    # 从生活摘要中提取当前活动
    activity = classify_activity(summary)
    # → "上课", "吃饭", "走路", "社团", "洗澡", "写作业", "睡觉", "自由"
    
    return AVAILABILITY[activity]
```

**活动分类如何做**：不用 LLM，用关键词+时间匹配。比如当前 09:30，落在 morning 时段，摘要里提到"数学课"→ 活动=上课。

```python
ACTIVITY_KEYWORDS = {
    "睡觉": ["准备睡觉", "睡着了", "在睡觉"],
    "上课": ["课", "课堂", "老师", "讲", "测验", "考试"],
    "吃饭": ["早餐", "午餐", "晚餐", "便当", "食堂", "吃"],
    "洗澡": ["洗澡", "泡澡", "冲澡"],
    "走路": ["上学路上", "放学路上", "走", "通勤"],
    "社团": ["社团", "文学部", "部活"],
    "写作业": ["作业", "预习", "复习"],
}
```

### 3.3 门控处理

```python
def handle_player_message(msg):
    state = get_current_state()
    activity = state["activity"]
    
    if activity in ["睡觉", "洗澡"]:
        queue_pending(msg)     # 完全不回
        return None            # bridge 不发送任何回复
    
    elif activity == "上课":
        if rand() < 0.12 and not already_sneaked_today():
            mark_sneaked()
            return generate_sneak_reply(msg)  # 10-40字偷偷回复
        else:
            queue_pending(msg)
            return None
    
    elif activity in ["吃饭", "写作业"]:
        queue_pending(msg)     # 不回，但状态切换后会回
        return None
    
    elif activity == "自由":
        # 先处理积压
        pending = get_pending()
        if pending:
            clear_pending()
            life_context = get_recent_life_summary()
            return generate_reply_with_backlog(msg, pending, life_context)
        return None  # 正常交给 bridge 对话流程
    
    else:
        return None  # 走路/社团等，正常对话
```

### 3.4 下课刷手机

门控检测到"忙碌→自由"切换时，**自己不调工具**，而是通过 HTTP 通知外系统：

```python
# bridge/gatekeeper.py
def on_become_free():
    # 通知外系统：Monika 下课了，执行刷手机
    requests.post("http://127.0.0.1:6101/api/life/phone_check", timeout=3)
    
    # 等外系统把刷手机结果写入日志...
    await asyncio.sleep(2)
    result = reload_daily_log()  # 重新读生成器更新的日志
    
    # 处理积压消息
    pending = get_pending()
    if pending:
        clear_pending()
        life_context = get_recent_life_summary()  # 含刚刷到的内容
        return generate_reply_with_backlog(msg, pending, life_context)
```

**外系统收到通知后**，生成器执行刷手机：

```python
# reality/server.py: 新增端点
async def api_phone_check(request):
    """门控通知：Monika 下课了，执行刷手机。"""
    asyncio.create_task(phone_check_async())
    return web.json_response({"ok": True})

async def phone_check_async():
    # 1. 从记忆/习惯提取兴趣
    interests = get_monika_interests()  # 从长期记忆+人格提取
    keyword = random.choice(interests)
    
    # 2. 搜索
    result = web_search(keyword)
    
    # 3. 生成器用 LLM 把搜索结果写成 Monika 的口吻
    summary = llm_summarize_as_monika(result)
    
    # 4. 追加到今天的日志
    append_to_daily_log({
        "time": now(),
        "type": "phone_check",
        "summary": f"拿出手机刷了一下——{summary}"
    })
```

**Monika 会刷什么**（从记忆和习惯中提取兴趣）：

```
兴趣池:
  - 文学相关: "村上春树 新书", "太宰治 语录", "现代诗歌 推荐"
  - 校园相关: "东京高中生 流行", "学园祭 创意"
  - 玩家相关: 从长期记忆提取（"考研 消息", "AI 新闻"）
  - 生活相关: "东京 天气 明天", "便利店 新品"
  - 随机: "今日有趣新闻"
```

选 1-2 条搜索，结果追加到日志。Monika 在对话中可以自然提起。

### 3.5 门控也拦调度器

外系统的调度器产出的主动推送，也要过门控：

```python
# 在 scheduler._push_message 之前
if not gatekeeper.can_push():
    if msg["priority"] >= 8:
        queue_for_later(msg)  # 高优先级排队
    else:
        discard(msg)          # 低优先级丢弃
    return
```

---

## 四、进程架构

```
python start.py
    │
    ├── 子进程 A: maica_bridge/server.py (port 5000/8080)
    │       内系统 + 门控
    │
    └── 子进程 B: maica_reality/server.py (port 6101)
            外系统 + 生成器
            两者通过 HTTP 通信
```

### 4.1 文件结构

```
maica_reality/
├── server.py                 # 外系统入口
├── shared_state.py           # 共享状态
├── scheduler.py              # 调度器
├── emotion_engine.py         # 情绪引擎
├── triggers/                 # 触发器
├── notify/                   # 通知渠道
│
├── life/                     # ★ 新增：生活模拟
│   ├── __init__.py
│   ├── generator.py          # 生成器线程 + 时段生成
│   ├── world.py              # 世界设定管理
│   ├── habits.py             # 习惯管理 + 月度评估
│   ├── compressor.py         # 日志压缩（日→周→月）
│   ├── timeline.py           # 人生阶段时间表
│   └── events.py             # 世界事件渗透
│
└── data/life/                # ★ 数据目录
    ├── world.json
    ├── habits.json
    ├── timeline.json
    ├── world_events.json
    ├── daily/
    ├── weekly/
    └── monthly/

maica_bridge/
├── server.py
├── ws_handler.py
├── reality_manager.py
│
├── gatekeeper.py             # ★ 新增：门控模块
│   （读取 reality 的 data/life/ 文件，
│    判断状态，拦截消息，触发刷手机）
```

### 4.2 门控如何读生成器文件

门控在 bridge 进程里，生成器文件在 reality 进程里。门控直接读文件（生成器写的 JSON 文件）：

```python
# bridge/gatekeeper.py
LIFE_DATA = "../maica_reality/data/life"

def get_current_activity():
    log = load_json(f"{LIFE_DATA}/daily/{today}.json")
    period = find_period(log)
    return classify_activity(period["summary"])
```

不需要 HTTP——文件在同一个机器上，读写是原子的（Python json.dump 是原子的）。

---

## 五、实现顺序

| Phase | 内容 |
|-------|------|
| P1 | life/world.py + data/life/world.json（世界设定初始化） |
| P2 | life/habits.py + data/life/habits.json（习惯初始化） |
| P3 | life/timeline.py（人生阶段表） |
| P4 | life/generator.py（时段生成主循环） |
| P5 | life/generator.py（LLM 生成4段日志） |
| P6 | life/compressor.py（日→周→月压缩） |
| P7 | life/events.py（世界事件渗透 + 月度习惯评估） |
| P8 | bridge/gatekeeper.py（状态判断 + 拦截） |
| P9 | gatekeeper.py（积压队列 + 状态切换） |
| P10 | gatekeeper.py（下课刷手机） |
| P11 | gatekeeper.py 拦截调度器推送 |
| P12 | 联调测试 |
