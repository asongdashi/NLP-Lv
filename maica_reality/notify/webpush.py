"""
Web Push 通知渠道
==================
通过 VAPID 协议向 Android Chrome PWA 推送通知。
"""

import os
import json
from .base import NotifyChannel


class WebPushChannel(NotifyChannel):
    def channel_name(self):
        return "webpush"

    def is_available(self):
        return bool(_get_subscriptions())

    def send(self, title, message, priority):
        return send_webpush(title, message, priority)


def _get_subscriptions():
    """加载所有已注册的 push subscription。"""
    subs_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "state", "push_subscriptions.json"
    )
    if os.path.exists(subs_path):
        try:
            with open(subs_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _get_vapid_keys():
    """获取 VAPID 密钥对。"""
    from config import logger
    # 尝试从 config 读取
    try:
        import json as _json
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config.json"
        )
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = _json.load(f)
        webpush = cfg.get("webpush", {})
        priv = webpush.get("vapid_private_key", "")
        pub = webpush.get("vapid_public_key", "")
        email = webpush.get("vapid_claim_email", "monika@localhost")
        if priv and pub:
            return priv, pub, email
    except Exception:
        pass

    # 自动生成
    try:
        from py_vapid import Vapid
        v = Vapid()
        v.generate_keys()
        priv = v.private_key if isinstance(v.private_key, str) else v.private_key.decode()
        pub = v.public_key if isinstance(v.public_key, str) else v.public_key.decode()
        logger.info("[WEBPUSH] Generated new VAPID keys")
        return priv, pub, "monika@localhost"
    except ImportError:
        logger.warning("[WEBPUSH] py_vapid not installed. Run: pip install py-vapid")
        return None, None, None


def send_webpush(title, message, priority=5):
    """向所有已注册的设备发送 Web Push 通知。"""
    subs = _get_subscriptions()
    if not subs:
        return False

    priv_key, pub_key, email = _get_vapid_keys()
    if not priv_key:
        return False

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        from config import logger
        logger.warning("[WEBPUSH] pywebpush not installed. Run: pip install pywebpush")
        return False

    from config import logger

    data = json.dumps({
        "title": title,
        "body": message,
        "icon": "/static/icon.png",
        "badge": "/static/badge.png",
        "data": {"url": "/m"},
    })

    success = 0
    for sub in subs:
        try:
            webpush(
                subscription_info=sub,
                data=data,
                vapid_private_key=priv_key,
                vapid_claims={"sub": f"mailto:{email}"},
                timeout=10,
            )
            success += 1
        except WebPushException as e:
            if e.response and e.response.status_code == 410:
                # Subscription 已过期，移除
                logger.debug(f"[WEBPUSH] Expired subscription removed")
            else:
                logger.debug(f"[WEBPUSH] Send failed: {e}")
        except Exception as e:
            logger.debug(f"[WEBPUSH] Error: {e}")

    return success > 0
