"""
数据同步模块
============
定期从内系统 (maica_bridge) 同步数据到外系统 data/ 目录。
比较文件修改时间，只在有更新时复制。
"""

import os
import shutil
import time
import threading
from config import logger

SYNC_INTERVAL = 600  # 10 分钟

_sync_lock = threading.Lock()
_last_sync = 0


def sync_from_bridge():
    """从 bridge 同步数据文件。"""
    global _last_sync

    reality_dir = os.path.dirname(os.path.abspath(__file__))
    bridge_dir = os.path.join(reality_dir, "..", "maica_bridge")

    # 需要同步的文件映射
    sync_map = {
        os.path.join(bridge_dir, "memory", "long_term.json"):
            os.path.join(reality_dir, "data", "memory", "long_term.json"),
        os.path.join(bridge_dir, "memory", "short_term.json"):
            os.path.join(reality_dir, "data", "memory", "short_term.json"),
        os.path.join(bridge_dir, "journals", "experience.jsonl"):
            os.path.join(reality_dir, "data", "journals", "experience.jsonl"),
        os.path.join(bridge_dir, "profile", "player_profile.json"):
            os.path.join(reality_dir, "data", "profile", "player_profile.json"),
    }

    synced = 0
    for src, dst in sync_map.items():
        if not os.path.exists(src):
            continue
        src_mtime = os.path.getmtime(src)
        dst_mtime = os.path.getmtime(dst) if os.path.exists(dst) else 0

        if src_mtime > dst_mtime:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            synced += 1

    if synced > 0:
        logger.debug(f"[SYNC] Synced {synced} files from bridge")


def sync_loop():
    """同步循环（后台线程）。"""
    global _last_sync
    logger.info("[SYNC] Data sync loop started")

    # 首次立即同步
    sync_from_bridge()
    _last_sync = time.time()

    while True:
        try:
            time.sleep(SYNC_INTERVAL)
            sync_from_bridge()
            _last_sync = time.time()
        except Exception as e:
            logger.warning(f"[SYNC] Error: {e}")


def start_sync():
    """启动同步线程。"""
    t = threading.Thread(target=sync_loop, daemon=True)
    t.start()
    return t
