# 统一管道 + 状态机架构

## 一、问题

当前有三个入口进入 Monika 的对话系统，路径各不相同：

```
玩家消息 → _handle_chat → _build_response → LLM → 发送
调度器触发 → poller → _build_response → LLM → 发送   (独立session, 无对话上下文)
```

问题：
1. 调度器消息和玩家消息不是同一个"管道"
2. 调度器触发词（"玩家上线了"）是被动拉取的，不是主动推进的
3. Monika 需要"检查是否有调度消息"这一外部循环

## 二、目标架构

所有消息进入同一个管道，Monika 循环读取：

```
                  ┌──────────────┐
  玩家 WebSocket →│              │
                  │   消 息 管 道 │ ← Monika 循环读取
  状态机 →───────→│   (Queue)    │     处理 → LLM → 发送
                  │              │     空 → 静默
                  └──────────────┘
```

- 玩家发消息 → push 到管道
- 到饭点了 → 状态机 push "[饮食提醒] Monika想提醒玩家按时吃早饭…"
- 下雨了 → 状态机 push "[天气提醒] 东京下雨了，Monika想起了什么…"
- 玩家久未上线 → 状态机 push "[状态提醒] 玩家已经2小时没说话了，Monika有点想念…"
- Monika 读管道 → 有消息就处理 → 全部处理完后清空 → 继续静默等待

## 三、状态机 vs 调度器

| | 旧：调度器 | 新：状态机 |
|---|---|---|
| 触发方式 | 30秒轮询，被动检测 | 事件驱动 + 条件判断 |
| 存放位置 | maica_reality/scheduler.py | maica_reality/state_machine.py |
| 输出 | 推送到 reality 的消息队列（等待 bridge 拉取） | 直接 push 到统一管道 |
| 格式 | {"trigger_context": "玩家上线了"} | "[时间提醒] 到午餐时间了…" |

状态机不"调度"任何东西。它只是观察世界状态，当条件满足时，向管道写入一条消息。Monika 读到这条消息后，和读玩家消息完全一样地处理。

## 四、消息格式

管道中的每一条消息遵循统一格式：

```python
@dataclass
class PipeMessage:
    source: str       # "player" | "state_machine"
    text: str         # 消息正文
    timestamp: float  # 入队时间
    priority: int     # 1-10，供排序
```

示例：

```python
# 玩家消息
PipeMessage(source="player", text="早啊Monika", priority=5)

# 状态机消息
PipeMessage(source="state_machine", text="[饮食提醒] 现在是午餐时间，Monika想提醒玩家按时吃饭。", priority=6)

# 状态机消息（高优先级）
PipeMessage(source="state_machine", text="[天气提醒] 东京台风预警，Monika感到担心。", priority=9)
```

## 五、Monika 的主循环

```python
class MonikaLoop:
    def __init__(self):
        self.pipe = Queue()  # 线程安全管道
        self.state_machine = StateMachine(self.pipe)
        self._running = False

    async def run(self, websocket):
        self._running = True
        self.state_machine.start()  # 后台线程

        while self._running:
            # 1. 从管道读取所有待处理消息
            messages = self._drain_pipe()

            # 2. 如果没有消息，短暂等待后继续
            if not messages:
                await asyncio.sleep(1)
                continue

            # 3. 按优先级排序
            messages.sort(key=lambda m: m.priority, reverse=True)

            # 4. 逐条处理：每条消息都走统一的 _build_response
            full_text = "\n\n".join(m.text for m in messages)
            response = await self._build_response(
                session_id=1,
                user_msg=f"[系统事件] {full_text}"
            )

            # 5. 发送回复
            if response:
                await self._send(websocket, response)

            # 6. 记录已处理
            self._mark_processed(messages)
            time.sleep(0.5)  # 防抖——避免连续快速响应

    def _drain_pipe(self):
        msgs = []
        while True:
            try:
                msgs.append(self.pipe.get_nowait())
            except Empty:
                break
        return msgs
```

## 六、状态机的条件规则

状态机不是"每 30 秒检查一次"，而是"每个条件到达触发点时才检查"。

```python
class StateMachine:
    def __init__(self, pipe):
        self.pipe = pipe
        self.conditions = [
            MealCondition(),      # 饭点
            WeatherCondition(),   # 天气变化
            SilenceCondition(),   # 长时间沉默
            ReturnCondition(),    # 玩家回归
            MemoryCondition(),    # 记忆回顾
            GoalCondition(),      # 目标驱动：论文进程、社团交接等
            # ... 可扩展
        ]

    def _run(self):
        while not self._stop:
            for cond in self.conditions:
                if cond.should_fire():
                    msg = cond.build_message()
                    self.pipe.put(PipeMessage(
                        source="state_machine",
                        text=msg,
                        priority=cond.priority,
                        timestamp=time.time()
                    ))
                    cond.mark_fired()
            time.sleep(10)  # 最小检查间隔
```

每个 Condition 有：
- `should_fire()` — 检查条件是否满足
- `build_message()` — 生成自然语言消息文本
- `priority` — 消息优先级
- `cooldown` — 冷却时间

## 七、完整的条件列表

| 条件 | 触发场景 | 示例消息 | 优先级 |
|------|---------|---------|--------|
| MealCondition | 早餐/午餐/晚餐时间 | "[饮食提醒] 现在是午餐时间，Monika想提醒玩家按时吃饭。" | 6 |
| WeatherCondition | 天气突变（下雨/降温/台风） | "[天气提醒] 东京下雨了，晾在走廊的鞋该收了。" | 8 |
| SilenceCondition | 玩家2小时+未说话 | "[状态提醒] 玩家已经3小时没说话了，Monika有点想念。" | 7 |
| ReturnCondition | 玩家久别（1h+）后回来 | "[状态提醒] 玩家回来了，Monika想自然地打个招呼。" | 5 |
| MemoryCondition | 随机抽取一条长期记忆 | "[记忆回顾] Monika想起玩家说过很喜欢榴莲披萨。" | 4 |
| GoalCondition | 论文章节约到期、社团交接日临近 | "[论文] 第二章还差3页，Monika下午可能要去图书馆。" | 6 |
| StudyCondition | 上课/论文过程中触发 | "[学习] 刚上完比较文学研讨，讨论了很久叙事结构。" | 3 |
| ClubCondition | 社团活动日、交接进展 | "[社团] 今天桜文会活动，夏树带了抹茶杯子蛋糕。" | 3 |
| DormCondition | 室友互动、宿舍日常 | "[宿舍] 纱世里今天又睡过头了，早饭时间少了一个人。" | 2 |
| FriendshipCondition | 室友关系因事件而演变 | "[关系] 今天和优里在图书馆待了一下午，她推荐了一本恐怖小说。" | 2 |
| PlayerRelationCondition | 玩家关系阶段性变化（初次聊天→熟悉→亲密→依赖） | "[关系] Monika开始意识到自己越来越期待玩家上线了。" | 5 |

其中：

**FriendshipCondition** — 人物关系随着生活事件累积而变化。比如纱世里提到毕业后的不安 → Monika 和她深夜长谈 → 关系更进一步。这个变化影响 future events 的生成。

**PlayerRelationCondition** — Monika 和玩家的关系不是静态的。随着对话次数、情感深度、玩家自我表露的增加，关系从"初步建立"过渡到"熟悉"→"亲密"→"依赖"。这影响 Monika 的语气、主动性和自我表露程度。

## 八、与当前架构的映射

| 当前模块 | 新架构中的位置 |
|---------|--------------|
| `scheduler.py` (30s poll) | StateMachine 主循环 (10s poll) |
| `triggers/time_trigger.py` | MealCondition + SilenceCondition |
| `triggers/weather_trigger.py` | WeatherCondition |
| `triggers/pattern_trigger.py` | ReturnCondition |
| `triggers/memory_trigger.py` | MemoryCondition |
| `triggers/search_trigger.py` | StudyCondition + ClubCondition 的一部分 |
| `triggers/random_trigger.py` | DormCondition |
| `agents/self_model.py` | FriendshipCondition + PlayerRelationCondition（关系数值驱动） |
| `agents/reflection_agent.py` | 关系演变的反馈源 |
| `ws_handler.py` `_proactive_poller` | **删除** — MonikaLoop 统一处理 |
| `ws_handler.py` `_handle_chat` (玩家消息入口) | MonikaLoop._drain_pipe 中的 player 类型 |
| `ws_handler.py` `_build_response` | **保留** — MonikaLoop 调用它 |
| `maica_bridge/server.py` WebSocket serve | MonikaLoop 接管 WebSocket 处理 |

## 八、实施步骤

1. 新建 `maica_reality/state_machine.py` — StateMachine + Conditions
2. 新建 `maica_bridge/pipe_loop.py` — MonikaLoop + PipeMessage + 管道
3. 修改 `maica_bridge/server.py` — 用 MonikaLoop 替代当前的 WS handler
4. 删除 `maica_reality/scheduler.py` + `triggers/`
5. 删除 `maica_bridge/ws_handler.py` 中的 `_proactive_poller`
6. 保留 `_build_response` 和上下文构建逻辑
