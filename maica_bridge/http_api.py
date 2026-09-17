"""
HTTP API 路由模块

提供 MAICA 前端所需的 REST 接口：
- 可访问性检查 / 版本 / 合法性验证
- 服务节点列表 / 工作负载
- 情绪分析 / 对话历史 / 存档 / 触发器
"""

import os
from aiohttp import web

from config import WS_HOST, WS_PORT, HTTP_HOST, HTTP_PORT, logger


async def http_accessibility(request):
    """服务器可访问性检查。"""
    return web.json_response({
        "success": True,
        "content": "serving",
        "code": 200,
        "status": "ok",
    })


async def http_version(request):
    """返回 MAICA 版本信息。"""
    return web.json_response({
        "success": True,
        "content": {
            "legc_version": "9.9.9",
            "fe_blessland_version": "9.9.9",
        },
    })


async def http_legality(request):
    """合法性 / Token 验证 —— 桥接模式下接受任何请求。"""
    return web.json_response({
        "success": True,
        "content": {
            "username": "bridge_user",
            "valid": True,
        },
    })


async def http_emotion(request):
    """情绪分析 —— 简化版，固定返回微笑。"""
    return web.json_response({
        "success": True,
        "content": ["微笑", 0.8],
    })


async def http_defaults(request):
    """返回默认设置。"""
    return web.json_response({"success": True, "content": {}})


async def http_register(request):
    """注册接口 —— 返回一个虚拟 token。"""
    return web.json_response({
        "success": True,
        "content": "BRIDGE_TOKEN_DUMMY",
    })


async def http_servers(request):
    """返回服务节点列表（包含本桥接服务器 id=9999）。"""
    return web.json_response({
        "success": True,
        "content": {
            "isMaicaNameServer": True,
            "servers": [{
                "id": 9999,
                "name": "MAICA Bridge (Deepseek)",
                "description": "本地 MAICA 桥接服务器 - 使用 Deepseek API",
                "isOfficial": False,
                "portalPage": "https://github.com/PencilMario/MAICA",
                "servingModel": "Deepseek Chat",
                "modelLink": "https://api.deepseek.com",
                "wsInterface": f"ws://{WS_HOST}:{WS_PORT}",
                "httpInterface": f"http://{HTTP_HOST}:{HTTP_PORT}/api",
            }],
        },
    })


async def http_workload(request):
    """工作负载信息。"""
    return web.json_response({
        "success": True,
        "content": {
            "onliners": 1,
            "servers": {
                "gpu0": {
                    "0": {
                        "name": "Deepseek API",
                        "vram": "100000 MiB",
                        "mean_utilization": 0,
                        "mean_memory": 0,
                        "mean_consumption": 0,
                        "tflops": 400,
                    },
                },
            },
        },
    })


async def http_trigger(request):
    """MTrigger 管理 —— 简化版。"""
    return web.json_response({"success": True, "content": {}})


async def http_history(request):
    """对话历史 —— 简化版。"""
    return web.json_response({"success": True, "content": []})


async def http_savefile(request):
    """存档上传 —— 简化版。"""
    return web.json_response({"success": True})


async def http_chat_log(request):
    """聊天记录：GET 返回今日全部消息，POST 追加一条。"""
    import json as _json
    today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    log_dir = os.path.join(os.path.dirname(__file__), "data", "chat_logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"{today}.jsonl")

    if request.method == "GET":
        msgs = []
        if os.path.exists(log_file):
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            msgs.append(_json.loads(line))
                        except Exception:
                            pass
        return web.json_response({"messages": msgs})

    elif request.method == "POST":
        try:
            body = await request.json()
            body["time"] = body.get("time") or __import__("datetime").datetime.now().strftime("%H:%M")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(_json.dumps(body, ensure_ascii=False) + "\n")
            return web.json_response({"ok": True})
        except Exception:
            return web.json_response({"ok": False})


async def http_chat(request):
    """聊天界面 HTML。"""
    import os
    chat_path = os.path.join(os.path.dirname(__file__), "static", "chat.html")
    if os.path.exists(chat_path):
        return web.FileResponse(chat_path)
    return web.Response(text="chat.html not found", status=404)


async def http_voice(request):
    """语音通话界面 HTML。"""
    import os
    path = os.path.join(os.path.dirname(__file__), "static", "voice.html")
    if os.path.exists(path):
        return web.FileResponse(path)
    return web.Response(text="voice.html not found", status=404)


def create_http_app():
    """构建 aiohttp Application，注册所有路由。"""
    app = web.Application()
    # 静态文件
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.isdir(static_dir):
        app.router.add_static("/static/", static_dir)
    # 注册路由 — 两个前缀: /api/ 和 / (MAICA 前端直接拼接 endpoint)
    _prefixes = ("/api", "")
    _routes = [
        ("GET",    "/accessibility", http_accessibility),
        ("GET",    "/version",       http_version),
        ("GET",    "/legality",      http_legality),
        ("GET",    "/emotion",       http_emotion),
        ("GET",    "/defaults",      http_defaults),
        ("GET",    "/register",      http_register),
        ("GET",    "/servers",       http_servers),
        ("GET",    "/workload",      http_workload),
        ("GET",    "/history",       http_history),
        ("GET",    "/trigger",       http_trigger),
        ("GET",    "/vista",         http_savefile),
        ("POST",   "/trigger",       http_trigger),
        ("POST",   "/savefile",      http_savefile),
        ("PUT",    "/history",       http_savefile),
        ("DELETE", "/trigger",       http_trigger),
        ("GET",    "/chat_log",       http_chat_log),
        ("POST",   "/chat_log",       http_chat_log),
        ("GET",    "/chat",           http_chat),
        ("GET",    "/voice",          http_voice),
    ]
    for prefix in _prefixes:
        for method, path, handler in _routes:
            app.router.add_route(method, prefix + path, handler)
    return app
