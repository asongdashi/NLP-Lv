"""
双层记忆管理模块

短期记忆 (Short-term):
  - 每次对话后自动追加
  - 超过天数阈值后，由 LLM 压缩为一条精简摘要
  - 参与 FAISS 被动检索

长期记忆 (Long-term):
  - 由 Monika 通过 save_memory 工具手动保存
  - 永不压缩、永不删除
  - 参与 FAISS 被动检索
"""

import os
import json
import time
import logging

from .config import (
    MEMORY_DIR,
    MEMORY_MAX_ENTRIES,
    MEMORY_FORGET_LAMBDA,
    MEMORY_IMPORTANCE_DECAY,
)

logger = logging.getLogger("maica_bridge.rag")

SHORT_TERM_FILE = os.path.join(MEMORY_DIR, "short_term.json")
SHORT_TERM_ARCHIVE_FILE = os.path.join(MEMORY_DIR, "short_term_archive.json")
LONG_TERM_FILE = os.path.join(MEMORY_DIR, "long_term.json")
SHORT_TERM_MAX_ENTRIES = 100
SHORT_TERM_COMPRESSION_DAYS = 7  # 超过 N 天的条目触发压缩


def _now():
    return time.time()


def _score_by_keyword(content: str, keyword: str, created_at: float = 0) -> float:
    """按关键词匹配度打分（非连续字符匹配 + 时间衰减）。"""
    kw = keyword.strip().lower()
    content_lower = content.lower()

    # 1) 完整子串匹配
    if kw in content_lower:
        score = 1.0 + min(len(kw) * 0.05, 0.3)
    else:
        # 2) 非连续匹配
        pos = 0
        hits = 0
        for ch in kw:
            idx = content_lower.find(ch, pos)
            if idx >= 0:
                hits += 1
                pos = idx + 1
        if hits == 0:
            return 0.0
        hit_ratio = hits / len(kw)
        if hit_ratio < 0.5:
            return 0.0
        score = hit_ratio * 0.7

    # 时间衰减
    age_days = (_now() - created_at) / 86400.0
    time_bonus = max(0, 1.0 - age_days * 0.02)
    score += time_bonus * 0.3

    return score


# ── 短期记忆 ──


class ShortTermMemory:
    """短期记忆：自动追加，定时压缩。"""

    def __init__(self):
        self.entries = []       # [{"content": ..., "created_at": ...}, ...]
        self.archived = []      # 压缩后的归档
        self._load()

    def _load(self):
        os.makedirs(MEMORY_DIR, exist_ok=True)

        # 迁移旧格式
        old_file = os.path.join(MEMORY_DIR, "memory_store.json")
        if not os.path.exists(SHORT_TERM_FILE) and os.path.exists(old_file):
            self._migrate_old(old_file)

        if os.path.exists(SHORT_TERM_FILE):
            try:
                with open(SHORT_TERM_FILE, "r", encoding="utf-8") as f:
                    self.entries = json.load(f)
                logger.info(f"Short-term memory loaded: {len(self.entries)} entries")
            except Exception as e:
                logger.warning(f"Failed to load short-term memory: {e}")
                self.entries = []

        if os.path.exists(SHORT_TERM_ARCHIVE_FILE):
            try:
                with open(SHORT_TERM_ARCHIVE_FILE, "r", encoding="utf-8") as f:
                    self.archived = json.load(f)
            except Exception:
                self.archived = []

    def _migrate_old(self, old_file: str):
        """从旧的 memory_store.json 迁移到短期记忆格式。同时清理旧索引。"""
        try:
            with open(old_file, "r", encoding="utf-8") as f:
                old_entries = json.load(f)
            if isinstance(old_entries, list):
                for e in old_entries:
                    content = e.get("content", "") if isinstance(e, dict) else str(e)
                    created = e.get("created_at", _now()) if isinstance(e, dict) else _now()
                    self.entries.append({
                        "content": content,
                        "created_at": created,
                    })
                logger.info(f"Migrated {len(self.entries)} entries from old memory_store.json")
                # 迁移后删除旧存储文件
                os.remove(old_file)
                # 删除旧 FAISS 索引，迫使下次初始化时重建
                index_dir = os.path.join(os.path.dirname(MEMORY_DIR), "indexes")
                for fname in ["memory.faiss", "memory_texts.json"]:
                    fpath = os.path.join(index_dir, fname)
                    if os.path.exists(fpath):
                        os.remove(fpath)
                        logger.info(f"Removed old index: {fpath}")
        except Exception as e:
            logger.warning(f"Failed to migrate old memory: {e}")

    def _save(self):
        with open(SHORT_TERM_FILE, "w", encoding="utf-8") as f:
            json.dump(self.entries, f, ensure_ascii=False, indent=2)
        with open(SHORT_TERM_ARCHIVE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.archived, f, ensure_ascii=False, indent=2)

    def add(self, content: str):
        """添加一条短期记忆。"""
        self.entries.append({
            "content": content,
            "created_at": _now(),
        })
        logger.debug(f"Short-term memory added: {content[:60]}...")
        self._prune_overflow()
        self._save()

    def get_texts(self) -> list:
        """获取所有条目文本（用于 FAISS 索引）。"""
        return [e["content"] for e in self.entries]

    def get_entries(self) -> list:
        """获取所有条目（dict 格式）。"""
        return list(self.entries)

    def search(self, keyword: str, max_results: int = 3) -> list:
        """按关键词搜索，返回 [(score, content, source_label), ...]"""
        scored = []
        for e in self.entries:
            s = _score_by_keyword(e["content"], keyword, e.get("created_at", 0))
            if s > 0:
                scored.append((s, e["content"][:300], "短期记忆"))
        scored.sort(reverse=True, key=lambda x: x[0])
        return scored[:max_results]

    def compress_if_needed(self, days: int = None):
        """
        压缩超过天数的旧条目。由外部调用（如定时或手动触发）。
        压缩方式：将超时的条目交给 LLM 精简为一条摘要，原条目移入归档。
        """
        if days is None:
            days = SHORT_TERM_COMPRESSION_DAYS

        cutoff = _now() - days * 86400
        old = [e for e in self.entries if e.get("created_at", 0) < cutoff]
        recent = [e for e in self.entries if e.get("created_at", 0) >= cutoff]

        if len(old) <= 1:
            return  # 只有 0-1 条不需要压缩

        # 生成压缩摘要
        old_texts = [e["content"] for e in old]
        summary = self._generate_compression_summary(old_texts)

        # 归档旧条目
        for e in old:
            self.archived.append({
                "content": e["content"],
                "compressed_at": _now(),
            })

        # 写入压缩后摘要
        self.entries = recent
        if summary:
            self.entries.append({
                "content": summary,
                "created_at": _now(),
            })

        logger.info(f"Short-term compression: {len(old)} entries → 1 summary")
        self._save()

    def _generate_compression_summary(self, texts: list) -> str:
        """用 LLM 将多条旧记忆压缩为一条摘要。"""
        # 简单合并，不需要 LLM 调用
        if len(texts) <= 2:
            return "; ".join(texts[:2])

        combined = "; ".join(texts)
        if len(combined) <= 300:
            return f"[压缩记忆] {combined}"

        return f"[压缩记忆] {combined[:280]}..."

    def _prune_overflow(self):
        """超出上限时，压缩最旧的条目。"""
        if len(self.entries) <= SHORT_TERM_MAX_ENTRIES:
            return

        # 按时间排序，最旧的在前面
        self.entries.sort(key=lambda e: e.get("created_at", 0))

        # 取最旧的 20% 条目尝试压缩
        excess = len(self.entries) - SHORT_TERM_MAX_ENTRIES
        remove_count = max(excess, int(SHORT_TERM_MAX_ENTRIES * 0.1))
        old_entries = self.entries[:remove_count]
        self.entries = self.entries[remove_count:]

        for e in old_entries:
            self.archived.append({
                "content": e["content"],
                "compressed_at": _now(),
            })

        logger.info(f"Short-term overflow pruned: {remove_count} entries archived")
        self._save()

    def stats(self) -> dict:
        return {
            "active": len(self.entries),
            "archived": len(self.archived),
        }


# ── 长期记忆 ──


class LongTermMemory:
    """长期记忆：Monika 手动保存，永不压缩/删除。"""

    def __init__(self):
        self.entries = []  # [{"content": ..., "created_at": ..., "source": ...}, ...]
        self._load()

    def _load(self):
        os.makedirs(MEMORY_DIR, exist_ok=True)
        if os.path.exists(LONG_TERM_FILE):
            try:
                with open(LONG_TERM_FILE, "r", encoding="utf-8") as f:
                    self.entries = json.load(f)
                logger.info(f"Long-term memory loaded: {len(self.entries)} entries")
            except Exception as e:
                logger.warning(f"Failed to load long-term memory: {e}")
                self.entries = []

    def _save(self):
        with open(LONG_TERM_FILE, "w", encoding="utf-8") as f:
            json.dump(self.entries, f, ensure_ascii=False, indent=2)

    def add(self, content: str, source: str = "manual"):
        """添加一条长期记忆（永不删除）。"""
        from datetime import datetime, timezone, timedelta
        tz = timezone(timedelta(hours=8))
        time_str = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
        tagged = f"[{time_str}] {content}"

        self.entries.append({
            "content": tagged,
            "created_at": _now(),
            "source": source,
        })
        logger.info(f"Long-term memory saved: {content[:60]}...")
        self._save()

    def get_texts(self) -> list:
        """获取所有条目文本（用于 FAISS 索引）。"""
        return [e["content"] for e in self.entries]

    def get_entries(self) -> list:
        """获取所有条目（dict 格式）。"""
        return list(self.entries)

    def search(self, keyword: str, max_results: int = 3) -> list:
        """按关键词搜索，返回 [(score, content, source_label), ...]"""
        scored = []
        for e in self.entries:
            s = _score_by_keyword(e["content"], keyword, e.get("created_at", 0))
            if s > 0:
                scored.append((s, e["content"][:300], "长期记忆"))
        scored.sort(reverse=True, key=lambda x: x[0])
        return scored[:max_results]

    def stats(self) -> dict:
        return {
            "total": len(self.entries),
        }


# ── 统一 MemoryManager ──


class MemoryManager:
    """统一记忆管理器（保持旧 API 兼容）。"""

    def __init__(self):
        self.short_term = ShortTermMemory()
        self.long_term = LongTermMemory()

    @property
    def entries(self):
        """兼容旧代码：返回空列表（不再直接访问）。"""
        return []

    def get_texts(self) -> list:
        """获取所有记忆文本（用于 FAISS 索引）。短期在前，长期在后。"""
        return self.short_term.get_texts() + self.long_term.get_texts()

    def add_conversation_summary(self, user_msg: str, assistant_reply: str):
        """对话后自动追加到短期记忆（带时间戳）。"""
        from datetime import datetime, timezone, timedelta
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        time_str = now.strftime("%Y-%m-%d %H:%M")
        content = (f"[{time_str}] [对话记忆] "
                   f"玩家: {user_msg[:200]} | Monika: {assistant_reply[:200]}")
        self.short_term.add(content)

    def save_long_term(self, content: str):
        """Monika 手动保存到长期记忆。"""
        self.long_term.add(content, source="manual")
        # 返回更新后的记忆文本列表（供外部重建索引）
        return self.get_texts()

    def search(self, keyword: str, max_per_pool: int = 3) -> str:
        """
        搜索所有记忆池（多阶段检索）：
        1. 关键词召回 (ShortTermMemory.search / LongTermMemory.search)
        2. 时间衰减 (已在 _score_by_keyword 中)
        3. 显著性 + 目标加权 (salience + goal_boost)
        4. 重排序 (加权综合分)
        """
        short_results = self.short_term.search(keyword, max_per_pool)
        long_results = self.long_term.search(keyword, max_per_pool)

        all_results = short_results + long_results
        if not all_results:
            return ""

        # 阶段3-4: 显著性 + 目标加权，重新排序
        boosted = []
        for score, content, source in all_results:
            # Salience boost
            salience_boost = 1.0
            try:
                from cognition.salience import compute as salience_score
                salience_boost = 1.0 + salience_score(content) * 0.3
            except ImportError:
                pass

            # Goal relevance boost
            goal_boost = 1.0
            try:
                from agents.goal_planner import get_priority_boost
                goal_boost = get_priority_boost(content)
            except ImportError:
                pass

            final_score = score * salience_boost * goal_boost
            boosted.append((final_score, content, source, score))

        boosted.sort(reverse=True, key=lambda x: x[0])

        lines = []
        for final, content, source, raw in boosted[:max_per_pool * 2]:
            lines.append(f"[{source}] {content}")

        return "\n\n---\n\n".join(lines)

    def touch_entries(self, indices):
        """兼容旧 API：新系统中为 no-op。"""
        pass

    def decay_unused(self):
        """兼容旧 API：新系统中为 no-op。"""
        pass

    def compress_short_term(self, days: int = None):
        """触发短期记忆压缩。"""
        self.short_term.compress_if_needed(days)

    def stats(self) -> dict:
        return {
            "short_term_active": len(self.short_term.entries),
            "short_term_archived": len(self.short_term.archived),
            "long_term": len(self.long_term.entries),
            "max_short_term": SHORT_TERM_MAX_ENTRIES,
        }
