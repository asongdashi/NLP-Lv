"""
检索模块

统一检索接口：查询 → 三个索引分别搜索 → 合并排序 → 返回格式化文本。

检索策略:
  1. 对查询文本做 embedding
  2. 分别搜索 MAS / memory / corpus 三个索引
  3. 按相似度阈值过滤
  4. 按来源权重排序 (MAS > memory > corpus)
  5. 返回格式化的 prompt 文本
"""

import logging

from .config import (
    TOP_K_MAS, TOP_K_MEMORY, TOP_K_CORPUS,
    SIMILARITY_THRESHOLD,
    MAS_CONTEXT_WINDOW, MEMORY_CONTEXT_WINDOW,
)
from .embedding import get_embedding_model

logger = logging.getLogger("maica_bridge.rag")


def _deduplicate(results):
    """对相近结果去重（简单字符重叠判定）。"""
    if len(results) <= 1:
        return results
    unique = [results[0]]
    for item in results[1:]:
        text = item[0]
        is_dup = False
        for existing in unique:
            # 如果任一文本是另一个的子串，视为重复
            if text in existing[0] or existing[0] in text:
                # 保留分数更高的
                if item[1] > existing[1]:
                    unique.remove(existing)
                    unique.append(item)
                is_dup = True
                break
        if not is_dup:
            unique.append(item)
    return unique


def format_retrieval_results(mas_results, memory_results, corpus_results):
    """将检索结果格式化为可放入 system prompt 的文本。"""
    parts = []

    if mas_results:
        parts.append("[Monika的过往对话参考]")
        for i, (text, score) in enumerate(mas_results, 1):
            snippet = text[:300].replace("\n", " ")
            parts.append(f"{i}. (相似度{score:.2f}) {snippet}")

    if memory_results:
        parts.append("\n[你们之间的记忆]")
        for i, (text, score) in enumerate(memory_results, 1):
            snippet = text[:200].replace("\n", " ")
            parts.append(f"{i}. {snippet}")

    if corpus_results:
        parts.append("\n[额外参考资料]")
        for i, (text, score) in enumerate(corpus_results, 1):
            snippet = text[:200].replace("\n", " ")
            parts.append(f"{i}. {snippet}")

    return "\n".join(parts)


class Retriever:
    """统一检索器。"""

    def __init__(self, index_manager, memory_manager=None):
        self.index_manager = index_manager
        self.memory_manager = memory_manager
        self.embed = get_embedding_model()

    def retrieve(self, query, extra_context=""):
        """
        对查询检索所有索引。

        返回:
          - formatted_context: 格式化的检索文本（可放入 prompt）
          - raw_results: dict with keys "mas", "memory", "corpus"
        """
        # 合并查询和额外上下文
        search_text = query
        if extra_context:
            search_text = query + " " + extra_context

        # 编码查询
        query_vec = self.embed.encode_query(search_text)

        # 搜索各索引
        mas_res = []
        memory_res = []
        corpus_res = []

        if not self.index_manager.mas_index.is_empty:
            mas_res = self.index_manager.mas_index.search(query_vec, TOP_K_MAS, MAS_CONTEXT_WINDOW)

        if not self.index_manager.memory_index.is_empty:
            memory_res = self.index_manager.memory_index.search(query_vec, TOP_K_MEMORY, MEMORY_CONTEXT_WINDOW)
            # 记录检索命中的记忆条目
            if self.memory_manager:
                memory_texts = [m[0] for m in memory_res]
                active_texts = [e.content for e in self.memory_manager.entries]
                touched = []
                for mt in memory_texts:
                    try:
                        idx = active_texts.index(mt)
                        touched.append(idx)
                    except ValueError:
                        pass
                self.memory_manager.touch_entries(touched)

        if not self.index_manager.corpus_index.is_empty:
            corpus_res = self.index_manager.corpus_index.search(query_vec, TOP_K_CORPUS)

        # 过滤低相似度
        mas_res = [r for r in mas_res if r[1] >= SIMILARITY_THRESHOLD]
        memory_res = [r for r in memory_res if r[1] >= SIMILARITY_THRESHOLD]
        corpus_res = [r for r in corpus_res if r[1] >= SIMILARITY_THRESHOLD]

        # P17: salience 过滤低价值语料
        try:
            from cognition.salience import compute
            mas_res = [r for r in mas_res if compute(r[0]) > 0.1]
        except ImportError:
            pass

        # 去重
        mas_res = _deduplicate(mas_res)
        memory_res = _deduplicate(memory_res)
        corpus_res = _deduplicate(corpus_res)

        # 格式化
        formatted = format_retrieval_results(mas_res, memory_res, corpus_res)

        if formatted:
            logger.info(
                f"Retrieved: MAS={len(mas_res)}, memory={len(memory_res)}, "
                f"corpus={len(corpus_res)} → {len(formatted)} chars"
            )

        return formatted
