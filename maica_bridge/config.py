"""
MAICA Bridge 配置模块

加载 config.json 并提供全局配置访问。
首次运行时如果没有 config.json 则从模板自动生成。
"""

import json
import os
import logging

_CONFIG_DIR = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(_CONFIG_DIR, "config.json")
TEMPLATE_PATH = os.path.join(_CONFIG_DIR, "config_template.json")


def load_config():
    """加载配置，优先读 config.json，否则从模板生成。"""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    elif os.path.exists(TEMPLATE_PATH):
        print("[WARN] config.json not found. Using template. Please edit config.json with your API key.")
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        return cfg
    else:
        return {}


# ── 全局配置 ──
cfg = load_config()

WS_HOST = cfg.get("ws_host", "127.0.0.1")
WS_PORT = cfg.get("ws_port", 5000)
HTTP_HOST = cfg.get("http_host", "127.0.0.1")
HTTP_PORT = cfg.get("http_port", 8080)

PLAYER_NAME = cfg.get("player_name", "玩家")

DEEPSEEK_MODEL = cfg.get("deepseek_model", "deepseek-chat")
DEEPSEEK_API_KEY = cfg.get("deepseek_api_key", "")
DEEPSEEK_BASE = cfg.get("deepseek_api_base", "https://api.deepseek.com/v1")

# ── 多 Key 支持 ──
# 每个任务类型可使用独立的 API Key，避免上下文污染。
# 未指定时回退到 deepseek_api_key。
_API_KEYS = cfg.get("api_keys", {})


def get_api_key(task="chat"):
    key = _API_KEYS.get(task, "")
    return key if key else DEEPSEEK_API_KEY


_API_MODELS = cfg.get("api_models", {})


def get_api_model(task="chat"):
    return _API_MODELS.get(task, DEEPSEEK_MODEL)

SYSTEM_PROMPT_ZH = cfg.get("system_prompt_zh", "")
SYSTEM_PROMPT_VOICE_ZH = cfg.get("system_prompt_voice_zh", "") or SYSTEM_PROMPT_ZH
SYSTEM_PROMPT_EN = cfg.get("system_prompt_en", "")

TTS_VOICE = cfg.get("tts_voice", "zh-CN-XiaoyiNeural")
LOG_LEVEL = cfg.get("log_level", "INFO")

# ── 思考模式 ──
ENABLE_THINKING = cfg.get("enable_thinking", False)
REASONING_EFFORT = cfg.get("reasoning_effort", "high")

# ── 特性开关 ──
ENABLE_HEALTH_SYNC = cfg.get("enable_health_sync", True)
ENABLE_HARMONYOS = cfg.get("enable_harmonyos", True)


# ── 日志 ──
def setup_logging():
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL),
        format="[%(levelname)s] %(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger("maica_bridge")


logger = setup_logging()
