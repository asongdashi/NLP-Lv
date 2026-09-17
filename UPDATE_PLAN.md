# MAICA 项目更新方案

> 2026-05-22  
> 包含：已有 Bug 修复 + 语音通话功能

---

## Phase 1：Bug 修复（P0 — 阻塞/崩溃）

### [C1] 删除死端点 `reality_manager` 引用

`http_api.py:135` 导入不存在的 `reality_manager` 模块，`POST /api/push_test` 永远报错。

**修改**：删除 `http_api.py` 中第 135-155 行的 `push_test_message` 路由和 import。

### [C2] Reality `tools.py` 文件路径修正

`_get_my_status` 读 `maica_reality/logs/lifecycle.json`，实际在 `maica_bridge/logs/`。`_search_journal` 同样读错目录。

**修改**：将路径从 `os.path.dirname(__file__)` 改为指向 `maica_bridge/` 的绝对路径。

### [C3] `get_storage()` 传参错误

`Storage("default")` 但 `Storage.__init__()` 不接受参数，调用即崩溃。

**修改**：改为 `Storage()`。

### [C4] 压缩器数据格式修复

`compressor.py` 读 `log.get("periods")`，但生成器产出的 key 是 `"events"`。压缩器完全不工作。

**修改**：`_compress_daily_to_weekly` 改为读 `log.get("events")` 数组并拼接 detail 字段。

### [C5] API Key 脱敏

`config_template.json` 含真实 API Key。

**修改**：全部替换为占位符 `"YOUR_KEY_HERE"`。

---

## Phase 2：Bug 修复（P1 — 特定条件下出错）

### [H1] 删除 `test_reality.py` 中的 `topic_generator` 导入

**修改**：删除第 70 行和对 `generate()` 的调用，或删掉整个测试脚本。

### [H2/H3] 统一 `agents` 模块的 sys.path 注入

Bridge 端导入 reality 的 agents 模块依赖 `_get_proactive_context` 中的 ad-hoc 路径注入。

**修改**：在 bridge `server.py` 启动时统一加 `maica_reality/` 到 sys.path，和 reality 侧对齐。删除 ws_handler.py 中的分散 `sys.path.insert`。

### [H4] `data_sync.py` 文件名修正

同步 `profile/profile.json`，实际文件是 `player_profile.json`。

**修改**：路径改为 `player_profile.json`。

### [H5] `get_rag_manager()` 提升为顶层导入

在 `_add_rag_memory` 中没独立 import，依赖 `_build_response` 先执行。

**修改**：在 `_add_rag_memory` 内加局部 import。

### [H6] `config_template.json` 端口修正

模板默认 `http_port: 6000`，应为 `8080`。

**修改**：改为 `8080`。

---

## Phase 3：Bug 修复（P2 — 代码质量 / 维护）

### [M1] 统一 `tools.py` 和 `deepseek_client.py`

Bridge 和 Reality 各有一份，已经出现 timeout 值不同步。

**修改**：
- Reality 的 `tools.py` 和 `deepseek_client.py` 删除
- Bridge 的 `deepseek_client.py` 统一用 600s timeout（life_gen 需要）
- 修改 Reality `server.py` 的 sys.path 确保导入 bridge 版本

### [M2] 统一 `maica_protocol.py`

Bridge 版有 session 时间戳注入，Reality 版没有。

**修改**：Reality 的 `maica_protocol.py` 同步 bridge 版的时间戳逻辑。

### [M3] 删除 `gatekeeper.py` 死变量 `_LIFE_DATA`

**修改**：删除未使用的 `_LIFE_DATA` 变量定义。

### [M4] 更新 `reset_monika.sh`

`maica_reality/rag/` 路径已失效。

**修改**：删除第 138 行的无效 `rm -f`；第 132 行改为精准删除而非 `*.json` 通配。

### [M5] 删除 `rag/config.py` 重复定义的 `SIMILARITY_THRESHOLD`

**修改**：移除重复行。

### [M6] `iter_lines().decode()` 兼容性

新版 requests 库 `iter_lines()` 返回已解码的 str。

**修改**：加 `isinstance(line, bytes)` 判断。

### [M7] Reality `tools.py` 顶部加 sys.path 防护

依赖 bridge 路径先注入才能导入 rag 模块。

**修改**：在文件顶部加 `sys.path.insert` 兜底。

---

## Phase 4：语音通话（新功能）

> 详细设计见 `VOICE_DESIGN.md` 和 `ARCHITECTURE.md`

### [V1] 新增 `maica_bridge/voice.py`

```python
class VoiceService:
    def __init__(self):
        self.stt = SenseVoice()
        self.tts = ChatTTS()
    def transcribe(self, audio_bytes) -> dict  # STT
    def synthesize(self, text) -> bytes        # TTS
```

### [V2] 新增语音 WebSocket 消息处理

`ws_handler.py` 中 `handle_ws_client` 新增处理：
- `type: "voice_audio"` → STT → handle_query(voice=True)
- `type: "voice_interrupt"` → 打断当前输出

### [V3] 配置新增 `system_prompt_voice_zh`

`config.json` 和 `config_template.json` 新增语音专用提示词：
- 短句风格（2-3 句一个回合）
- 不使用 `[情绪名]` 标签
- 允许被打断后自然衔接

### [V4] `_build_response` 支持 voice 参数

```python
_build_response(session_id, user_msg, is_system=False, voice=False)
```
voice=True 时：
- 使用 `system_prompt_voice_zh`
- 其余逻辑不变（同一函数、同一 LLM 调用、同一存档）

### [V5] I/O 层语音输出

`_handle_chat` 完成后，如果 voice=True，由 I/O 层逐句 TTS 输出。打断时撤回已存档内容。

### [V6] 手机端页面

`maica_bridge/static/voice.html`：
- 录音 + Silero VAD → WebSocket 发送音频
- 接收音频 → 播放
- 通话中隐藏文字输入框

### [V7] 语音模式下暂停 MonikaLoop 推送

MonikaLoop 检测到 VoiceService 活跃状态 → `continue` 休眠。

---

## 执行顺序

```
Phase 1 (P0) → Phase 2 (P1) → Phase 3 (P2) → Phase 4 (Voice)

Phase 1 和 2 应在语音开发前完成，避免在代码库上叠加新功能。
Phase 3 是代码清理，和 Phase 4 可并行。
```

---

## 文件改动清单

| Phase | 文件 | 操作 |
|---|---|---|
| **P0** | `maica_bridge/http_api.py` | 删除 reality_manager 路由 |
| **P0** | `maica_reality/tools.py` | 修正文件路径 |
| **P0** | `maica_bridge/storage/api.py` | `get_storage()` 修复 |
| **P0** | `maica_reality/life/compressor.py` | 修正 events 读取 key |
| **P0** | `maica_bridge/config_template.json` | API Key 脱敏 |
| **P1** | `maica_reality/test_reality.py` | 删除 topic_generator 引用 |
| **P1** | `maica_bridge/server.py` | 加 reality 到 sys.path |
| **P1** | `maica_bridge/ws_handler.py` | 删除分散 sys.path.insert |
| **P1** | `maica_reality/data_sync.py` | 修正 profile 文件名 |
| **P1** | `maica_bridge/ws_handler.py` | _add_rag_memory 独立 import |
| **P1** | `maica_bridge/config_template.json` | 端口 6000→8080 |
| **P2** | `maica_reality/tools.py` | **删除** |
| **P2** | `maica_reality/deepseek_client.py` | **删除** |
| **P2** | `maica_bridge/deepseek_client.py` | timeout → 600s |
| **P2** | `maica_reality/maica_protocol.py` | 同步 bridge 时间戳逻辑 |
| **P2** | `maica_bridge/gatekeeper.py` | 删除 _LIFE_DATA |
| **P2** | `reset_monika.sh` | 修正无效路径 |
| **P2** | `maica_bridge/rag/config.py` | 删除重复 THRESHOLD |
| **P2** | `maica_bridge/deepseek_client.py` | decode() 兼容修复 |
| **V1-V7** | 新增 `maica_bridge/voice.py` | VoiceService |
| **V1-V7** | 新增 `maica_bridge/static/voice.html` | 手机语音页面 |
| **V1-V7** | 修改 `maica_bridge/ws_handler.py` | voice 消息处理 |
| **V1-V7** | 修改 `maica_bridge/config.json` | system_prompt_voice_zh |
| **V1-V7** | 修改 `maica_bridge/pipe_loop.py` | MonikaLoop 语音模式检查 |
