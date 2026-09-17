"""
RAG 管理器

统一入口，协调:
  - 索引构建/加载
  - 语料提取 (首次运行)
  - 检索增强的 prompt 构建
  - 记忆管理
"""

import os
import logging
import re
import threading

from .embedding import get_embedding_model
from .config import (
    MAS_CORPUS_DIR, MEMORY_DIR, CORPUS_DIR, INDEX_DIR,
    MAS_EXTRACT_OUTPUT,
)
from .qdrant_indexer import IndexManager
from .retriever import Retriever
from .memory_manager import MemoryManager
from .persona_manager import get_persona

logger = logging.getLogger("maica_bridge.rag")


def _has_chinese(text):
    """检测文本是否包含中文字符。"""
    return any('\u4e00' <= c <= '\u9fff' for c in text)


def _sanitize_text(text):
    """清洗文本：移除非法 Unicode 代理字符、控制字符。"""
    if not isinstance(text, str):
        return text
    text = "".join(c for c in text if not (0xD800 <= ord(c) <= 0xDFFF))
    text = "".join(c for c in text if c == "\n" or c == "\t" or ord(c) >= 0x20)
    return text


def _translate_to_english(chinese_text):
    """使用 Deepseek API 将中文查询翻译为英文，用于跨语言检索。"""
    import requests
    from config import DEEPSEEK_BASE, get_api_key

    chinese_text = _sanitize_text(chinese_text)
    resp = requests.post(
        f"{DEEPSEEK_BASE}/chat/completions",
        headers={
            "Authorization": f"Bearer {get_api_key('search')}",
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "You are translating a Chinese query for semantic search against an English corpus about Monika from Doki Doki Literature Club. Key name mappings: 夏树/夏利 = Natsuki, 沙世里/纱世里 = Sayori, 尤里 = Yuri. Important: '电车难题' means 'trolley problem'. Translate naturally. Return ONLY the English translation."},
                {"role": "user", "content": chinese_text},
            ],
            "temperature": 0,
            "max_tokens": 200,
        },
        timeout=15,
    )
    if resp.status_code != 200:
        logger.warning(f"Query translation failed: {resp.status_code}")
        return chinese_text

    result = resp.json()
    translated = result["choices"][0]["message"]["content"].strip()
    logger.info(f"Translated query: '{chinese_text[:50]}...' -> '{translated[:80]}...'")
    return translated


class RAGManager:
    """RAG 统一管理器。"""

    def __init__(self):
        self.index_manager = IndexManager()
        self.memory_manager = MemoryManager()
        self.retriever = None
        self._ready = False
        self._persona = None  # 缓存的人格文档
        self._init_lock = threading.Lock()

    @property
    def is_ready(self):
        return self._ready

    @property
    def persona(self):
        """获取 Monika 人格文档（懒加载）。"""
        if self._persona is None:
            self._persona = get_persona()
        return self._persona or ""

    def _check_embedding_type_changed(self):
        """检查嵌入模型类型是否变化，以及 TF-IDF 状态是否有效。"""
        from .embedding import get_embedding_model, TFIDFEmbedding
        embed = get_embedding_model()
        current_type = getattr(embed, '_type', 'unknown')
        type_file = os.path.join(INDEX_DIR, "embedding_type.txt")

        # 检查类型文件
        if os.path.exists(type_file):
            with open(type_file, "r") as f:
                saved_type = f.read().strip()
            if saved_type != current_type:
                logger.info(f"RAG: Embedding type changed ({saved_type} → {current_type}), "
                            "rebuilding indexes...")
                return True

        # 检查 TF-IDF 状态是否有效（版本可能不匹配）
        if current_type == "tfidf":
            tfidf = TFIDFEmbedding()
            if not tfidf.load() and not tfidf.fitted:
                # 状态无效，需重建
                logger.info("RAG: TF-IDF state invalid (version mismatch), rebuilding...")
                # 删除旧 FAISS 索引
                for fname in os.listdir(INDEX_DIR):
                    if fname.endswith(".faiss") or fname.endswith("_texts.json"):
                        os.remove(os.path.join(INDEX_DIR, fname))
                return True

        return False

    def _save_embedding_type(self):
        """保存当前嵌入模型类型。"""
        from .embedding import get_embedding_model
        embed = get_embedding_model()
        current_type = getattr(embed, '_type', 'unknown')
        type_file = os.path.join(INDEX_DIR, "embedding_type.txt")
        with open(type_file, "w") as f:
            f.write(current_type)

    def initialize(self, force_rebuild=False):
        """初始化 RAG：加载已有索引，或从零构建。线程安全。"""
        with self._init_lock:
            if self._ready and not force_rebuild:
                return  # 已经初始化完成，跳过
            return self._initialize_locked(force_rebuild)

    def _initialize_locked(self, force_rebuild=False):
        os.makedirs(INDEX_DIR, exist_ok=True)
        os.makedirs(MAS_CORPUS_DIR, exist_ok=True)
        os.makedirs(MEMORY_DIR, exist_ok=True)
        os.makedirs(CORPUS_DIR, exist_ok=True)

        # 检查嵌入模型是否变化
        if not force_rebuild:
            force_rebuild = self._check_embedding_type_changed()

        if not force_rebuild and self.index_manager.load_all():
            logger.info("RAG: Loaded existing indexes from disk")
            # 确保记忆索引是最新的（迁移后可能缺失）
            if self.index_manager.memory_index.is_empty:
                memory_texts = self.memory_manager.get_texts()
                if memory_texts:
                    logger.info("RAG: Rebuilding memory index (missing after migration)")
                    try:
                        self.index_manager.build_memory_index(memory_texts)
                    except Exception as e:
                        logger.error(f"RAG: Memory index unfixable after rebuild: {e}")
                        # 非致命 — mas_corpus 仍可用
            self.retriever = Retriever(self.index_manager, self.memory_manager)
            self._ready = True
            return

        logger.info("RAG: Building indexes from scratch...")

        # 1. MAS 语料: 如果未提取，先提取
        if not os.path.exists(MAS_EXTRACT_OUTPUT):
            logger.info("RAG: Extracting MAS corpus...")
            from .corpus_extractor import extract_and_save
            extract_and_save()

        # 2. 预拟合嵌入模型（收集所有语料）再构建索引
        from .embedding import get_embedding_model
        mas_file = MAS_EXTRACT_OUTPUT if os.path.exists(MAS_EXTRACT_OUTPUT) else None
        memory_texts = self.memory_manager.get_texts()

        # 收集全量文本用于 TF-IDF 预拟合
        all_texts = []
        if mas_file:
            from .qdrant_indexer import chunk_text_file
            all_texts.extend(chunk_text_file(mas_file))
        if memory_texts:
            from .qdrant_indexer import chunk_texts
            all_texts.extend(chunk_texts(memory_texts))
        from .qdrant_indexer import chunk_files_in_dir
        all_texts.extend(chunk_files_in_dir(CORPUS_DIR))

        embed = get_embedding_model()
        embed.fit_on_corpus(all_texts)

        self.index_manager.build_all(mas_file, memory_texts, CORPUS_DIR)
        self.retriever = Retriever(self.index_manager, self.memory_manager)
        self._ready = True
        self._save_embedding_type()
        logger.info("RAG: Initialization complete")

    def retrieve(self, query, extra_context=""):
        """检索并返回格式化上下文。字符级 n-gram TF-IDF 原生支持中英文，无需翻译。"""
        if not self._ready or not self.retriever:
            return ""
        query = _sanitize_text(query)
        return self.retriever.retrieve(query, extra_context)

    def add_memory(self, user_msg, assistant_reply):
        """在对话后添加短期记忆。写入 SQLite + JSON + Qdrant。"""
        self.memory_manager.add_conversation_summary(user_msg, assistant_reply)
        text = f"[对话记忆] 玩家: {user_msg[:200]} | Monika: {assistant_reply[:200]}"
        # SQLite — 短期记忆
        try:
            from storage.api import Storage
            from datetime import datetime
            Storage().db.execute(
                "INSERT INTO short_term_memory(content, salience, created_at) VALUES(?,?,?)",
                (text, 0.3, datetime.now().isoformat()),
            )
            Storage().db.commit()
        except ImportError:
            pass
        if not self._incremental_memory(text):
            self._rebuild_memory_index()

    def save_long_term_memory(self, content):
        """Monika 手动保存长期记忆。写入 SQLite + JSON + Qdrant。"""
        self.memory_manager.save_long_term(content)
        # SQLite
        try:
            from storage.api import Storage
            from datetime import datetime
            Storage().db.execute(
                "INSERT INTO long_term_memory(content, source, salience, created_at) VALUES(?,?,?,?)",
                (content, "manual", 0.8, datetime.now().isoformat()),
            )
            Storage().db.commit()
        except ImportError:
            pass
        # 增量 upsert 单个向量
        try:
            embed = get_embedding_model()
            vec = embed.encode(content)
            import numpy as np
            vec = np.array(vec).astype(np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = (vec / norm).tolist()
            from storage.qdrant_client import get_client
            client = get_client()
            if client:
                from qdrant_client.models import PointStruct
                count = client.count(collection_name="memory").count
                client.upsert(
                    collection_name="memory",
                    points=[PointStruct(id=count, vector=vec, payload={"text": content})],
                )
        except ImportError:
            self._rebuild_memory_index()  # fallback

    def decay_memory(self):
        """兼容旧 API：新系统中短期记忆通过 compress_short_term() 管理。"""
        pass

    def compress_short_term(self, days=None):
        """压缩过期的短期记忆并重建索引。"""
        self.memory_manager.compress_short_term(days)
        self._rebuild_memory_index()

    def _rebuild_memory_index(self):
        """完全重建记忆索引（仅在批量变化时调用，如压缩后）。"""
        memory_texts = self.memory_manager.get_texts()
        self.index_manager.build_memory_index(memory_texts)

    def _incremental_memory(self, text):
        """增量追加单条记忆到 Qdrant（不重建整个索引）。"""
        try:
            embed = get_embedding_model()
            vec = embed.encode(text)
            import numpy as np
            vec = np.array(vec).astype(np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = (vec / norm).tolist()
            from storage.qdrant_client import get_client
            client = get_client()
            if client:
                from qdrant_client.models import PointStruct
                count = client.count(collection_name="memory").count
                client.upsert(
                    collection_name="memory",
                    points=[PointStruct(id=count, vector=vec, payload={"text": text})],
                )
                return True
        except ImportError:
            pass
        return False

    def rebuild_corpus_index(self):
        """重建自定义语料索引（语料文件变化后调用）。"""
        self.index_manager.build_corpus_index(CORPUS_DIR)

    def stats(self):
        return {
            "ready": self._ready,
            "mas_chunks": (
                len(self.index_manager.mas_index.texts)
                if self.index_manager.mas_index else 0
            ),
            "memory_entries": (
                len(self.index_manager.memory_index.texts)
                if self.index_manager.memory_index else 0
            ),
            "corpus_chunks": (
                len(self.index_manager.corpus_index.texts)
                if self.index_manager.corpus_index else 0
            ),
            "memory": self.memory_manager.stats(),
        }


# 全局单例
_rag_manager = None


def get_rag_manager():
    global _rag_manager
    if _rag_manager is None:
        _rag_manager = RAGManager()
    return _rag_manager
