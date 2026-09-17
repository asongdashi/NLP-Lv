"""
RAG 配置
"""

import os

_RAG_DIR = os.path.dirname(__file__)
_BRIDGE_DIR = os.path.dirname(_RAG_DIR)

# ── 路径 ──
MAS_CORPUS_DIR = os.path.join(_RAG_DIR, "..", "mas_corpus")
MEMORY_DIR = os.path.join(_RAG_DIR, "..", "memory")
CORPUS_DIR = os.path.join(_RAG_DIR, "..", "corpus")
INDEX_DIR = os.path.join(_RAG_DIR, "..", "indexes")

MAS_SCRIPTS_RPA = os.path.join(_BRIDGE_DIR, "..", "..", "..", "scripts.rpa")
MAS_EXTRACT_OUTPUT = os.path.join(MAS_CORPUS_DIR, "mas_dialogue.txt")

# ── 嵌入模型 ──
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384
_try_cuda = True
try:
    import torch
    _try_cuda = torch.cuda.is_available()
except ImportError:
    _try_cuda = False
DEVICE = "cuda" if _try_cuda else "cpu"

# ── 检索参数 ──
TOP_K_MAS = 15      # MAS 语料每次检索返回条数（配合上下文窗口）
TOP_K_MEMORY = 5    # 长期记忆返回条数
TOP_K_CORPUS = 5    # 自定义语料返回条数
SIMILARITY_THRESHOLD = 0.15  # 低于此相似度的结果丢弃（char n-gram 分数偏低）

# ── 记忆遗忘参数 ──
MEMORY_MAX_ENTRIES = 200     # 记忆保留上限
MEMORY_FORGET_LAMBDA = 0.01  # 遗忘速率 (指数衰减系数，越小遗忘越慢)
MEMORY_IMPORTANCE_DECAY = 0.95  # 每次未被检索时的衰减因子

# ── 索引重建 ──
CHUNK_SIZE = 200   # 语料切块字数 (中文)
CHUNK_OVERLAP = 50  # 块重叠字数

# ── 上下文窗口 ──
MAS_CONTEXT_WINDOW = 5   # 附带 ±N 个相邻块（增大上下文）
MEMORY_CONTEXT_WINDOW = 3  # 记忆检索的上下文窗口（增大上下文）
