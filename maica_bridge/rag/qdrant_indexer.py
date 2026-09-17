"""
Qdrant 向量索引模块（替代 FAISS indexer.py）
===========================================
纯嵌入式，零部署。三个集合: mas_corpus, memory, corpus
"""

import os
import json
import logging
import numpy as np

from .config import INDEX_DIR, CHUNK_SIZE, CHUNK_OVERLAP
from .embedding import get_embedding_model

logger = logging.getLogger("maica_bridge.rag")


def chunk_text_file(filepath, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += max(1, chunk_size - overlap)
    return chunks


def chunk_texts(texts, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    full = "\n".join(texts)
    chunks = []
    start = 0
    while start < len(full):
        end = start + chunk_size
        chunk = full[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += max(1, chunk_size - overlap)
    return chunks


def chunk_files_in_dir(directory, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    all_chunks = []
    if not os.path.isdir(directory):
        return all_chunks
    for fname in sorted(os.listdir(directory)):
        if fname.endswith(".txt"):
            path = os.path.join(directory, fname)
            try:
                chunks = chunk_text_file(path, chunk_size, overlap)
                all_chunks.extend(chunks)
                logger.debug(f"  {fname}: {len(chunks)} chunks")
            except Exception as e:
                logger.warning(f"Failed to read {fname}: {e}")
    return all_chunks


class QdrantVectorIndex:
    """Qdrant 向量索引包装。"""

    def __init__(self, name, dim):
        self.name = name
        self.dim = dim
        self.texts = []
        self._vectors = None
        self._client = None

    def _ensure_client(self):
        # 不再缓存 self._client — 始终通过全局单例 get_client() 获取，
        # 避免三个索引各自持有过期引用。
        import sys, os as _os
        _bdir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        if _bdir not in sys.path:
            sys.path.insert(0, _bdir)
        from storage.qdrant_client import get_client, QDRANT_PATH
        try:
            return get_client()
        except ValueError:
            import shutil
            shutil.rmtree(QDRANT_PATH, ignore_errors=True)
            _os.makedirs(QDRANT_PATH, exist_ok=True)
            logger.warning(f"[{self.name}] Qdrant data corrupted, rebuilt")
            return get_client()
        except (ImportError, ModuleNotFoundError):
            return None

    def build(self, chunks):
        if not chunks:
            logger.warning(f"[{self.name}] No chunks to index")
            return

        embed = get_embedding_model()
        logger.info(f"[{self.name}] Encoding {len(chunks)} chunks...")
        vectors = embed.encode_batch(chunks)
        vectors = np.array(vectors).astype(np.float32)

        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1
        vectors = vectors / norms

        client = self._ensure_client()
        if client is None:
            logger.warning(f"[{self.name}] Qdrant not available, skipping build")
            return
        from qdrant_client.models import PointStruct, Distance, VectorParams
        if client.collection_exists(self.name):
            client.delete_collection(collection_name=self.name)
        try:
            client.create_collection(
                collection_name=self.name,
                vectors_config=VectorParams(size=self.dim, distance=Distance.COSINE),
            )
        except ValueError:
            # collection 存储文件损坏 — 修复它，重试最多 3 次
            self._repair_collection(client)
            # 修复后重试建表
            client = self._ensure_client()
            try:
                client.create_collection(
                    collection_name=self.name,
                    vectors_config=VectorParams(size=self.dim, distance=Distance.COSINE),
                )
                logger.info(f"[{self.name}] Collection rebuilt after corruption")
            except Exception as e:
                raise RuntimeError(
                    f"[{self.name}] Collection unfixable after repair: {e}"
                ) from e

        points = []
        for i, (vec, text) in enumerate(zip(vectors, chunks)):
            points.append(PointStruct(id=i, vector=vec.tolist(), payload={"text": text}))

        if points:
            client.upsert(collection_name=self.name, points=points)

        self.texts = list(chunks)
        self._vectors = vectors

        logger.info(f"[{self.name}] Index built: {len(self.texts)} chunks, dim={self.dim}")

    def _repair_collection(self, client):
        """修复损坏的 collection：关闭全局客户端 → 删除磁盘文件 → 重新初始化。"""
        import shutil, os as _os
        from storage.qdrant_client import QDRANT_PATH, _client as _global_client

        coll_path = _os.path.join(QDRANT_PATH, "collection", self.name)
        logger.warning(f"[{self.name}] Repairing corrupted collection at {coll_path}")

        # 1. 关闭全局单例客户端
        if _global_client is not None:
            try:
                _global_client.close()
            except Exception:
                pass
        import storage.qdrant_client as qc
        qc._client = None  # 重置全局单例

        # 2. 物理删除损坏的 collection 目录
        for _ in range(3):
            shutil.rmtree(coll_path, ignore_errors=True)
            if not _os.path.exists(coll_path):
                break
            import time as _t
            _t.sleep(0.3)

        if _os.path.exists(coll_path):
            raise RuntimeError(
                f"[{self.name}] Cannot delete corrupted collection directory: {coll_path}"
            )

        logger.info(f"[{self.name}] Corrupted collection files removed")

    def search(self, query_vector, k=5, context_window=0):
        if not self.texts:
            return []

        query = np.array([query_vector]).astype(np.float32)
        q_norm = np.linalg.norm(query)
        if q_norm > 0:
            query = query / q_norm

        client = self._ensure_client()
        if client is None:
            return []
        results = client.search(
            collection_name=self.name,
            query_vector=query[0].tolist(),
            limit=max(k, 15),
        )

        if context_window <= 0:
            return [(r.payload.get("text", ""), float(r.score)) for r in results]

        # 带上下文窗口
        seen = set()
        output = []
        for r in results:
            idx = r.id
            if idx < 0 or idx >= len(self.texts):
                continue
            win_start = max(0, idx - context_window)
            win_end = min(len(self.texts), idx + context_window + 1)
            for ni in range(win_start, win_end):
                if ni not in seen:
                    seen.add(ni)
                    ns = float(r.score) if ni == idx else float(r.score) * 0.85
                    output.append((self.texts[ni], ns))
        return output

    def save(self, directory):
        pass  # Qdrant auto-persists

    def load(self, directory):
        client = self._ensure_client()
        count = client.count(collection_name=self.name).count if client.collection_exists(self.name) else 0
        if count == 0:
            return False
        logger.info(f"[{self.name}] Loaded: {count} chunks")
        return True

    @property
    def is_empty(self):
        client = self._ensure_client()
        if not client.collection_exists(self.name):
            return True
        return client.count(collection_name=self.name).count == 0


class IndexManager:
    """管理所有索引。"""

    def __init__(self):
        self.mas_index = None
        self.memory_index = None
        self.corpus_index = None

    def _init_indexes(self, dim):
        self.mas_index = QdrantVectorIndex("mas_corpus", dim)
        self.memory_index = QdrantVectorIndex("memory", dim)
        self.corpus_index = QdrantVectorIndex("corpus", dim)

    def build_mas_index(self, mas_file):
        logger.info(f"Building MAS index from: {mas_file}")
        chunks = chunk_text_file(mas_file)
        if not chunks:
            logger.warning("No MAS chunks to index")
            return
        self.mas_index.build(chunks)

    def build_memory_index(self, memory_texts):
        if not memory_texts:
            return
        chunks = chunk_texts(memory_texts)
        # 重试最多 2 次 — 修复损坏、重建
        for attempt in range(2):
            try:
                self.memory_index.build(chunks)
                return
            except RuntimeError as e:
                if attempt == 0:
                    logger.warning(f"Memory index build attempt 1 failed: {e}, retrying...")
                else:
                    logger.error(f"Memory index build failed after 2 attempts: {e}")
                    raise

    def build_corpus_index(self, corpus_dir):
        logger.info(f"Building corpus index from: {corpus_dir}")
        chunks = chunk_files_in_dir(corpus_dir)
        if not chunks:
            logger.info("No corpus files found")
            return
        self.corpus_index.build(chunks)

    def load_all(self):
        embed = get_embedding_model()
        embed.load()
        self._init_indexes(embed.dim)
        self.mas_index.load(None)
        self.memory_index.load(None)
        self.corpus_index.load(None)
        return not self.mas_index.is_empty

    def build_all(self, mas_file, memory_texts, corpus_dir):
        all_corpus_texts = []
        if mas_file and os.path.exists(mas_file):
            all_corpus_texts.extend(chunk_text_file(mas_file))
        if memory_texts:
            all_corpus_texts.extend(chunk_texts(memory_texts))
        if corpus_dir and os.path.isdir(corpus_dir):
            all_corpus_texts.extend(chunk_files_in_dir(corpus_dir))
        embed = get_embedding_model()
        embed.load()
        self._init_indexes(embed.dim)
        if mas_file and os.path.exists(mas_file):
            self.build_mas_index(mas_file)
        if memory_texts:
            try:
                self.build_memory_index(memory_texts)
            except Exception as e:
                logger.warning(f"Memory index build failed ({e}), continuing without it")
        if corpus_dir and os.path.isdir(corpus_dir):
            self.build_corpus_index(corpus_dir)
