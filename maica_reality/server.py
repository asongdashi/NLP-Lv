"""
MAICA Reality Server (外系统入口)
==================================
Monika 的"感官 + 情绪"层。
独立 HTTP 服务器，时刻监视现实世界，主动触发话题。
内系统 (maica_bridge) 通过 HTTP API 交互。

启动: python server.py
端口: 6101
"""

import sys
import os
import json
import asyncio
import threading
import time as time_module
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

try:
    from aiohttp import web
except ImportError:
    print("[FATAL] aiohttp not installed. Run: pip install aiohttp")
    sys.exit(1)

# 禁用 aiohttp access 日志
import logging as _logging
_logging.getLogger("aiohttp.access").setLevel(_logging.WARNING)

_REALITY_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _REALITY_DIR)
_BRIDGE_DIR = os.path.join(_REALITY_DIR, "..", "maica_bridge")

from config import logger, DEEPSEEK_API_KEY, CONFIG_PATH

# 共享模块（rag/ 等）统一从 bridge 导入，reality 的 rag/ 已删除
# 放在 reality 后面：优先找 reality 本地模块，找不到再 fallback 到 bridge
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(1, _BRIDGE_DIR)

# ── 共享状态（统一来源，避免 __main__ vs server 双副本 bug）──
import shared_state
from shared_state import message_queue, message_queue_lock


# ── HTTP 路由 ──

async def api_pending(request):
    """内系统拉取待投递消息。拉取后清空队列。"""
    with message_queue_lock:
        msgs = list(message_queue)
        message_queue.clear()
    if msgs:
        logger.debug(f"[API] Pending: {len(msgs)} msg(s)")
    return web.json_response({"messages": msgs})


async def api_notify(request):
    """内系统通知玩家状态变化。"""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid json"})

    event = body.get("event", "")
    now = datetime.now().isoformat()

    if event == "player_online":
        shared_state.player_online = True
        logger.info(f"[REALITY] Player online at {now}")

    elif event == "player_offline":
        shared_state.player_online = False
        logger.info(f"[REALITY] Player offline at {now}")
    elif event == "player_message":
        shared_state.player_last_msg_time = now
        # 检测勿扰指令
        focus_req = body.get("focus_request")
        if focus_req:
            from focus_manager import set_focus
            set_focus(focus_req.get("duration_minutes", 60),
                      focus_req.get("reason", "玩家要求"))
        logger.debug(f"[REALITY] Player message: {body.get('player_message', '')[:50]}")

    return web.json_response({"ok": True})


async def api_emotion(request):
    """查询 Monika 当前情绪 (调试用)。"""
    try:
        from emotion_engine import get_emotion_snapshot
        return web.json_response(get_emotion_snapshot())
    except ImportError:
        return web.json_response({"error": "emotion engine not loaded"})


async def api_push_test(request):
    """测试用：手动推一条消息到队列。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    text = body.get("text", "[测试] Monika 想说点什么~")
    with message_queue_lock:
        message_queue.append({
            "id": f"test_{int(time_module.time())}",
            "text": text,
            "trigger": "test",
            "priority": body.get("priority", 5),
            "created_at": datetime.now().isoformat(),
        })
    logger.info(f"[TEST] Pushed test message: {text[:60]}")
    return web.json_response({"ok": True, "queued": 1})


async def api_vapid_key(request):
    """返回 VAPID 公钥，供手机端注册 Web Push。"""
    try:
        from notify.webpush import _get_vapid_keys
        _, pub, _ = _get_vapid_keys()
        resp = web.json_response({"public_key": pub or ""})
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp
    except Exception:
        return web.json_response({"public_key": ""})


async def api_push_register(request):
    """手机端注册 Web Push subscription。"""
    if request.method == "OPTIONS":
        resp = web.json_response({"ok": True})
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        return resp
    try:
        body = await request.json()
        subs_path = os.path.join(_REALITY_DIR, "data", "state", "push_subscriptions.json")
        os.makedirs(os.path.dirname(subs_path), exist_ok=True)
        subs = []
        if os.path.exists(subs_path):
            with open(subs_path, "r", encoding="utf-8") as f:
                subs = json.load(f)
        endpoint = body.get("endpoint", "")
        subs = [s for s in subs if s.get("endpoint") != endpoint]
        subs.append(body)
        with open(subs_path, "w", encoding="utf-8") as f:
            json.dump(subs, f, ensure_ascii=False)
        logger.info("[REALITY] Push subscription registered")
        resp = web.json_response({"ok": True})
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})


# ── 服务器启动 ──

def create_app():
    app = web.Application()
    app.router.add_get("/api/pending", api_pending)
    app.router.add_post("/api/notify", api_notify)
    app.router.add_get("/api/emotion", api_emotion)
    app.router.add_post("/api/push_test", api_push_test)
    app.router.add_get("/api/vapid_key", api_vapid_key)
    app.router.add_post("/api/push_register", api_push_register)
    app.router.add_route("OPTIONS", "/api/push_register", api_push_register)
    # 静态文件
    static_dir = os.path.join(_REALITY_DIR, "static")
    if os.path.isdir(static_dir):
        app.router.add_static("/static/", static_dir)
    return app


async def main():
    print("=" * 50)
    print("  MAICA Reality Server (外系统)")
    print("  Monika 的感官 + 情绪层")
    print("=" * 50)

    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY == "YOUR_DEEPSEEK_API_KEY_HERE":
        print("[WARN] Deepseek API Key 未配置!")

    # 启动数据同步（后台线程）
    try:
        from data_sync import start_sync
        start_sync()
        logger.info("[REALITY] Data sync started")
    except ImportError:
        logger.warning("[REALITY] Data sync not available yet")

    # 初始化生活生成器数据
    try:
        from life.world import init_if_needed as init_world
        from life.habits import init_if_needed as init_habits
        from life.timeline import init_if_needed as init_timeline
        init_world()
        init_habits()
        init_timeline()
        logger.info("[REALITY] Life data initialized")
    except Exception:
        pass

    # 生活生成器：先同步追补今天的事件，再启动后台线程
    try:
        from life.generator import catch_up
        logger.info("[REALITY] Generating today's events...")
        catch_up()
        from life.generator import start as start_generator
        start_generator()
        logger.info("[REALITY] Life generator started")
    except Exception:
        logger.warning("[REALITY] Life generator not available yet")

    # 初始化 Self Model
    try:
        from agents.self_model import init_if_needed
        init_if_needed()
        logger.info("[REALITY] Self Model initialized")
    except ImportError:
        pass

    # 启动 Reflection Agent
    try:
        from agents.reflection_agent import start as start_reflection
        start_reflection()
        logger.info("[REALITY] Reflection Agent started")
    except ImportError:
        pass

    # 启动 Goal Planner
    try:
        from agents.goal_planner import start as start_planner
        start_planner()
        logger.info("[REALITY] Goal Planner started")
    except ImportError:
        pass

    # 启动状态机（后台线程）
    sm = None
    try:
        from state_machine import StateMachine
        sm = StateMachine(None)  # pipe 稍后由 bridge 注入
        sm.start()
        logger.info("[REALITY] State machine started")
    except ImportError:
        logger.warning("[REALITY] State machine not available yet")

    # HTTP 服务器
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 6101)
    await site.start()
    print("[REALITY] HTTP Server on http://127.0.0.1:6101")
    print("[REALITY] API: /api/pending, /api/notify, /api/emotion")
    print("[REALITY] PWA: http://127.0.0.1:6101/m")
    print("[READY] Monika 的外系统已启动\n")

    # 等待
    try:
        while shared_state.running:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass

    shared_state.running = False
    await runner.cleanup()
    print("[REALITY] Server stopped.")


if __name__ == "__main__":
    asyncio.run(main())
