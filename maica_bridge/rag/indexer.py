"""
向量索引模块

管理三个索引的构建、保存和加载:
  - mas_index:   MAS 核心语料
  - memory_index: 长期记忆
  - corpus_index: 自定义语料

使用 FAISS 存储向量，JSON 存储原文。
"""

import os
import json
import logging
import numpy as np

from .config import INDEX_DIR, CHUNK_SIZE, CHUNK_OVERLAP
from .embedding import get_embedding_model

logger = logging.getLogger("maica_bridge.rag")


def chunk_text_file(filepath, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """将文本文件切块，返回 chunks 列表。"""
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
    """将多行文本合并后切块。"""
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
    """读取目录下所有 .txt 文件，合并并按 chunk 切分。"""
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


class VectorIndex:
    """单个 FAISS 向量索引。"""

    def __init__(self, name, dim):
        self.name = name
        self.dim = dim
        self.index = None
        self.texts = []  # chunk text

    def _ensure_faiss(self):
        try:
            import faiss
            return faiss
        except ImportError:
            raise ImportError(
                "FAISS is required for vector search. "
                "Install with: pip install faiss-cpu"
            )

    def build(self, chunks):
        """从文本块构建索引。"""
        if not chunks:
            logger.warning(f"[{self.name}] No chunks to index")
            return

        embed = get_embedding_model()
        logger.info(f"[{self.name}] Encoding {len(chunks)} chunks...")
        vectors = embed.encode_batch(chunks)
        vectors = np.array(vectors).astype(np.float32)

        # L2 归一化以便用内积做余弦相似度
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1
        vectors = vectors / norms

        faiss = self._ensure_faiss()
        self.index = faiss.IndexFlatIP(self.dim)  # 内积 = 余弦相似度(已归一化)
        self.index.add(vectors)
        self.texts = list(chunks)

        logger.info(f"[{self.name}] Index built: {len(self.texts)} chunks, "
                     f"dim={self.dim}")

    def search(self, query_vector, k=5, context_window=0):
        """搜索最相似的 k 条。context_window > 0 时也会附带相邻文本块。
        返回 [(text, score), ...]"""
        if self.index is None or not self.texts:
            return []

        query = np.array([query_vector]).astype(np.float32)
        # 查询向量也需要归一化
        q_norm = np.linalg.norm(query)
        if q_norm > 0:
            query = query / q_norm

        scores, indices = self.index.search(query, max(k, 15))
        results = []
        seen_indices = set()

        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self.texts):
                continue
            # 包含上下文窗口
            win_start = max(0, idx - context_window)
            win_end = min(len(self.texts), idx + context_window + 1)
            for neighbor_idx in range(win_start, win_end):
                if neighbor_idx not in seen_indices:
                    seen_indices.add(neighbor_idx)
                    # 匹配的中心块保持原分数，相邻块略微降权
                    neighbor_score = float(score) if neighbor_idx == idx else float(score) * 0.85
                    results.append((self.texts[neighbor_idx], neighbor_score))

        return results

    def save(self, directory):
        """保存索引到磁盘。"""
        os.makedirs(directory, exist_ok=True)
        faiss = self._ensure_faiss()
        index_path = os.path.join(directory, f"{self.name}.faiss")
        texts_path = os.path.join(directory, f"{self.name}_texts.json")

        if self.index is not None:
            faiss.write_index(self.index, index_path)
        with open(texts_path, "w", encoding="utf-8") as f:
            json.dump(self.texts, f, ensure_ascii=False)

        logger.info(f"[{self.name}] Saved to {directory}")

    def load(self, directory):
        """从磁盘加载索引。"""
        import faiss
        index_path = os.path.join(directory, f"{self.name}.faiss")
        texts_path = os.path.join(directory, f"{self.name}_texts.json")

        if not os.path.exists(index_path):
            logger.warning(f"[{self.name}] Index file not found: {index_path}")
            return False

        self.index = faiss.read_index(index_path)
        with open(texts_path, "r", encoding="utf-8") as f:
            self.texts = json.load(f)
        logger.info(f"[{self.name}] Loaded: {len(self.texts)} chunks")
        return True

    @property
    def is_empty(self):
        return self.index is None or len(self.texts) == 0


class IndexManager:
    """管理所有三个索引。"""

    def __init__(self):
        self.mas_index = None
        self.memory_index = None
        self.corpus_index = None

    def _init_indexes(self, dim):
        """创建索引（需要知道嵌入维度）。"""
        self.mas_index = VectorIndex("mas", dim)
        self.memory_index = VectorIndex("memory", dim)
        self.corpus_index = VectorIndex("corpus", dim)

    def build_mas_index(self, mas_file):
        """从提取好的 MAS 语料文件构建索引。"""
        logger.info(f"Building MAS index from: {mas_file}")
        chunks = chunk_text_file(mas_file)
        if not chunks:
            logger.warning("No MAS chunks to index")
            return
        self.mas_index.build(chunks)
        self.mas_index.save(INDEX_DIR)

    def build_memory_index(self, memory_texts):
        """从记忆文本列表构建索引。"""
        if not memory_texts:
            return
        chunks = chunk_texts(memory_texts)
        self.memory_index.build(chunks)
        self.memory_index.save(INDEX_DIR)

    def build_corpus_index(self, corpus_dir):
        """从自定义语料目录构建索引。"""
        logger.info(f"Building corpus index from: {corpus_dir}")
        chunks = chunk_files_in_dir(corpus_dir)
        if not chunks:
            logger.info("No corpus files found")
            return
        self.corpus_index.build(chunks)
        self.corpus_index.save(INDEX_DIR)

    def load_all(self):
        """加载所有已保存的索引。"""
        embed = get_embedding_model()
        embed.load()
        self._init_indexes(embed.dim)

        loaded_any = False
        if self.mas_index.load(INDEX_DIR):
            loaded_any = True
        if self.memory_index.load(INDEX_DIR):
            loaded_any = True
        if self.corpus_index.load(INDEX_DIR):
            loaded_any = True
        return loaded_any

    def build_all(self, mas_file, memory_texts, corpus_dir):
        """构建全部三个索引。"""
        # 收集所有语料文本用于 TF-IDF 预拟合
        all_corpus_texts = []

        if mas_file and os.path.exists(mas_file):
            all_corpus_texts.extend(chunk_text_file(mas_file))
        if memory_texts:
            all_corpus_texts.extend(chunk_texts(memory_texts))
        if corpus_dir and os.path.isdir(corpus_dir):
            all_corpus_texts.extend(chunk_files_in_dir(corpus_dir))

        # 预拟合嵌入模型
        embed = get_embedding_model()
        if hasattr(embed, 'fit_on_corpus') and all_corpus_texts:
            embed.fit_on_corpus(all_corpus_texts)

        # 用拟合后的维度创建索引
        self._init_indexes(embed.dim)

        # 分别构建索引
        self.build_mas_index(mas_file)
        self.build_memory_index(memory_texts)
        self.build_corpus_index(corpus_dir)
