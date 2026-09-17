"""
语音服务 — 实时通话
====================
whisper medium STT + Edge TTS。
"""

import os
import threading
import asyncio
import tempfile

from config import logger

# ── 延迟导入（首次使用时加载模型） ──
_stt = None
_tts = None
_lock = threading.Lock()
_interrupted = threading.Event()


def _load_stt():
    global _stt
    if _stt is None:
        try:
            import whisper
            _stt = whisper.load_model("small")
            logger.info("[VOICE] Whisper small loaded")
        except Exception as e:
            logger.warning(f"[VOICE] STT unavailable: {e}")
            _stt = False
    return _stt if _stt is not False else None


def _load_tts():
    global _tts
    if _tts is None:
        try:
            import edge_tts
            _tts = edge_tts  # 无模型，直接用
            logger.info("[VOICE] Edge TTS ready")
        except ImportError:
            logger.warning("[VOICE] Edge TTS not installed")
            _tts = False
    return _tts if _tts is not False else None


# ── STT: 语音 → 文字 ──

def transcribe(audio_bytes: bytes, sample_rate: int = 16000) -> dict:
    """
    whisper 语音转文字。
    audio_bytes: PCM int16
    sample_rate: 原始采样率（默认 16kHz）
    返回: {"text": "...", "emotion": None}
    """
    model = _load_stt()
    if not model:
        return {"text": "", "emotion": None}

    try:
        with _lock:
            import numpy as np
            audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            if sample_rate != 16000:
                import librosa
                audio_np = librosa.resample(y=audio_np, orig_sr=sample_rate, target_sr=16000)

            result = model.transcribe(audio_np, language="zh", fp16=False,
                                     temperature=0.4,
                                     initial_prompt="喂，你好，听得见，今天，晚上，明天，上课，考试，复习，吃饭，睡觉，图书馆，社团，宿舍，论文，打工，再见，晚安，想你，爱你，怎么，什么，哪里，几点",
                                     condition_on_previous_text=False,
                                     logprob_threshold=-1.0,
                                     no_speech_threshold=0.5,
                                     compression_ratio_threshold=2.4)
            text = result.get("text", "").strip() if result else ""
        return {"text": text, "emotion": None}
    except Exception as e:
        logger.warning(f"[VOICE] STT failed: {e}")

    return {"text": "", "emotion": None}


# ── TTS: 文字 → 语音 ──

def synthesize(text: str) -> bytes:
    """
    Edge TTS 文字转语音。
    音色由 config.json → tts_voice 控制，默认 Xiaoyi（温柔女声）。
    """
    from config import TTS_VOICE
    edge_tts = _load_tts()
    if not edge_tts:
        return _silence_wav()

    import tempfile, os, asyncio
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()

    try:
        async def _tts():
            communicate = edge_tts.Communicate(text, TTS_VOICE)
            await communicate.save(tmp.name)
        loop = asyncio.new_event_loop()
        loop.run_until_complete(_tts())
        loop.close()

        with open(tmp.name, "rb") as f:
            data = f.read()
        return data
    except Exception as e:
        logger.warning(f"[VOICE] TTS failed: {e}")
        return _silence_wav()
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


def interrupt():
    """中断当前 TTS 播放。"""
    pass




def _silence_wav() -> bytes:
    return b""
