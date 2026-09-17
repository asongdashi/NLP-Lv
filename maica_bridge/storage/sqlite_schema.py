"""
SQLite 主存储 — 初始化 + 连接管理
===============================
嵌入式，零部署。文件: data/maica_data.db
"""

import os
import sqlite3
import threading

_BRIDGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_BRIDGE_DIR, "data", "maica_data.db")

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS self_state (
    category TEXT NOT NULL,
    key TEXT NOT NULL,
    value REAL NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (category, key)
);

CREATE TABLE IF NOT EXISTS beliefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    confidence REAL DEFAULT 0.5,
    formed_at TEXT NOT NULL,
    updated_at TEXT,
    active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    category TEXT NOT NULL,
    created_at TEXT NOT NULL,
    active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS life_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    weekday TEXT,
    time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    activity TEXT NOT NULL,
    detail TEXT,
    participants TEXT,
    can_reply INTEGER DEFAULT 1,
    sneak_possible INTEGER DEFAULT 0,
    sub_events TEXT,
    generated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_date ON life_events(date);

CREATE TABLE IF NOT EXISTS emotion_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    impact TEXT NOT NULL,
    half_life_h REAL DEFAULT 4,
    created_at TEXT NOT NULL,
    decayed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reflections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    events_summary TEXT,
    journal_summary TEXT,
    result TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS long_term_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    source TEXT DEFAULT 'auto',
    salience REAL DEFAULT 0.5,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    who TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_date ON chat_messages(timestamp);

CREATE TABLE IF NOT EXISTS short_term_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    salience REAL DEFAULT 0.3,
    created_at TEXT NOT NULL
);
"""


def _connect():
    if not hasattr(_local, "conn") or _local.conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
        _local.conn.row_factory = sqlite3.Row
        for _ in range(5):
            try:
                _local.conn.execute("PRAGMA journal_mode=WAL")
                _local.conn.execute("PRAGMA synchronous=NORMAL")
                break
            except sqlite3.OperationalError:
                import time
                time.sleep(0.5)
    return _local.conn


def init_db():
    conn = _connect()
    conn.executescript(SCHEMA)
    conn.commit()


def get_conn():
    return _connect()
