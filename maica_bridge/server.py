"""
MAICA-to-Deepseek Bridge Server (入口)
======================================
一个本地 WebSocket/HTTP 服务器，模拟 MAICA 协议并转发到 Deepseek API。
使得 MAICA 前端可以直接使用 Deepseek 大模型进行对话。

使用方法:
  1. 将 config_template.json 复制为 config.json 并填入你的 Deepseek API Key
  2. 安装依赖: pip install -r requirements.txt
  3. 运行: python server.py
  4. 在 MAICA 子模组设置中将 provider_id 设置为 9999 (本地部署)
"""

import sys
import os
import asyncio

# 强制 UTF-8 输出（Windows 兼容）
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# 内外系统共享模块路径
_BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
_REALITY_DIR = os.path.join(_BRIDGE_DIR, "..", "maica_reality")
sys.path.insert(0, _BRIDGE_DIR)
if _REALITY_DIR not in sys.path:
    sys.path.insert(1, _REALITY_DIR)

# ── 依赖检查 ──
_MISSING = []
try:
    from aiohttp import web
except ImportError:
    _MISSING.append("aiohttp")
try:
    import websockets
except ImportError:
    _MISSING.append("websockets")

if _MISSING:
    print(f"[ERROR] Missing dependencies: {', '.join(_MISSING)}")
    print("请安装依赖: pip install " + " ".join(_MISSING))
    sys.exit(1)

# ── 项目模块 ──
from config import logger, DEEPSEEK_API_KEY, CONFIG_PATH, WS_HOST, WS_PORT, HTTP_HOST, HTTP_PORT, PLAYER_NAME
from config import ENABLE_HEALTH_SYNC, ENABLE_HARMONYOS

# 禁用 aiohttp 的 access 日志（避免每次 poll 都打印 GET /api/pending）
import logging as _logging
_logging.getLogger("aiohttp.access").setLevel(_logging.WARNING)
from http_api import create_http_app
from ws_handler import MAICABridge
from server_state import shutdown_event


async def _wait_for_shutdown():
    """轮询 shutdown_event，不阻塞事件循环。"""
    while not shutdown_event.is_set():
        await asyncio.sleep(0.5)


async def main():
    print("=" * 50)
    print("  MAICA-to-Deepseek Bridge Server")
    print("  MAICA Protocol -> Deepseek API")
    print("=" * 50)

    # API Key 检查
    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY == "YOUR_DEEPSEEK_API_KEY_HERE":
        print("[WARN] Deepseek API Key 未配置!")
        print(f"      请编辑文件: {CONFIG_PATH}")
        print("      填入你的 Deepseek API Key 后重新运行。\n")

    # 初始化生命周期日志
    try:
        from rag.lifecycle_manager import record_startup
        record_startup()
    except Exception:
        pass

    # 同步玩家名到档案
    try:
        from rag.profile_manager import sync_player_name
        sync_player_name(PLAYER_NAME)
    except Exception:
        pass

    # HTTP 服务器
    http_app = create_http_app()
    runner = web.AppRunner(http_app)
    await runner.setup()
    site = web.TCPSite(runner, HTTP_HOST, HTTP_PORT)
    await site.start()
    print(f"[HTTP] Server started on http://{HTTP_HOST}:{HTTP_PORT}/api")

    # ── 阶段 1: 预加载所有模型（在 WS 端口开放之前完成）──
    bridge = MAICABridge()
    loop = asyncio.get_running_loop()
    print("[INIT] Preloading models (RAG + Voice)...")

    def _init_rag():
        from rag.rag_manager import get_rag_manager
        get_rag_manager().initialize()
    def _init_stt():
        from voice import _load_stt
        _load_stt()
    def _init_tts():
        from voice import _load_tts
        _load_tts()

    futures = [loop.run_in_executor(None, f) for f in [_init_rag, _init_stt, _init_tts]]
    for f in asyncio.as_completed(futures):
        try:
            await f
        except Exception:
            pass
    logger.info("[BRIDGE] All models ready")

    # ── 阶段 2: 启动管道基础设施（在 WS 端口开放之前完成）──
    print("[INIT] Starting pipe infrastructure...")
    if ENABLE_HARMONYOS:
        from visual_builder import VisualBuilder
        bridge.visual_builder = VisualBuilder(bridge.memory_system, bridge)
        logger.info("[INIT] VisualBuilder enabled (HarmonyOS mode)")
    from pipe_loop import MonikaLoop
    monika_loop = MonikaLoop(bridge, websocket=None, session_id="1")
    bridge.monika_loop = monika_loop

    from ws_handler import start_bridge_poller
    poller_task = asyncio.create_task(start_bridge_poller(monika_loop))
    loop_task = asyncio.create_task(monika_loop.run())
    logger.info("[BRIDGE] Pipe infrastructure started")

    # ── 阶段 3: 现在才开放 WebSocket 端口 ──
    print(f"[WS] Server starting on ws://{WS_HOST}:{WS_PORT}")
    print("[READY] All models loaded. Monika is ready for connections.")

    async with websockets.serve(
        bridge.handle_ws_client,
        WS_HOST,
        WS_PORT,
        ping_interval=20,
        ping_timeout=30,
        close_timeout=10,
    ):
        print("[READY] MAICA Bridge is running. Connect now.\n")

        # 注册关闭处理
        from server_state import shutdown_event

        # 服务器持续运行，直到"关闭程序"触发 shutdown_event
        while not shutdown_event.is_set():
            await asyncio.sleep(1)

        # ── 优雅清理 ──
        print("[SHUTDOWN] Closing Qdrant...")
        try:
            from storage.qdrant_client import _client
            if _client: _client.close()
        except: pass
        print("[SHUTDOWN] Stopping pipe...")
        if monika_loop: monika_loop.stop()
        if poller_task: poller_task.cancel()
        if loop_task: loop_task.cancel()
        print("[SHUTDOWN] Stopping HTTP...")
        await runner.cleanup()
        print("[SHUTDOWN] Server stopped cleanly.")



if __name__ == "__main__":
    asyncio.run(main())
