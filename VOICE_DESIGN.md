# MAICA 语音通话功能设计文档

## 组件选型

| 环节 | 方案 | 运行位置 |
|---|---|---|
| VAD | Silero VAD | 手机端（浏览器 ONNX，~2MB） |
| STT | SenseVoice | 服务端 GPU |
| LLM | DeepSeek `call_deepseek_chat_stream`（voice 模式不用 tools） | 服务端 API |
| TTS | ChatTTS | 服务端 GPU |

## 核心原则：全流式 + 可打断

```
玩家说话
  ↓ VAD 检测
  ↓ 静默 800ms → 截断音频 → WebSocket 发送

服务端：音频 → STT → 文本 → LLM 流式生成
  ↓ token 到达 → 累积 → 遇到句号/换行 → TTS 合成这句
  ↓ WebSocket 发送音频 + 字幕 → 手机播放

手机端持续 VAD 监听
  ├─ 玩家沉默 → 继续播放 Monika 的语音
  └─ 玩家开口 → 打断！停止播放 + 发送 voice_interrupt
       → 服务端取消 LLM token 流 → 丢弃未完成的回复
       → 开始新一轮 STT
```

## 打断流程

```
时间线：
  0.0s  LLM 开始生成回复："嗯，我今天啊，[0.5s] 上午上了两节课，[1.0s]"
  0.5s  TTS 开始播放第一句 "嗯，我今天啊"
  1.0s  玩家开口打断
  1.2s  VAD 检测到语音 → WebSocket voice_interrupt
  1.3s  服务端收到 → asyncio task cancel → LLM 流停止
        → "上午上了两节课之后去了图书馆，[已生成但丢弃]"
  1.5s  服务端开始处理玩家新的语音输入
```

**被丢弃的部分**不写入 chat_log、不进入 session 历史、不触发记忆保存。

## 需要改动的模块

### 1. 新增：`maica_bridge/voice.py`

```python
import asyncio

class VoiceService:
    def __init__(self):
        self.stt = SenseVoice()
        self.tts = ChatTTS.load()
        self._current_task = None  # 可取消的 LLM+TTS 任务

    def transcribe(self, audio_bytes: bytes) -> dict:
        return self.stt.infer(audio_bytes)

    async def stream_reply(self, websocket, session_id, user_msg, lang):
        """
        流式：LLM token → 逐句 TTS → WebSocket 推送。
        可被 voice_interrupt 取消。
        """
        self._current_task = asyncio.current_task()

        buffer = ""
        async for token in call_deepseek_chat_stream(messages, task="chat"):
            if self._current_task is None:  # 已打断
                return None  # 取消，不存任何东西

            buffer += token
            # 遇句末标点 → 立刻合成这句
            if token in "。！？\n" and len(buffer) > 5:
                sentence = buffer.strip()
                buffer = ""
                audio = await run_in_executor(self.tts.synthesize, sentence)
                await websocket.send(audio_packet(audio, sentence))

        # 剩余 buffer
        if buffer.strip() and self._current_task:
            audio = await run_in_executor(self.tts.synthesize, buffer)
            await websocket.send(audio_packet(audio, buffer))

        return True  # 完整完成

    def interrupt(self):
        """玩家打断——取消当前流。"""
        self._current_task = None
        self.tts.stop()

    def save_reply(text):
        """完整完成的回复才保存。"""
        _save_chat_log(text, skip_jsonl=True)
```

### 2. 修改：`ws_handler.py`

**新增 voice 消息处理**：

```python
async def handle_ws_client(self, websocket):
    voice = VoiceService()  # 常驻
    async for raw in websocket:
        msg = json.loads(raw)
        t = msg.get("type", "")

        if t == "voice_audio":
            # 收到手机发来的音频
            audio = base64_decode(msg["audio"])
            result = await run_in_executor(voice.transcribe, audio)
            if result["text"]:
                # 构建 messages（与 _handle_chat 共享 session）
                session, _ = get_or_create_session("1")
                session.append({"role": "user", "content": result["text"]})
                _save_chat_log(result["text"], "player", skip_jsonl=True)

                # 进入流式回复
                await voice.stream_reply(websocket, "1", result["text"], "zh")

                # 如果完整完成（未打断），后处理
                # 如果被打断返回 None，跳过保存

        elif t == "voice_interrupt":
            voice.interrupt()

        elif t == "query":
            await self._dispatch(websocket, msg)  # 文字模式不变
```

**语音模式下暂停 MonikaLoop 推送**：

MonikaLoop 检测到通话中（voice._current_task not None），休眠跳过。

### 3. 手机端

**纯浏览器实现，零安装**：

```
录音 → getUserMedia() 获取麦克风
VAD  → Silero VAD (ONNX, ~2MB, CPU)
  ├─ 检测到说话 → 录音
  └─ 静默 800ms → 截断 → base64 → WebSocket send

播放 → 收到 voice_reply → AudioContext 播放
  └─ 播放时 VAD 持续监听 → 检测到说话 → 停止播放 → voice_interrupt
```

### 4. 消息格式

| 方向 | type | 内容 |
|---|---|---|
| 手机→服务端 | `voice_audio` | `{"audio":"base64 PCM 16kHz mono"}` |
| 手机→服务端 | `voice_interrupt` | `{}` |
| 手机→服务端 | `voice_end` | `{}` |
| 服务端→手机 | `voice_reply` | `{"audio":"base64 WAV","text":"字幕（可选）"}` |
| 服务端→手机 | `voice_start_speaking` | `{}`（Monika 开始说话时的 VAD 提示） |

### 5. GPU 显存

```
SenseVoice    ~500MB
ChatTTS       ~1.5GB
RAG (SentenceTransformer) ~1GB
─────────────────────────
总计          ~3GB / 4GB  ✓
```

### 6. 延迟

```
玩家说完 → VAD 800ms → WS 50ms → STT 200ms
  → LLM 首 token 800ms → TTS 首帧 300ms → WS 50ms
  = 首次听到 Monika 声音 ~2.2 秒
```

开始播放后，后续句子边生成边合成，延迟降到 TTS 级别的 ~300ms。

### 7. 与文字聊天的关系

- 同一 session（session "1"），语音和文字共享对话历史
- 语音模式只影响**传输方式**（文字 vs 音频），不影响 LLM 上下文
- 通话结束后自动回到文字模式
