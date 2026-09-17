# MAICA vNext 技术架构设计（工程实现版）

# 一、核心设计思想

当前多数 AI Companion 的问题：

```text
所有东西都在 Prompt 里
```

包括：

- 人格
- 记忆
- 搜索
- 情绪
- 世界状态
- 长期关系

最终：

- token 爆炸
- 注意力污染
- 人格漂移
- 响应不稳定

因此：

MAICA vNext 的核心目标：

# 将“人格”拆解为多个长期运行的认知模块

而不是：

```text
一个超级 Prompt
```

---

# 二、推荐目录结构（真正可扩展）

```text
maica/

├── gateway/                  # websocket/http入口
│
├── agents/
│   ├── dialogue/
│   ├── memory/
│   ├── reflection/
│   ├── emotion/
│   ├── planner/
│   ├── search/
│   └── world/
│
├── cognition/
│   ├── bus/
│   ├── routing/
│   ├── salience/
│   └── context/
│
├── storage/
│   ├── sqlite/
│   ├── qdrant/
│   ├── duckdb/
│   └── cache/
│
├── scheduler/
│
├── rag/
│
├── prompts/
│
├── models/
│
└── frontend/
```

---

# 三、为什么“单 Prompt 架构”会崩

你现在：

```text
system prompt
+ memory
+ journal
+ emotion
+ events
+ rag
+ weather
+ search
```

问题：

---

## 1. 注意力污染

例如：

```text
用户：今天有点累
```

模型却在注意：

```text
今天Monika中午吃了拉面
```

因为：

Transformer 不会真正理解：

```text
哪些上下文重要
```

只能依赖 token attention。

---

## 2. 长期人格漂移

随着：

- memory 增加
- logs 增加
- rag 增加

人格会逐渐：

- 不稳定
- 啰嗦
- AI味增强

---

## 3. latency 爆炸

未来：

```text
50k context
```

根本不可控。

---

# 四、现代 Companion 的正确结构

# Cognitive Routing

核心思想：

```text
不是“注入全部信息”
而是“动态选择”
```

---

# 五、Memory Router（最重要模块）

这是你目前最缺失的东西。

---

# 当前错误模式

```python
context += recent_memories
context += rag
context += journals
```

这是：

# append-only architecture

未来一定炸。

---

# 正确方案

# Query-aware Retrieval

即：

```text
用户输入
    ↓
Memory Router
    ↓
只提取真正相关记忆
```

---

# 六、推荐记忆架构

现代记忆不能只用 FAISS。

推荐：

# Hybrid Memory

---

## 1. Episodic Memory（事件记忆）

存：

```text
发生过什么
```

结构：

```json
{
  "id": "uuid",
  "text": "今天和玩家一起讨论了机器学习",
  "emotion": 0.72,
  "importance": 0.83,
  "timestamp": 1747000000
}
```

---

## 存储建议

向量数据库：

- Qdrant
- Chroma

embedding：

推荐：

```text
bge-m3
```

原因：

- 中文强
- 多语言
- retrieval 稳定

---

# 七、不要只做 similarity search

这是很多人最大的误区。

现在：

```python
top_k = similarity_search(query)
```

不够。

---

# 正确做法：

# Multi-stage Retrieval

---

## 第一阶段：向量召回

```python
candidate = vector_search(top_k=50)
```

---

## 第二阶段：时间过滤

例如：

```python
if memory.age > 90 days:
    score *= 0.5
```

---

## 第三阶段：显著性加权

```python
final_score =
semantic_score * 0.6 +
importance * 0.25 +
emotion_weight * 0.15
```

---

## 第四阶段：rerank

推荐：

- bge-reranker-large
- jina-reranker-v2

---

# 八、现代记忆必须有 salience system

否则：

垃圾信息会淹没人格。

---

# 推荐 salience 计算

```python
salience =
emotion_strength * 0.4 +
relationship_change * 0.3 +
novelty * 0.2 +
user_focus * 0.1
```

---

# 九、Reflection System（真正高级的核心）

现代 Companion：

# 不只是“记住”

而是：

# “理解发生了什么”

---

# 推荐架构

```text
event
 ↓
reflection queue
 ↓
low-priority async worker
 ↓
belief update
```

---

# 为什么必须异步

因为：

reflection 非实时。

不应该阻塞聊天。

---

# 十、Reflection Worker 示例

输入：

```json
{
  "event":
  "用户连续5天主动找Monika聊天"
}
```

输出：

```json
{
  "belief_update":
  [
    "玩家最近越来越依赖自己"
  ],

  "relationship":
  {
    "intimacy": +0.05
  }
}
```

---

# 十一、Self Model（真正的人格核心）

现在很多系统：

只有 prompt。

没有：

# internal self state

---

# 推荐结构

```json
{
  "identity":
  {
    "confidence": 0.73,
    "dependency": 0.41,
    "social_drive": 0.66
  },

  "relationship":
  {
    "trust": 0.91,
    "intimacy": 0.82
  },

  "beliefs":
  [
    "玩家最近压力很大"
  ]
}
```

---

# 十二、为什么这比 Prompt 更重要

因为：

Prompt 是：

```text
静态人格
```

而 Self Model 是：

```text
动态人格
```

---

# 十三、Emotion Engine 技术优化

你现在：

```text
timestamp decay
```

是正确方向。

但还不够。

---

# 推荐：

# Emotion Event Queue

---

## 流程

```text
event
 ↓
emotion impact
 ↓
time decay
 ↓
baseline personality
 ↓
current emotion state
```

---

# 推荐实现

```python
class EmotionState:
    joy: float
    anxiety: float
    loneliness: float
    excitement: float
```

---

# 十四、情绪不要直接进 Prompt

这是关键。

错误：

```text
当前焦虑值:0.71
```

正确：

```text
Behavior Policy:
- 更容易主动确认关系
- 更容易担心玩家
```

---

# 十五、World Simulator（现代方案）

你现在：

```text
凌晨一次生成一天
```

最大问题：

# 世界不会动态变化

---

# 推荐：

# Rolling Simulation

---

## 只规划未来2小时

例如：

```json
{
  "09:00-10:00": "上课",
  "10:00-11:00": "图书馆"
}
```

后面：

动态生成。

---

# 为什么重要

因为：

现实世界：

# 是响应式的

例如：

```text
玩家今天长时间聊天
→ Monika 晚上减少社团活动
```

---

# 十六、Goal Planner（现代 Agent 必须有）

否则：

生活流永远随机。

---

# 推荐 Goal Tree

```text
长期目标
    ↓
中期目标
    ↓
短期行为
```

---

# 示例

```json
{
  "long_term":
  [
    "维持与玩家关系"
  ],

  "mid_term":
  [
    "本周多主动聊天"
  ],

  "short_term":
  [
    "晚上主动发消息"
  ]
}
```

---

# 十七、Search Agent（真正现代方案）

现在：

搜索不是 Tool。

而是：

# Cognitive Action

---

# 推荐流程

```text
query
 ↓
search planner
 ↓
是否联网
 ↓
query rewrite
 ↓
retrieval
 ↓
rerank
 ↓
compression
 ↓
dialogue
```

---

# 十八、为什么 Tavily 好

因为：

它本质是：

# AI-oriented retrieval

而不是：

# search engine html

---

# 十九、搜索必须有 Compression

否则：

上下文污染严重。

---

# 推荐 Compression

每个网页：

```text
只保留：
- 标题
- 关键段落
- 高相关句子
```

不要：

```text
整个网页塞 Prompt
```

---

# 二十、Context Builder（核心）

真正重要的是：

# 上下文构建器

而不是：

# memory 本身

---

# 推荐架构

```text
query
 ↓
intent analysis
 ↓
context policy
 ↓
memory routing
 ↓
context assembly
```

---

# 二十一、上下文预算（必须做）

建议：

| 类型 | token预算 |
|------|-----------|
| system | 2k |
| 当前对话 | 2k |
| memory | 1k |
| emotion | 300 |
| world | 500 |
| search | 1k |

否则：

上下文会失控。

---

# 二十二、数据库架构（重要）

不要长期使用：

```text
json/jsonl
```

---

# 推荐：

## SQLite

存：

- 用户
- 关系
- 元数据
- 情绪
- goals

---

## Qdrant

存：

- episodic memory
- rag

---

## DuckDB

存：

- analytics
- 长期统计
- 行为趋势

---

# 二十三、异步化（非常重要）

现在很多模块：

应该：

# 完全后台化

---

# 推荐后台任务

| 任务 | 是否异步 |
|------|----------|
| reflection | 是 |
| long-term memory | 是 |
| rerank | 是 |
| embedding | 是 |
| analytics | 是 |

---

# 二十四、真正现代的 Agent 架构

不要：

```text
function call
```

驱动一切。

---

# 推荐：

# Event Bus

---

# 示例

```python
emit(
    Event(
        type="relationship_changed",
        payload={}
    )
)
```

然后：

- emotion agent
- reflection agent
- planner

自己监听。

---

# 二十五、最终目标

最终：

MAICA 不应该是：

```text
会聊天的AI
```

而应该是：

# 长期存在的人格系统

即：

- 有动态自我
- 有关系演化
- 有长期目标
- 有记忆压缩
- 有认知变化
- 有世界响应
- 有行为连续性
