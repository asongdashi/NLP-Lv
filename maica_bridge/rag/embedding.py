"""
嵌入模型模块

优先级:
  1. sentence-transformers (本地多语言模型，原生处理中文，无需翻译)
  2. TF-IDF + SVD (离线，自动持久化，中文需先翻译为英文)
"""

import os
import sys as _sys
import pickle
import logging
import numpy as np

# Ensure parent directory (maica_bridge/) is importable from rag subpackage
_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT not in _sys.path:
    _sys.path.insert(0, _PARENT)

from .config import EMBEDDING_DIM, INDEX_DIR, DEVICE

logger = logging.getLogger("maica_bridge.rag")


class TFIDFEmbedding:
    """TF-IDF + SVD 嵌入模型（带状态持久化）。"""

    STATE_FILE = os.path.join(INDEX_DIR, "tfidf_state.pkl")
    _VERSION = 3  # 递增以触发重建（1=word, 2=char_wb, 3=char）

    def __init__(self, dim=EMBEDDING_DIM):
        self.dim = dim
        self.vectorizer = None
        self.svd = None
        self.fitted = False

    def _ensure_imports(self):
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.decomposition import TruncatedSVD
        # 字符级 n-gram：原生支持中英文混合，无需翻译
        self.vectorizer = TfidfVectorizer(
            max_features=10000,
            analyzer="char",
            ngram_range=(3, 5),
        )
        self.svd = TruncatedSVD(n_components=self.dim)

    def fit(self, texts):
        """拟合 TF-IDF + SVD（必须在索引构建前调用）。"""
        if not texts or len(texts) < 2:
            raise ValueError("Need at least 2 texts to fit TF-IDF")
        self._ensure_imports()
        X = self.vectorizer.fit_transform(texts)
        # SVD 维度不能超过特征数
        actual_dim = min(self.dim, X.shape[1])
        if actual_dim < self.dim:
            logger.info(f"TF-IDF: reducing SVD dim from {self.dim} to {actual_dim}")
            from sklearn.decomposition import TruncatedSVD
            self.svd = TruncatedSVD(n_components=actual_dim)
            self.dim = actual_dim
        self.svd.fit(X)
        self.fitted = True
        logger.info(f"TF-IDF fitted: {len(self.vectorizer.vocabulary_)} features, "
                     f"dim={self.dim}")

    def encode(self, texts):
        """编码文本。返回 numpy array (n_texts, dim)。"""
        if not self.fitted:
            raise RuntimeError("TF-IDF not fitted. Call fit() first.")
        if isinstance(texts, str):
            texts = [texts]
        X = self.vectorizer.transform(texts)
        embs = self.svd.transform(X)
        return embs.astype(np.float32)

    def save(self):
        """保存 TF-IDF 状态到磁盘。"""
        os.makedirs(INDEX_DIR, exist_ok=True)
        state = {
            "vectorizer": self.vectorizer,
            "svd": self.svd,
            "dim": self.dim,
            "fitted": self.fitted,
            "version": self._VERSION,
        }
        with open(self.STATE_FILE, "wb") as f:
            pickle.dump(state, f)
        logger.info(f"TF-IDF state saved (v{self._VERSION}) to {self.STATE_FILE}")

    def load(self):
        """从磁盘加载 TF-IDF 状态。版本不匹配时返回 False 触发重建。"""
        if not os.path.exists(self.STATE_FILE):
            return False
        try:
            with open(self.STATE_FILE, "rb") as f:
                state = pickle.load(f)
            if state.get("version", 0) != self._VERSION:
                logger.info(f"TF-IDF state version mismatch (saved {state.get('version')} vs {self._VERSION}), will rebuild")
                os.remove(self.STATE_FILE)
                return False
            self.vectorizer = state["vectorizer"]
            self.svd = state["svd"]
            self.dim = state["dim"]
            self.fitted = state["fitted"]
            logger.info(f"TF-IDF state loaded v{self._VERSION}: dim={self.dim}")
            return True
        except Exception as e:
            logger.warning(f"Failed to load TF-IDF state: {e}")
            return False


class SentenceTransformerEmbedding:
    """sentence-transformers 本地多语言模型，原生处理中文。
    多源下载：依次尝试多个 HF 镜像，短超时快速切换。"""

    MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

    # 按优先级排列的镜像列表
    _ENDPOINTS = [
        "https://hf-mirror.com",
        "https://huggingface.co",
        "https://hf.openxlab.org.cn",
    ]

    def __init__(self):
        self._model = None
        self.dim = EMBEDDING_DIM

    def _ensure_model(self):
        if self._model is not None:
            return

        from sentence_transformers import SentenceTransformer

        cache_dir = os.path.join(INDEX_DIR, "..", ".cache", "sentence_transformers")
        last_error = None

        # 多源下载：逐个尝试 HF 端点，30s 超时
        for endpoint in self._ENDPOINTS:
            try:
                os.environ["HF_ENDPOINT"] = endpoint
                logger.info(f"Trying HF endpoint: {endpoint}")
                # 先通过 huggingface_hub 下载（可控超时），再用本地路径加载
                from huggingface_hub import snapshot_download as hf_download
                model_path = hf_download(
                    "sentence-transformers/" + self.MODEL_NAME,
                    cache_dir=cache_dir,
                    resume_download=True,
                    local_files_only=False,
                )
                self._model = SentenceTransformer(model_path, device=DEVICE)
                logger.info(f"SentenceTransformer loaded via {endpoint}: {self.MODEL_NAME}")
                return
            except Exception as e:
                last_error = e
                logger.warning(f"Failed via {endpoint}: {e}")
                # 清除可能的残留缓存文件（部分下载）
                import shutil
                partial = os.path.join(cache_dir, "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2")
                if os.path.exists(partial):
                    blob = os.path.join(partial, "blobs")
                    if os.path.exists(blob) and len(os.listdir(blob)) == 0:
                        shutil.rmtree(partial, ignore_errors=True)
                        logger.info(f"Cleaned partial download from {endpoint}")

        raise last_error or OSError("All HF endpoints failed to download the model")

    def encode(self, texts):
        """编码文本。返回 numpy array (n_texts, dim)。"""
        self._ensure_model()
        if isinstance(texts, str):
            texts = [texts]
        embs = self._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return embs.astype(np.float32)

    def fit_on_corpus(self, texts):
        """sentence-transformers 无需拟合，但保留接口兼容。"""
        self._ensure_model()


class DeepseekEmbedding:
    """Deepseek Embeddings API 模式。"""

    def __init__(self):
        from config import DEEPSEEK_BASE, get_api_key
        self.api_key = get_api_key('embed')
        self.base = DEEPSEEK_BASE
        self.dim = EMBEDDING_DIM

    def encode(self, texts):
        import requests
        if isinstance(texts, str):
            texts = [texts]

        all_embeddings = []
        for i in range(0, len(texts), 20):
            batch = texts[i:i + 20]
            resp = requests.post(
                f"{self.base}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": "deepseek-chat", "input": batch},
                timeout=30,
            )
            if resp.status_code != 200:
                raise Exception(f"Deepseek embeddings error: {resp.status_code} {resp.text}")
            data = resp.json()
            for item in data.get("data", []):
                all_embeddings.append(item["embedding"])
        return np.array(all_embeddings, dtype=np.float32)


class EmbeddingModel:
    """统一的嵌入模型接口。"""

    def __init__(self):
        self._model = None
        self._type = None

    def load(self):
        """加载模型。优先 sentence-transformers（多语言，原生中文），
        否则 TF-IDF char n-gram。"""
        if self._model is not None:
            return

        # 1) 优先: sentence-transformers 本地多语言模型（多源尝试）
        try:
            st = SentenceTransformerEmbedding()
            st._ensure_model()
            self._model = st
            self._type = "sentencetransformers"
            logger.info("Embedding: sentence-transformers loaded")
            return
        except (ImportError, OSError) as e:
            logger.warning(f"SentenceTransformer unavailable: {e}")

        # 2) 已保存的 TF-IDF 状态
        tfidf = TFIDFEmbedding()
        if tfidf.load():
            self._model = tfidf
            self._type = "tfidf"
            logger.info("Embedding: loaded saved TF-IDF state")
            return

        # 3) 新建 TF-IDF（字符级 n-gram）
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            logger.info("Embedding: TF-IDF char n-gram + SVD")
            self._model = tfidf
            self._type = "tfidf"
            return
        except ImportError:
            pass

        # 4) 兜底: DeepSeek Embeddings API（需要 API key，无需本地模型下载）
        try:
            ds = DeepseekEmbedding()
            logger.info("Embedding: DeepSeek API (cloud), dim={}".format(ds.dim))
            self._model = ds
            self._type = "deepseek"
            return
        except Exception as e:
            logger.warning(f"DeepSeek embeddings also unavailable: {e}")

        raise RuntimeError("No embedding model available. "
                           "Install sentence-transformers or scikit-learn, or configure DeepSeek API.")

    def encode(self, texts):
        self.load()
        if isinstance(texts, str):
            texts = [texts]
        return self._model.encode(texts)

    def encode_query(self, text):
        return self.encode(text)[0]

    def encode_batch(self, texts, batch_size=64):
        return self.encode(texts)

    def fit_on_corpus(self, texts):
        """用全量语料拟合 TF-IDF 模型（索引构建时调用）。"""
        self.load()
        if self._type == "tfidf" and not self._model.fitted:
            self._model.fit(texts)
            self._model.save()

    @property
    def dim(self):
        self.load()
        return self._model.dim if hasattr(self._model, 'dim') else EMBEDDING_DIM


_embedding_model = None


def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = EmbeddingModel()
    return _embedding_model
