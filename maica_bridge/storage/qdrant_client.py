"""
Qdrant 向量存储 — 单例客户端
=============================
所有模块共享同一个 QdrantClient 实例。
"""

import os
import threading

_BRIDGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QDRANT_PATH = os.path.join(_BRIDGE_DIR, "data", "qdrant")

_client = None
_lock = threading.Lock()

COLLECTIONS = {
    "mas_corpus":      384,
    "memory":          384,
    "long_term_memory": 384,
    "corpus":          384,
}


def get_client():
    """获取全局单例 Qdrant 客户端。检测尸体，自动重建。"""
    global _client
    if _client is not None:
        try:
            _client.get_collections()
            return _client
        except RuntimeError:
            _client = None  # closed, will recreate below

    with _lock:
        if _client is not None:
            return _client
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams
        os.makedirs(QDRANT_PATH, exist_ok=True)
        _client = QdrantClient(path=QDRANT_PATH)
        for name, dim in COLLECTIONS.items():
            if not _client.collection_exists(name):
                _client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
                )
    return _client


def upsert(collection, vectors, payloads=None):
    client = get_client()
    from qdrant_client.models import PointStruct
    points = []
    _next_id = [0]
    # 获取当前最大 ID
    try:
        count = client.count(collection_name=collection).count
        _next_id[0] = count
    except Exception:
        pass
    for i, vec in enumerate(vectors):
        payload = payloads[i] if payloads and i < len(payloads) else {}
        points.append(PointStruct(id=_next_id[0] + i, vector=vec, payload=payload))
    if points:
        client.upsert(collection_name=collection, points=points)


def search(collection, query_vector, top_k=10):
    client = get_client()
    results = client.search(collection_name=collection, query_vector=query_vector, limit=top_k)
    return [(r.payload, r.score) for r in results]


def clear(collection):
    client = get_client()
    if client.collection_exists(collection):
        client.delete_collection(collection_name=collection)
        from qdrant_client.models import Distance, VectorParams
        client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=COLLECTIONS.get(collection, 384), distance=Distance.COSINE),
        )
