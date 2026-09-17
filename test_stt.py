"""STT 独立测试 — whisper 语音转文字（文件版）"""
import sys
import numpy as np
import whisper
import wave

MODEL = "small"  # tiny / base / small / medium

print(f"加载 whisper {MODEL}...")
model = whisper.load_model(MODEL)
print(f"就绪。用法: python test_stt.py audio.wav\n")

if len(sys.argv) < 2:
    print("请提供 WAV 文件路径: python test_stt.py test.wav")
    sys.exit(1)

path = sys.argv[1]
print(f"读取: {path}")

# 读 WAV
with wave.open(path, "rb") as wf:
    assert wf.getnchannels() == 1, "需要单声道 WAV"
    sr = wf.getframerate()
    frames = wf.readframes(wf.getnframes())
    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

# 如果采样率不是 16kHz，重采样
if sr != 16000:
    print(f"重采样 {sr}Hz → 16000Hz...")
    import scipy.signal
    ratio = 16000 / sr
    audio = scipy.signal.resample(audio, int(len(audio) * ratio))

print("识别中...")
result = model.transcribe(audio, language="zh", fp16=False)
print(f"→ {result['text'].strip()}")
