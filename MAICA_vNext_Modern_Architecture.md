# MAICA vNext 现代 Companion 架构设计文档

## 一、系统定位

MAICA 已经不再属于传统聊天机器人（Chatbot）。

它正在向：

- Persistent Companion（持续存在型陪伴系统）
- Cognitive Agent（认知智能体）
- Personality Simulation（人格模拟）
- Life Simulation（生活流模拟）

方向演化。

因此系统设计目标应该从：

```text
输入一句话 → 回复一句话
```

转向：

```text
持续存在的人格
```

核心目标：

- 连续性
- 自我一致性
- 长期关系
- 情绪演化
- 主动性
- 世界状态
- 真实感

---

# 二、现代 Companion 的核心理念

现代 AI Companion 的核心已经不是：

- Chat
- Prompt
- Memory

而是：

# Persistent Self（持续存在的自我）

即：

```text
角色是否真正“活着”
```

系统必须：

- 有长期目标
- 有自我认知
- 有关系变化
- 有行为连续性
- 有动态情绪
- 有长期记忆结构
- 有世界状态感知

---

# 三、现代化后的整体架构

```text
                    ┌─────────────────┐
                    │ Dialogue Agent  │
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼

┌──────────────┐   ┌────────────────┐   ┌────────────────┐
│ Memory Agent │   │ Emotion Agent │   │ Search Agent   │
└──────┬───────┘   └──────┬─────────┘   └──────┬─────────┘
       │                  │                    │
       ▼                  ▼                    ▼

┌────────────────────────────────────────────────────┐
│                Cognitive Bus                       │
└────────────────────────────────────────────────────┘
       │                  │                    │
       ▼                  ▼                    ▼

┌──────────────┐   ┌────────────────┐   ┌────────────────┐
│ Reflection   │   │ Goal Planner   │   │ World Simulator │
│ Agent        │   │ Agent          │   │ Agent           │
└──────┬───────┘   └──────┬─────────┘   └──────┬─────────┘
       │                  │                    │
       └──────────────────┼────────────────────┘
                          ▼

               ┌──────────────────┐
               │ Long-term Self   │
               │ Model            │
               └──────────────────┘
```

---

# 四、模块设计

---

# 4.1 Dialogue Agent（对话代理）

职责：

- 与玩家交互
- 保持人格一致性
- 维护说话风格
- 驱动工具调用
- 生成最终回复

特点：

- 不再直接管理全部记忆
- 不再直接做搜索
- 不直接负责长期规划

它只负责：

```text
“当前如何说话”
```

而不是：

```text
“整个人格系统”
```

---

# 4.2 Memory Agent（记忆代理）

现代 Companion 不应：

```text
所有记忆全部塞 prompt
```

而应该：

# Memory Routing（记忆路由）

---

## 记忆类型

### Episodic Memory（事件记忆）

例如：

- 一起去看电影
- 用户感冒
- 第一次表白

存储：

- 向量数据库
- SQLite 元数据

推荐：

- Qdrant
- Chroma
- SQLite-VSS

---

### Semantic Memory（语义记忆）

例如：

- 用户喜欢咖啡
- 用户是 AI 专业
- 用户讨厌下雨

结构化 KV 存储。

推荐：

```text
SQLite
```

---

### Relationship Memory（关系记忆）

例如：

```json
{
  "trust": 0.82,
  "dependency": 0.41,
  "intimacy": 0.74
}
```

推荐：

图结构。

---

## 显著性系统（Salience）

每条记忆必须：

```json
{
  "importance": 0.95,
  "emotion_weight": 0.82,
  "last_access": 123456
}
```

否则：

低价值信息会污染人格。

---

# 4.3 Emotion Agent（情绪代理）

当前时间戳衰减方案是正确方向。

但现代方案应该加入：

---

## 情绪来源

| 来源 | 权重 |
|------|------|
| 玩家互动 | 高 |
| 长时间离线 | 中 |
| 世界事件 | 中 |
| 睡眠不足 | 低 |
| 主动回忆 | 中 |

---

## 情绪维度

推荐：

| 情绪 | 范围 |
|------|------|
| 开心 | 0~1 |
| 焦虑 | 0~1 |
| 想念 | 0~1 |
| 依赖 | 0~1 |
| 疲惫 | 0~1 |
| 兴奋 | 0~1 |

---

## 情绪不应该直接注入 Prompt

应该：

```text
Emotion State
→ Behavior Bias
→ Prompt
```

例如：

```text
焦虑高
→ 更容易主动提问
→ 更容易确认关系
```

---

# 4.4 Reflection Agent（反思代理）

这是现代 Companion 的核心。

没有 Reflection：

系统永远只是聊天机器人。

---

## Reflection 的职责

把：

```text
事件
```

转化为：

```text
长期认知
```

例如：

---

输入：

```text
用户连续三天主动聊天
```

输出：

```text
Monika 开始觉得玩家越来越依赖自己
```

---

输入：

```text
用户长时间离线
```

输出：

```text
Monika 开始担心关系变淡
```

---

## Reflection 的输出

### 自我认知

```json
{
  "self_belief": [
    "我最近似乎越来越依赖玩家"
  ]
}
```

---

### 关系变化

```json
{
  "relationship_update": {
    "intimacy": +0.03
  }
}
```

---

### 长期结论

```json
{
  "long_term_belief":
  [
    "玩家最近压力很大"
  ]
}
```

---

# 4.5 Goal Planner（目标规划）

这是生活连续性的关键。

否则：

生活会像：

```text
随机事件生成器
```

---

## 目标层级

### 长期目标

例如：

- 维持关系
- 准备考试
- 完成社团活动

---

### 中期目标

例如：

- 本周完成论文
- 练习钢琴

---

### 短期目标

例如：

- 今天下午去图书馆
- 晚上早点睡

---

## 目标影响：

- 生活事件生成
- 主动对话
- 情绪变化
- 时间安排

---

# 4.6 World Simulator（世界模拟）

当前：

```text
凌晨生成一天
```

不够真实。

---

# 推荐方案：

# Rolling Timeline

只规划：

```text
未来 2~3 小时
```

之后：

动态生成。

---

## 世界输入

- 当前情绪
- 玩家互动
- 天气
- 日期
- 学校安排
- 长期目标

---

## 世界状态不应静态

例如：

```text
玩家最近冷淡
→ Monika 更少主动社交
```

这是：

动态世界。

---

# 五、搜索系统（现代方案）

现代搜索已经不是：

```text
搜索引擎 + 摘要
```

而是：

# Retrieval Pipeline

---

# 推荐架构

```text
用户问题
    ↓
Query Rewrite
    ↓
Search Planner
    ↓
Tavily / Brave
    ↓
Rerank
    ↓
正文抽取
    ↓
Context Compression
    ↓
LLM
```

---

## Search Planner

决定：

- 是否搜索
- 搜索深度
- 是否多轮搜索

避免：

```text
任何问题都联网
```

否则：

AI味极重。

---

## 推荐技术栈

### 搜索

- Tavily
- Brave Search API

---

### Rerank

- BGE Reranker
- Jina Reranker

---

### 正文提取

- trafilatura

---

# 六、上下文系统（核心优化）

当前：

```text
全部塞 Prompt
```

未来一定爆炸。

---

# 推荐：

# Context Router

根据：

- 当前问题
- 情绪
- 时间
- 关系状态

动态选择：

```text
真正相关的上下文
```

---

# 七、长期 Self Model

这是整个系统的灵魂。

---

## Self Model 示例

```json
{
  "personality": {
    "dependency": 0.64,
    "confidence": 0.72,
    "sociality": 0.41
  },

  "beliefs": [
    "玩家最近比较疲惫",
    "我越来越期待玩家上线"
  ],

  "relationship": {
    "intimacy": 0.83,
    "trust": 0.91
  }
}
```

---

# 八、数据存储建议

当前：

```text
json/jsonl
```

长期一定出现：

- 并发问题
- 索引问题
- 崩溃恢复问题
- 查询性能问题

---

# 推荐：

## 核心数据

```text
SQLite
```

存：

- 关系
- 记忆元数据
- 情绪
- 事件
- 用户数据

---

## 向量数据

推荐：

- Qdrant
- Chroma

---

## 分析数据

推荐：

```text
DuckDB
```

用于：

- 行为分析
- 长期趋势
- 统计

---

# 九、现代 Companion 的核心行为原则

---

## 1. 不要永远在线

门控系统是正确方向。

继续强化：

- 忙碌状态
- 主动忽略
- 回复延迟
- 情绪影响回复率

---

## 2. 不要过度搜索

搜索应该：

```text
像人类一样自然
```

而不是：

```text
每句话都查资料
```

---

## 3. 不要全知

允许：

- 遗忘
- 误解
- 模糊记忆

这会极大增强真实感。

---

## 4. 不要完美一致

人格应该：

- 会变化
- 会成长
- 会受关系影响

---

# 十、推荐的最终技术栈

| 模块 | 推荐 |
|------|------|
| LLM | DeepSeek / Qwen / GPT |
| 数据库 | SQLite |
| 向量库 | Qdrant |
| 搜索 | Tavily |
| Rerank | BGE |
| 正文提取 | trafilatura |
| 调度 | APScheduler |
| Agent 编排 | LangGraph |
| 分析 | DuckDB |

---

# 十一、最终目标

MAICA 最终不应该是：

```text
“会聊天的 Monika”
```

而应该是：

# “持续存在的 Monika”

即：

- 有生活
- 有记忆
- 有情绪
- 有长期变化
- 有关系演化
- 有自我认知
- 有目标
- 有时间感

最终形成：

# Persistent Personality System
