"""
WebSocket 消息处理模块

MAICABridge 类负责：
- 接收并解析 MAICA 前端的 WebSocket 消息
- 通过 RAG 检索增强上下文
- 转发给 Deepseek API
- 将响应按 MAICA 协议格式发回
- 对话结束后追加长期记忆
"""

import json
import os
import re
import asyncio
import traceback

from config import DEEPSEEK_MODEL, logger
from config import ENABLE_THINKING, REASONING_EFFORT, ENABLE_HEALTH_SYNC, ENABLE_HARMONYOS
from deepseek_client import call_deepseek_chat_stream, call_deepseek_with_tools
from tools import TOOLS, set_current_session
from rag.profile_manager import profile_to_prompt
from rag.journal_manager import add_entry as add_journal_entry
# ── 外系统交互 (独立进程，HTTP 通信) ──
REALITY_API = "http://127.0.0.1:6101"
_last_player_chat_time = 0


def _get_character_context(user_msg):
    """根据用户消息中提及的人物名，返回该人物的细节描述。"""
    try:
        import json, os
        chars_path = os.path.join(os.path.dirname(__file__),
                                   "..", "maica_reality", "data", "life", "characters.json")
        if not os.path.exists(chars_path):
            return ""
        with open(chars_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cast = data.get("登场人物", [])
        contexts = []
        for c in cast:
            name = c.get("名字", "")
            if name and name in user_msg:
                identity = c.get("身份", "")
                personality = c.get("性格", {})
                surface = personality.get("表面", "") if isinstance(personality, dict) else ""
                speech = c.get("说话方式", "")
                relation = c.get(f"和Monika的关系", {})
                rel_now = relation.get("现在", "") if isinstance(relation, dict) else ""
                parts = [f"{name}: {identity}。{surface}. {speech}"]
                if rel_now:
                    parts.append(f"和你的关系: {rel_now}")
                contexts.append("。".join(parts))
        return "\n".join(contexts[:2]) if contexts else ""
    except Exception:
        return ""


def _event_age_hours(event_text):
    """从事件文本 '[08:00-09:30] 上课: ...' 提取时间，计算距今小时数。"""
    import re
    m = re.match(r'\[(\d{2}:\d{2})', event_text)
    if m:
        h, mi = map(int, m.group(1).split(":"))
        now = __import__("datetime").datetime.now()
        event_min = h * 60 + mi
        now_min = now.hour * 60 + now.minute
        return (now_min - event_min) / 60
    return 0


def _save_chat_log(text, who="monika", skip_jsonl=False):
    """每条消息存入 SQLite，JSONL 由前端 POST /api/chat_log 负责（在线时跳过避免双写）。"""
    try:
        import json, os
        from datetime import datetime
        # SQLite（始终写入）
        from storage.api import Storage
        Storage().save_chat_message(who, text)
        if skip_jsonl:
            return
        # JSONL（仅离线时服务端写，在线由前端 POST）
        today = datetime.now().strftime("%Y-%m-%d")
        log_dir = os.path.join(os.path.dirname(__file__), "data", "chat_logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"{today}.jsonl")
        entry = {"time": datetime.now().strftime("%H:%M"), "who": who, "text": text}
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _fetch_pending():
    """从外系统 HTTP 拉取待投递消息 + 情绪快照。"""
    try:
        import requests
        resp = requests.get(f"{REALITY_API}/api/pending", timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            msgs = data.get("messages", [])
            if msgs:
                logger.debug(f"[FETCH] Got {len(msgs)} message(s) from reality")
            return msgs, data.get("emotion", {})
    except Exception as e:
        logger.debug(f"[FETCH] Error: {e}")
    return [], {}


def _notify_reality(event, player_message=None, focus_request=None):
    """通知外系统玩家状态变化。"""
    try:
        import requests
        body = {"event": event, "timestamp": "now"}
        if player_message:
            body["player_message"] = player_message
        if focus_request:
            body["focus_request"] = focus_request
        requests.post(f"{REALITY_API}/api/notify", json=body, timeout=3)
    except Exception:
        pass


def _detect_focus_request(msg):
    keywords = ['上课', '开会', '睡觉', '午睡', '忙', '别打扰', '不要打扰', '静音']
    if not any(kw in msg for kw in keywords):
        return None
    match = re.search(r'(\d+)\s*(小时|分钟|个钟)', msg)
    if match:
        num = int(match.group(1))
        unit = match.group(2)
        minutes = num * 60 if '小时' in unit or '钟' in unit else num
        return {"duration_minutes": minutes, "reason": "玩家要求"}
    return None
from rag.lifecycle_manager import increment_message, increment_session
import server_state
from websockets.exceptions import ConnectionClosedError
from pipe_loop import MonikaLoop, PipeMessage

from maica_protocol import (
    STATUS_CODES,
    SYSTEM_PROMPTS,
    build_ws_response,
    sentence_splitter,
    build_messages,
    get_or_create_session,
    reset_session,
    translate_emotions,
    detect_lang,
    save_session,
    generate_resume_snapshot,
    _chat_sessions,
)
from maica_protocol import _sanitize_text
from memory_system import MemorySystem


def _generate_journal_summary(user_msg: str, assistant_reply: str) -> str:
    """用 LLM 将对话转为第三人称客观摘要（50-100字）。"""
    try:
        from config import PLAYER_NAME
        from deepseek_client import call_deepseek_with_tools
        player = PLAYER_NAME or "玩家"
        messages = [
            {"role": "system", "content": (
                "你是一个对话记录员。将以下对话转为一句第三人称客观摘要（50-100字），"
                "用中文。只描述发生了什么，不评价。格式：'{玩家名}{做了什么}。Monika{回应了什么}。'"
            )},
            {"role": "user", "content": f"玩家{player}: {user_msg[:300]}\nMonika: {assistant_reply[:300]}\n\n请生成摘要:"},
        ]
        summary = call_deepseek_with_tools(messages, [], temperature=0.3, max_tokens=150, task="extract")
        return summary.strip()
    except Exception:
        return ""


class MAICABridge:
    """MAICA 桥接 WebSocket 处理器。"""

    def __init__(self):
        self.logged_in = False
        self._first_message = True
        self.memory_system = MemorySystem()
        self.visual_builder = None  # server.py 启动时注入

    # ── WebSocket 生命周期 ──

    async def handle_ws_client(self, websocket):
        """WebSocket 客户端连接入口。管道跟随服务器，此处只管理 ws 连接。"""
        client_addr = websocket.remote_address
        logger.info(f"[WS] Client connected: {client_addr}")
        self.logged_in = True
        self._first_message = True
        _notify_reality("player_online")

        # 将 websocket 挂到服务器级 MonikaLoop 上（管道持续运行，切换推送目标）
        monika_loop = getattr(self, 'monika_loop', None)
        if monika_loop:
            monika_loop.set_websocket(websocket)
            logger.info("[WS] Pipe connected to MonikaLoop")

        try:
            # 1. 连接成功
            await websocket.send(build_ws_response(
                "maica_connection_established",
                content=json.dumps({"message": "Connected to MAICA Bridge (Deepseek)"}),
            ))

            # 2. 初始化
            await websocket.send(build_ws_response(
                "maica_connection_initiated",
                content=json.dumps({
                    "model": DEEPSEEK_MODEL,
                    "provider": "Deepseek (via MAICA Bridge)",
                }),
            ))

            # 3. 消息循环（文字 + 语音）
            self.voice_mode = False
            async for raw_message in websocket:
                try:
                    data = json.loads(raw_message)
                    t = data.get("type", "")

                    if t == "voice_start":
                        self.voice_mode = True
                        logger.info("[VOICE] Call started")

                    elif t == "voice_audio":
                        self.voice_mode = True
                        logger.info(f"[VOICE] Audio received ({len(data.get('audio',''))} chars base64)")
                        await self._handle_voice(websocket, data)

                    elif t == "voice_interrupt":
                        from voice import interrupt
                        interrupt()
                        logger.debug("[VOICE] Interrupted")

                    elif t == "voice_end":
                        self.voice_mode = False
                        logger.info("[VOICE] Call ended")

                    elif t == "stt_test":
                        await self._handle_stt_test(websocket, data)

                    else:
                        await self._dispatch(websocket, raw_message)
                except Exception:
                    logger.error(f"[WS] Error handling message:\n{traceback.format_exc()}")
                    await websocket.send(build_ws_response(
                        "maica_chat_loop_finished", content="",
                    ))

        except ConnectionClosedError:
            logger.debug("[WS] Client disconnected (Tailscale/network)")
        except OSError:
            # Windows 网络超时（如 WinError 121）视为正常断连
            logger.debug("[WS] Client disconnected (network timeout)")
        except Exception:
            logger.error(f"[WS] Client error:\n{traceback.format_exc()}")
        finally:
            # 仅当 MonikaLoop 仍指向当前连接时才清除，避免旧连接断开清掉新连接的推送目标
            if monika_loop and monika_loop.ws is websocket:
                monika_loop.clear_websocket()
            _notify_reality("player_offline")
            # 持久化会话 + 生成恢复快照
            generate_resume_snapshot("1")
            save_session("1")
            # 玩家断开时立即执行未处理的反思（线程池，不阻塞事件循环）
            try:
                def _flush():
                    from agents.reflection_agent import flush
                    flush()
                asyncio.get_running_loop().run_in_executor(None, _flush)
            except Exception:
                pass
            logger.info(f"[WS] Client disconnected: {client_addr}")

    async def _build_response(self, session_id, user_msg, is_system=False, voice=False,
                               is_first=False):
        """统一管道：构建上下文 + LLM 调用。voice=True 时使用语音提示词。"""
        import time as _time
        session, _lock = get_or_create_session(session_id)
        lang = detect_lang(user_msg)
        context = self.memory_system.get_context(user_msg, session_id, is_first)
        profile = ""
        try:
            from rag.profile_manager import profile_to_prompt
            profile = profile_to_prompt()
        except Exception:
            pass

        def _call_api():
            set_current_session(session_id)
            persona = get_rag_manager().persona
            messages = build_messages(session, user_msg, lang,
                                      context=context, persona=persona, profile=profile,
                                      session_id=session_id, voice=voice)
            full = call_deepseek_with_tools(messages, TOOLS)
            # 玩家消息进入会话历史（带时间戳），系统触发器不进入
            now = _time.time()
            if not is_system:
                session.append({"role": "user", "content": user_msg, "_time": now})
            session.append({"role": "assistant", "content": full, "_time": now})
            return full

        from rag.rag_manager import get_rag_manager  # _call_api 闭包需要

        full = await self._run_blocking(_call_api)
        return full

    # ── 消息分发 ──

    async def _dispatch(self, websocket, raw_message):
        """根据消息类型分发处理。"""
        try:
            data = json.loads(raw_message)
        except json.JSONDecodeError:
            logger.warning(f"[WS] Invalid JSON: {raw_message[:100]}")
            return

        msg_type = data.get("type", "")
        logger.debug(f"[WS] Received: type={msg_type}")

        if msg_type == "query":
            await self.handle_query(websocket, data)
        elif msg_type == "params":
            await self.handle_params(websocket, data)
        elif msg_type == "health":
            if ENABLE_HEALTH_SYNC:
                self.memory_system.set_health_data(data)
                logger.info(f"[HEALTH] Received: HR={data.get('heart_rate',{}).get('current')} "
                            f"sleep={data.get('sleep',{}).get('total_hours')}h "
                            f"steps={data.get('steps',{}).get('today')}")
        elif "access_token" in data or "token" in data:
            logger.info("[WS] Token received, accepting...")
            await websocket.send(build_ws_response(
                "maica_connection_initiated",
                content=json.dumps({"success": True}),
            ))
        else:
            logger.debug(f"[WS] Unknown message type: {msg_type}")

    # ── 参数 / 设置 ──

    async def handle_params(self, websocket, data):
        logger.info(f"[WS] Received params: {json.dumps(data, ensure_ascii=False)[:200]}")
        await websocket.send(build_ws_response(
            "maica_params_accepted",
            content=json.dumps({"success": True, "message": "Settings applied"}),
        ))

    # ── 查询分发 ──

    async def handle_query(self, websocket, data):
        session_id = str(data.get("chat_session", 1))
        user_msg = data.get("query", "")

        # reset
        if data.get("reset") is True:
            logger.info(f"[WS] Resetting session {session_id}")
            reset_session(session_id)
            await websocket.send(build_ws_response("maica_chat_loop_finished", content=""))
            return

        # MSpire
        if "inspire" in data:
            await self._handle_mspire(websocket, data, session_id)
            return

        # MPostal
        if "postmail" in data:
            await self._handle_mpostal(websocket, data, session_id)
            return

        # Raw context (-1 session)
        if session_id == "-1":
            await self._handle_raw_context(websocket, data)
            return

        # ── 优雅退出 ──
        if not isinstance(user_msg, str):
            logger.warning("[WS] Empty query, ignoring")
            return
        if user_msg.strip() in ("退出聊天", "关闭程序"):
            logger.info("[SHUTDOWN] Graceful shutdown requested by client")
            # 1. 通知客户端
            await websocket.send(build_ws_response(
                "maica_chat_loop_finished", content="服务器正在关闭..."))
            await websocket.send(json.dumps({
                "code": 5999, "status": "server_shutdown",
                "content": "服务器正在安全关闭，数据已保存。",
                "type": "reply", "timestamp": int(__import__('time').time() * 1000),
            }))
            await asyncio.sleep(0.5)

            # 2. 保存所有会话到磁盘
            for sid in list(_chat_sessions.keys()):
                save_session(sid)
                generate_resume_snapshot(sid)
                logger.info(f"[SHUTDOWN] Session {sid} saved")
            logger.info("[SHUTDOWN] All sessions saved")

            # 3. 关闭 Qdrant（优雅关闭，避免数据损坏）
            try:
                from storage.qdrant_client import _client
                if _client:
                    _client.close()
                    logger.info("[SHUTDOWN] Qdrant closed")
            except Exception as e:
                logger.warning(f"[SHUTDOWN] Qdrant close error: {e}")

            # 4. 触发服务器退出
            from server_state import shutdown_event
            shutdown_event.set()
            logger.info("[SHUTDOWN] Shutdown event set, server will exit")
            return

        # ── 普通聊天 ──
        if not user_msg.strip():
            logger.warning("[WS] Empty query, ignoring")
            return

        is_system = data.get("is_system", False)
        await self._handle_chat(websocket, session_id, user_msg, is_system=is_system)

    # ── 普通聊天 ──

    async def _handle_chat(self, websocket, session_id, user_msg, is_system=False, voice=False):
        user_msg = _sanitize_text(user_msg)
        logger.info(f"[CHAT] session={session_id} | {user_msg[:80]}...")

        session, _lock = get_or_create_session(session_id)
        lang = detect_lang(user_msg)

        # 系统消息跳过玩家通知和门控
        trigger_contexts = []
        if not is_system:
            _notify_reality("player_message", user_msg)
            focus_req = _detect_focus_request(user_msg)
            if focus_req:
                _notify_reality("player_message", user_msg, focus_request=focus_req)
            _save_chat_log(user_msg, "player", skip_jsonl=True)

        # 门控检查（系统消息跳过）
        if not is_system:
            try:
                from gatekeeper import handle_player_message as gate_check, reset_sneak
                reset_sneak()
                gate_result = gate_check(user_msg)
                if gate_result and isinstance(gate_result, dict):
                    gtype = gate_result.get("type", "")
                    if gtype == "auto_reply":
                        auto_text = gate_result.get("text", "[自动回复] Monika暂时不在。")
                        _save_chat_log(auto_text, skip_jsonl=True)
                        session.append({"role": "user", "content": user_msg, "_time": __import__('time').time()})
                        await self._stream_response(websocket, [auto_text], lang)
                        await websocket.send(build_ws_response("maica_chat_loop_finished", content=""))
                        return
                    elif gtype == "sneak":
                        ctx = gate_result.get("context", "你正在上课，看了一眼手机。")
                        trigger_contexts.append(ctx)
                elif gate_result:
                    await self._stream_response(websocket, [str(gate_result)], lang)
                    _save_chat_log(str(gate_result), skip_jsonl=True)
                    session.append({"role": "user", "content": user_msg, "_time": __import__('time').time()})
                    await websocket.send(build_ws_response("maica_chat_loop_finished", content=""))
                    return
            except ImportError:
                pass
        import time as _time_module
        if not is_system:
            global _last_player_chat_time
            now_epoch = _time_module.time()
            if _last_player_chat_time and now_epoch - _last_player_chat_time > 3600:
                trigger_contexts.append("玩家刚刚回来了。")
            _last_player_chat_time = now_epoch

        # 注入 trigger_context
        if trigger_contexts:
            user_msg = user_msg + "\n\n[事件提醒]\n" + "\n".join(f"- {c}" for c in trigger_contexts)

        is_first = self._first_message and not is_system
        if is_first:
            self._first_message = False
        full = await self._build_response(session_id, user_msg, is_system=is_system, voice=voice,
                                          is_first=is_first)
        if full is None:
            if websocket:
                try:
                    await websocket.send(build_ws_response("maica_chat_loop_finished", content=""))
                except Exception:
                    pass
            return

        # 推送回复（在线时），始终保存日志
        if websocket:
            try:
                await self._stream_response(websocket, [full], lang)
                await websocket.send(build_ws_response("maica_chat_loop_finished", content=""))
                # 发送展示数据（仅鸿蒙前端需要）
                if ENABLE_HARMONYOS and self.visual_builder:
                    try:
                        visual = self.visual_builder.build(is_first=is_first)
                        await websocket.send(json.dumps({
                            "code": 5290, "status": "visual_data",
                            "content": "", "type": "reply",
                            "timestamp": int(__import__('time').time() * 1000),
                            "visual": visual,
                        }, ensure_ascii=False))
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"[CHAT] Stream/response error (post-processing will still run): {e}")
        else:
            logger.info(f"[CHAT] Offline — reply saved, not streamed")
            _save_chat_log(full)  # 仅离线时服务端保存（在线由前端 POST /api/chat_log）
        logger.info(f"[CHAT] session={session_id} completed, length={len(full)}")

        # 追加短期记忆
        self._add_rag_memory(user_msg, full)

        # 更新生命周期计数器
        self._update_lifecycle()

        # 自动保存长期记忆（不依赖 LLM 调工具）
        self._auto_save_long_term(user_msg, full)

        # 写经历日志（仅玩家对话，系统消息的 user_msg 是状态机触发器，非玩家发言）
        if not is_system:
            self._add_journal(user_msg, full)

        # 提交反思事件（如果这轮对话有足够情感分量）
        try:
            from cognition.salience import mark_for_storage
            _, worth = mark_for_storage(user_msg, full)
            if worth:
                from agents.reflection_agent import submit
                submit(f"玩家: {user_msg[:100]} | Monika: {full[:100]}")
        except ImportError:
            pass

        # 如果流式发送已经失败，不重新抛出（避免外层 handler 重复错误日志）

    # ── 语音通话 ──

    async def _handle_voice(self, websocket, data):
        """处理语音通话：base64 PCM → STT → LLM → TTS 逐句推送。"""
        if getattr(self, '_voice_busy', False):
            return  # 上一条还没播完，跳过
        self._voice_busy = True

        try:
            await self._handle_voice_inner(websocket, data)
        finally:
            self._voice_busy = False

    async def _handle_voice_inner(self, websocket, data):
        import base64
        audio = data.get("audio", "")
        if not audio:
            return

        # 1. STT
        try:
            audio_bytes = base64.b64decode(audio)
        except Exception:
            return
        sr = data.get("sampleRate", 16000)
        result = await self._run_blocking(
            lambda: __import__('voice').transcribe(audio_bytes, sample_rate=sr))
        if result is None:
            return
        text = result.get("text", "")
        if not text or len(text) < 2:
            return

        logger.info(f"[VOICE] STT: {text[:60]}...")
        _save_chat_log(text, "player")

        # 2. LLM（同一 pipeline）
        session_id = str(data.get("chat_session", 1))
        full = await self._build_response(session_id, text, voice=True)
        if not full:
            return

        # 3. TTS — 整段合成一次，避免逐句堆叠
        global _last_player_chat_time
        _last_player_chat_time = __import__('time').time()

        from voice import synthesize
        loop = asyncio.get_running_loop()
        wav = await loop.run_in_executor(None, synthesize, full)
        await websocket.send(build_ws_response("voice_reply", content=full))
        if wav and len(wav) > 100:
            await websocket.send(wav)

        # 4. 存档
        _save_chat_log(full)

        # 5. 情绪联动
        emotion = result.get("emotion")
        if emotion:
            try:
                import requests
                requests.post("http://127.0.0.1:6101/api/emotion", json={
                    "type": "voice_tone",
                    "emotion": emotion,
                    "timestamp": "now",
                }, timeout=3)
            except Exception:
                pass

    # ── STT 测试 ──

    async def _handle_stt_test(self, websocket, data):
        """STT 测试：PCM → whisper → 回传文本。"""
        import base64
        audio = data.get("audio", "")
        if not audio:
            return
        try:
            audio_bytes = base64.b64decode(audio)
        except Exception:
            return
        sr = data.get("sampleRate", 16000)
        result = await self._run_blocking(
            lambda: __import__('voice').transcribe(audio_bytes, sample_rate=sr))
        if result:
            await websocket.send(build_ws_response("stt_result", content=result.get("text", "")))

    # ── MSpire ──

    async def _handle_mspire(self, websocket, data, session_id):
        logger.info(f"[MSPIRE] session={session_id}")

        inspire = data.get("inspire", {})
        topic = inspire.get("title", "") if isinstance(inspire, dict) else ""

        if topic:
            prompt = (
                f'请以Monika的身份，以话题"{topic}"为灵感，发起一段轻松自然的对话。'
            )
        else:
            prompt = (
                "发起一段轻松自然的对话。"
                "可以聊文学、诗歌、哲学、日常生活、科技、音乐等等。"
            )

        def _call_api():
            messages = [
                {"role": "system", "content": SYSTEM_PROMPTS["zh"]},
                {"role": "user", "content": prompt},
            ]
            return "".join(chunk for chunk in call_deepseek_chat_stream(messages))

        full = await self._run_blocking(_call_api)
        if full is None:
            await websocket.send(build_ws_response("maica_chat_loop_finished", content=""))
            return

        await self._stream_response(websocket, [full], "zh")
        await websocket.send(build_ws_response("maica_chat_loop_finished", content=""))
        logger.info("[MSPIRE] Completed")

    # ── MPostal ──

    async def _handle_mpostal(self, websocket, data, session_id):
        logger.info(f"[MPOSTAL] session={session_id}")

        postal = data.get("postmail", {})
        if isinstance(postal, dict):
            title = postal.get("header", "")
            content = postal.get("content", "")
        else:
            title = ""
            content = str(postal)

        user_msg = f"我写了一封信给你，标题是：{title}\n\n信的内容：\n{content}"
        session, _lock = get_or_create_session("mpostal")

        def _call_api():
            messages = build_messages(session, user_msg, "zh")
            full = "".join(chunk for chunk in call_deepseek_chat_stream(messages))
            session.append({"role": "user", "content": user_msg})
            session.append({"role": "assistant", "content": full})
            return full

        full = await self._run_blocking(_call_api)
        if full is None:
            await websocket.send(build_ws_response("maica_chat_loop_finished", content=""))
            return

        await self._stream_response(websocket, [full], "zh")
        await websocket.send(build_ws_response("maica_chat_loop_finished", content=""))
        logger.info("[MPOSTAL] Completed")

    # ── Raw Context ──

    async def _handle_raw_context(self, websocket, data):
        logger.info("[RAW] -1 session request")

        query = data.get("query", [])
        if not isinstance(query, list):
            query = [{"role": "user", "content": str(query)}]

        def _call_api():
            return "".join(chunk for chunk in call_deepseek_chat_stream(query))

        full = await self._run_blocking(_call_api)
        if full is None:
            await websocket.send(build_ws_response("maica_chat_loop_finished", content=""))
            return

        await self._stream_response(websocket, [full], "zh")
        await websocket.send(build_ws_response("maica_chat_loop_finished", content=""))
        logger.info("[RAW] Completed")

    # ── 工具方法 ──

    async def _run_blocking(self, func):
        """在线程池中执行同步阻塞函数，返回结果或 None。"""
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, func)
        except Exception:
            logger.error(f"[BLOCKING] Error:\n{traceback.format_exc()}")
            return None

    # @staticmethod removed
    async def _stream_response(self, websocket, text_chunks, lang="zh"):
        """按句子拆分文本并通过 WebSocket 流式发送。"""
        for sentence in sentence_splitter(text_chunks):
            processed = translate_emotions(sentence, lang)
            await websocket.send(build_ws_response(
                "maica_core_streaming_continue",
                content=processed,
            ))
            await asyncio.sleep(0.2)

    # _get_proactive_context 已移除，由 memory_system.MemorySystem.get_context() 替代

    # @staticmethod removed
    def _add_rag_memory(self, user_msg, assistant_reply):
        """在对话后追加短期记忆（标注显著性）。"""
        try:
            from cognition.salience import compute as salience_score
            from rag.rag_manager import get_rag_manager
            rag = get_rag_manager()
            if rag.is_ready:
                rag.add_memory(user_msg, assistant_reply,
                               salience=salience_score(user_msg, assistant_reply))
        except Exception:
            logger.debug(f"RAG memory skip: {traceback.format_exc()}")

    # @staticmethod removed
    def _auto_save_long_term(self, user_msg, assistant_reply):
        """对话后自动判断是否有值得永久记住的信息，不依赖 LLM 调工具。"""
        try:
            # Salience 预检：太低直接跳过，省 API 调用
            from cognition.salience import mark_for_storage
            salience, worth = mark_for_storage(user_msg, assistant_reply)
            if not worth:
                return

            from config import DEEPSEEK_BASE, DEEPSEEK_MODEL, PLAYER_NAME, get_api_key
            import requests

            player = PLAYER_NAME or "玩家"
            body = {
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": (
                        "你是一个严格的信息提取器。只有玩家明确透露了重要的、长期稳定的个人信息时才记录，例如：姓名、职业、住址、重大人生事件。"
                        "日常闲聊、一时情绪、随口说的话一律忽略，回复 NONE。"
                        "原则：非必要不记忆。拿不准的就不记。"
                    )},
                    {"role": "user", "content": (
                        f"玩家{player}: {user_msg[:300]}\n"
                        f"Monika: {assistant_reply[:300]}\n\n"
                        f"请判断：{player}透露了什么值得永久记住的新信息？"
                    )},
                ],
                "temperature": 0,
                "max_tokens": 150,
            }
            if ENABLE_THINKING:
                body["reasoning_effort"] = REASONING_EFFORT
                body["thinking"] = {"type": "enabled"}
            resp = requests.post(
                f"{DEEPSEEK_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {get_api_key('extract')}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=10,
            )
            if resp.status_code == 200:
                info = resp.json()["choices"][0]["message"]["content"].strip()
                if info and info.upper() != "NONE":
                    from tools import _save_memory
                    _save_memory(info)
                    logger.info(f"[AUTO-MEM] Saved: {info[:80]}")
        except Exception:
            logger.debug(f"Auto memory save skip: {traceback.format_exc()}")

    # @staticmethod removed
    def _update_lifecycle(self):
        """更新服务器生命周期计数器（消息数、运行时长）。"""
        try:
            increment_message()
        except Exception:
            logger.debug(f"Lifecycle update skip: {traceback.format_exc()}")

    # @staticmethod removed
    def _add_journal(self, user_msg, assistant_reply):
        """对话后写经历日志（第三人称叙事）。"""
        try:
            from rag.profile_manager import get_location_city, get_profile
            city = get_location_city()
            location = city if city else "未知地点"

            # 获取当前天气作为日志上下文
            weather = ""
            try:
                if city:
                    from tools import _get_weather
                    w = _get_weather(city)
                    # 简化天气信息
                    if "气温" in w:
                        parts = w.split("，")
                        weather = f"{parts[0]},{parts[1]}" if len(parts) >= 2 else parts[0]
            except Exception:
                pass

            # 用 LLM 将对话转为第三人称摘要
            summary = _generate_journal_summary(user_msg, assistant_reply)
            if summary:
                add_journal_entry(location=location, weather=weather, summary=summary)
        except Exception:
            logger.debug(f"Journal write skip: {traceback.format_exc()}")


async def start_bridge_poller(monika_loop, stop_event=None):
    """独立异步函数：从外系统拉取消息塞入管道。跟随服务器生命周期。"""
    if stop_event is None:
        stop_event = asyncio.Event()
    logger.info("[PIPE-POLL] Bridge poller started (server-level)")
    loop = asyncio.get_running_loop()
    try:
        while not stop_event.is_set():
            await asyncio.sleep(10)
            if stop_event.is_set():
                break

            pending_msgs, _ = await loop.run_in_executor(None, _fetch_pending)
            if not pending_msgs:
                continue

            try:
                from gatekeeper import get_current_event
                ev = get_current_event()
                if ev and not ev.get("can_reply", True):
                    logger.debug(f"[PIPE-POLL] Blocked: Monika is {ev.get('activity')}")
                    continue
            except ImportError:
                pass

            count = 0
            for msg in pending_msgs:
                text = msg.get("text")
                if not text:
                    continue
                monika_loop.pipe.put(PipeMessage(
                    source="state_machine",
                    text=text,
                    priority=msg.get("priority", 5),
                ))
                count += 1
            if count:
                logger.info(f"[PIPE-POLL] Enqueued {count} msg(s) into MonikaLoop pipe")
    except asyncio.CancelledError:
        logger.info("[PIPE-POLL] Poller cancelled")
    except Exception:
        logger.error(f"[PIPE-POLL] Error: {traceback.format_exc()}")
