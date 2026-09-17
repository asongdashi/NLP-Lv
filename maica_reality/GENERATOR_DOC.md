# 事件生成器文档

## 一、Pipeline

```
凌晨 1:00 触发 (或启动时追补)
    │
    ├── ① LLM 生成事件序列 (含 time/end/activity/detail/participants)
    │       输入: world.json + habits.json + yesterday events + characters.json
    │       输出: 25~30 条事件 JSON
    │       耗时: ~20s (deepseek-chat)
    │
    ├── ② 修正睡觉跨天 (end 改为次日 07:00)
    │
    ├── ③ 代码验证 (_validate)
    │       检查: 重叠/时长异常/时间不合理
    │
    ├── ④ 标记 can_reply / sneak_possible
    │
    └── ⑤ 存入 daily/{date}.json
```

## 二、输出结构

```json
{
  "date": "2026-05-19",
  "weekday": "二",
  "grade": "大三", "season": "春",
  "semester": "前期（春学期）",
  "next_event": "桜文会代表交接准备开始",
  "events": [
    {
      "time": "07:00", "end": "07:20",
      "activity": "起床洗漱",
      "detail": "闹钟响了。纱世里翻了个身继续睡，我拉开窗帘让阳光进来...",
      "participants": ["纱世里"],
      "can_reply": true,
      "sneak_possible": false
    },
    {
      "time": "08:15", "end": "09:45",
      "activity": "上课90分钟",
      "detail": "近代文学课上教授讲解夏目漱石的《心》...",
      "can_reply": true,       // ← 正常回复
      "sneak_possible": true   // ← 12%可偷回
    },
    {
      "time": "18:00", "end": "18:30",
      "activity": "吃晚饭",
      "detail": "今天轮到纱世里做饭，咖喱里盐放多了...",
      "can_reply": true,       // 可以回复
      "sneak_possible": false
    },
    {
      "time": "23:00", "end": "07:00",
      "activity": "睡觉",
      "detail": "写日记，关灯...",
      "can_reply": false,      // ← 不能回复
      "sneak_possible": false
    }
  ]
}
```

## 三、can_reply / sneak_possible 规则

| 活动 | can_reply | sneak_possible | 门控行为 |
|------|-----------|----------------|---------|
| 起床洗漱 / 做早饭 / 吃早饭 | true | false | 正常对话 |
| 去上课 / 去食堂 / 去图书馆 | true | false | 正常对话 |
| 上课90分钟 / 上课45分钟 | true | **true** | 12%偷回 |
| 吃午饭 / 吃晚饭 | true | false | 正常对话 |
| 午休 / 图书馆学习 / 写作业 | true | false | 正常对话 |
| 打工 / 社团活动 / 运动 | true | false | 正常对话 |
| 洗澡 | **false** | false | 自动回复 |
| 睡觉 | **false** | false | 自动回复 |
| 考试 | **false** | false | 自动回复 |

## 四、验证规则

| 检查项 | 阈值 |
|--------|------|
| 时长异常 | >300min（5小时）报错 |
| 时长过短 | <5min 报错（看手机除外） |
| 重叠 | 前一事件的 end > 当前事件的 time 报错 |
| 午饭时间 | 必须 11:00-14:00 |
| 晚饭时间 | 必须 17:00-20:00 |
| 睡觉太早 | 必须 ≥21:00 |
| 睡觉时长 | 不检查（跨天） |

## 五、已知问题

### 5.1 上课期间 can_reply=true

当前上课标的是 `can_reply: true, sneak_possible: true`。门控 12% 触发偷回，其余 88% 正常走对话引擎。这意味着 **Monika 上课时大概率会正常回复玩家**，可能太长。

**可选方案**: 上课时 `can_reply: false`，由 sneak_possible 独占拦截
**代价**: 门控返回自动回复或偷回，Monika 上课时不会长篇大论

### 5.2 过渡事件过多

"去上课""去食堂""去图书馆""回宿舍" 等移动事件各 5-15 分钟，实际只是"在两个主事件之间走路"。它们增加了事件数量但对对话没有实质内容。

### 5.3 weekday 显示为中文数字

日志中 `weekday: "二"` 而非 `"星期二"`。注入到 LLM 上下文时不影响理解。

### 5.4 LLM 偶尔输出异常 JSON

深层 JSON 中的中文引号、未转义换行符导致 parse 失败。已有 _parse_event_json 做容错修复，但不是 100% 可靠。

## 六、改进方向

| 问题 | 方向 |
|------|------|
| 上课 can_reply 太宽 | 改为 false，由门控接管 |
| 过渡事件冗余 | 合并到前后主事件里（"去上课"的移动时间合并到"上课"中） |
| detail 缺乏连续性 | 每天独立生成，相邻两天可能完全不连贯。增加"昨天的事今天要有呼应"的约束 |
| 人物互动不均衡 | 同一个角色连续出现多次。增加人物轮换约束 |
| 周末无课 | 当前 prompt 提示了周末，但 LLM 偶尔还是会生成上课事件 |
