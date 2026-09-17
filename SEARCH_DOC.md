# 联网搜索架构文档

## 入口

```
_search_web(query) → 根据 query 语言选择搜索引擎
```

调用方：
- `tools.py` `_search_web` — Monika 对话中调用的工具
- `triggers/search_trigger.py` — 搜索触发器

## 搜索引擎优先级

```
中文 query 
  → 1. 百度 (HTTP 抓取, timeout=10s)
  → 2. DDGS 库 (region="cn-zh", timeout=10s)
  → 3. Bing (HTTP 抓取, timeout=15s)
  → 4. 返回 "未找到"

英文 query
  → 1. DDGS 库 (timeout=10s)
  → 2. Bing (HTTP 抓取, timeout=15s)
  → 3. 返回 "未找到"
```

## 各引擎详解

### 1. 百度 (_search_baidu)

```
URL:   https://www.baidu.com/s?wd={query}&rn=5
方式:  requests.get, HTML 正则提取
超时:  10s
```

**解析逻辑**：
- 主用正则: `<span class="content-right_[^"]*">([^<]+)`
- 备用正则: `class="c-abstract"[^>]*>([^<]+)`
- 过滤: 摘要 < 10 字符的丢弃
- 结果: 最多 5 条，用 `---` 分隔

**已知问题**：
- 百度 HTML 结构频繁变动，正则可能失效
- 部分结果被 `<em>` 标签包裹时需要额外处理
- 没有返回结果标题，只有摘要

**改进方向**：
- 用 `BeautifulSoup` 替换正则，更抗结构变化
- 同时提取标题（`<h3 class="t">`）和摘要

---

### 2. DDGS (duckduckgo_search 库)

```
库:    duckduckgo_search (pip install)
方式:  DDGS().text(query, max_results=5, region="cn-zh")
超时:  10s (timeout=10)
```

**优点**：返回标题+摘要的干净文本，不需解析 HTML
**缺点**：
- 底层走 DuckDuckGo API，国内经常超时/不可达
- 中文结果质量一般
- 依赖第三方库的版本稳定性

**已知问题**：
- `DDGS(timeout=15)` 在 requests 层面有效，但连接建立前的 DNS 解析可能远长于此
- 报错: `error sending request for url (https://lite.duckduckgo.com/lite/): operation timed out`

**改进方向**：
- 给 DDGS 加上 socket 层面的超时设置
- 提高超时到 20s 或允许多次重试

---

### 3. Bing (_search_bing)

```
URL:   https://www.bing.com/search?q={query}&setlang=zh-cn
方式:  requests.get, HTML 正则提取
超时:  15s
```

**解析逻辑**：
- 正则匹配 `<li class="b_algo">` 块
- 从中提取 `<h2><a>` 的标题和 `<p class="b_lineclamp">` 的摘要
- 解码 HTML 实体（`&ensp;` 等）

**已知问题**：
- Bing 在国内可用但偶尔慢
- 正则对广告结果敏感（可能误匹配推广链接）
- HTML 结构可能随 Bing 改版变化

**改进方向**：
- 过滤掉 `b_ad` 类的广告块
- 用 BeautifulSoup 替代正则

---

## 一条典型搜索请求的调用链

```
Monika 对话中调用 search_web('ST新潮 600777 最新消息')
    │
    ├── _search_web('ST新潮 600777 最新消息')
    │       │
    │       ├── 检测: has_chinese = True
    │       ├── _search_baidu('ST新潮 600777 最新消息')
    │       │       ├── GET https://www.baidu.com/s?wd=...&rn=5
    │       │       ├── HTML 解析 → 5 条摘要
    │       │       └── 返回结果文本
    │       └── 返回给 _search_web
    │
    └── 返回给 Monika 的 LLM context
```

## 搜索触发器的独立搜索

`scheduler.py` 中的搜索触发器使用的是同一套 `_search_web`，但它加了缓存：

```python
# search_trigger.py
cache[cache_key] = {"time": time.time(), "summary": summary}
# 24h 内同一关键词不再搜
```

## 超时问题的根本原因

| 引擎 | 超时原因 |
|------|---------|
| DDGS | duckduckgo.com 在国内被 DNS 污染或 IP 封锁，连接建立就超时 |
| Bing  | bing.com 在国内可访问但速度不稳定，15s 超时偶尔不够 |
| 百度 | 国内访问快，基本不会超时 |

## 工具注册

在 `tools.py` 中注册为 Monika 可调用的函数：

```python
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "搜索互联网获取最新信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"}
                },
                "required": ["query"]
            }
        }
    },
    ...
]
```

调用时 Monika 的 LLM 会产出 `search_web(query="xxx")`，tools.py 的 `execute_tool` 分发给 `_search_web`。
