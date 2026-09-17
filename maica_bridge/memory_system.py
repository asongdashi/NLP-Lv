"""
统一记忆系统 — 无 if-else 架构

核心思想：不为来源类型做任何语义决策。
所有上下文碎片（语义记忆、经历日志、今日事件、自我认知）→ 嵌入向量 → 与用户消息计算余弦相似度 → 按相似度排序 → 从高到低填入 token 预算。

时间/天气/当前活动是"环境上下文"，始终排在首位，不参与竞争。
"""

import os
import json
import time
import logging
import numpy as np

from config import ENABLE_HEALTH_SYNC

logger = logging.getLogger("maica_bridge")

TOKEN_BUDGET = 1500      # 上下文总字符上限
FIXED_BUDGET = 300        # 环境上下文预分配
MEMORY_BUDGET = 1200      # 记忆上下文（从 token 预算扣除固定部分后）
RELEVANCE_THRESHOLD = 0.06 # 相似度低于此值的直接丢弃（multilingual-MiniLM 中文上限 ~0.3-0.4）

# 天气缓存（避免每条消息都调 wttr.in）
_weather_cache = {"text": "", "ts": 0}
_WEATHER_TTL = 600  # 10 分钟缓存


class MemorySystem:
    """get_context() — 调用它，得到一个字符串，没有 if-else 分支。"""

    def __init__(self):
        self._health_data = {}      # APP 上报的最新健康数据
        self._health_updated_at = 0 # 上报时间戳

    def set_health_data(self, data: dict):
        """APP 上报健康数据时调用。"""
        self._health_data = data
        self._health_updated_at = data.get("timestamp", time.time())

    def get_context(self, user_msg: str, session_id: str, is_first: bool = False) -> str:
        # ── 第 1 步：环境上下文 —— 无条件、固定预算 ──
        env_parts = []
        env_parts.append(self._build_time_weather())
        env_parts.append(self._build_current_activity())
        env_parts.append(self._build_health_context())
        background = "\n".join(p for p in env_parts if p)

        # ── 第 2 步：恢复快照 —— 仅首条消息，无条件、固定预算 ──
        resume = ""
        if is_first:
            resume = self._build_resume(session_id)
        if resume:
            if len(background) + len(resume) > FIXED_BUDGET:
                resume = resume[:FIXED_BUDGET - len(background)]
            background += "\n\n" + resume

        # ── 第 3 步：收集所有记忆碎片 —— 不看来源，统一收集 ──
        pieces = []
        pieces.extend(self._collect_semantic_memory(user_msg))   # RAG: [(text, vector)]
        pieces.extend(self._collect_journal_pieces())             # 经历日志: [(text, None)]
        pieces.extend(self._collect_past_event_pieces())          # 今日事件: [(text, None)]
        pieces.extend(self._collect_self_state_pieces())          # 自我认知: [(text, None)]

        if not pieces:
            logger.info(f"[MEM] Context: background only ({len(background)} chars)")
            return background

        # ── 第 4 步：计算每个碎片与用户消息的语义相似度 ──
        scored = self._rank_by_relevance(user_msg, pieces)

        # ── 第 5 步：按相似度从高到低填充记忆预算 ──
        memory_lines = []
        remaining = MEMORY_BUDGET
        for score, text in scored:
            if score < RELEVANCE_THRESHOLD:
                break  # 已排序，后面都比阈值低
            if remaining <= 0:
                break
            if len(text) <= remaining:
                memory_lines.append(text)
                remaining -= len(text)
            else:
                memory_lines.append(text[:remaining])
                remaining = 0

        memory = "\n\n---\n\n".join(memory_lines) if memory_lines else ""
        result = background
        if memory:
            result += "\n\n" + memory

        logger.info(f"[MEM] Context: {len(pieces)} pieces → {len(scored)} scored → "
                    f"{len(memory_lines)} selected → {len(result)} chars")
        return result

    # ==================== 环境上下文（不参与排序） ====================

    def _build_time_weather(self) -> str:
        from datetime import datetime, timezone, timedelta
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)

        hour = now.hour
        feels = (
            "清晨" if 5 <= hour < 8 else "上午" if 8 <= hour < 12 else "中午" if 12 <= hour < 14
            else "下午" if 14 <= hour < 17 else "傍晚" if 17 <= hour < 19 else "晚上" if 19 <= hour < 22
            else "深夜" if 22 <= hour < 23 else "凌晨"
        )
        weekday = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]
        lines = [
            f"【当前时间】北京 {now.strftime('%Y年%m月%d日 %H:%M')} 星期{weekday} ({feels})"
        ]
        try:
            global _weather_cache
            now_ts = time.time()
            if now_ts - _weather_cache["ts"] > _WEATHER_TTL:
                from tools import _get_weather
                from rag.profile_manager import get_location_city
                city = get_location_city() or "东京"
                _weather_cache["text"] = _get_weather(city)
                _weather_cache["ts"] = now_ts
            weather = _weather_cache["text"]
            for line in weather.split("\n"):
                if "当前天气" in line or "気温" in line:
                    lines.append(line + "。")
                    break
        except Exception:
            pass
        return "".join(lines)

    def _build_health_context(self) -> str:
        """从 _health_data 生成健康状态摘要。数据缺失时显式标注 MISSING。"""
        if not ENABLE_HEALTH_SYNC or not self._health_data:
            return ""

        lines = []
        age = time.time() - self._health_updated_at if self._health_updated_at else 0

        # ── 睡眠（每日） ──
        sleep = self._health_data.get("sleep", {})
        sh = sleep.get("total_hours", 0)
        sd = sleep.get("deep_hours", 0)
        if sh > 0:
            deep = f"（深睡 {sd}h）" if sd > 0 else ""
            lines.append(f"🛌 昨晚睡眠 {sh}h{deep}")
        else:
            lines.append("🛌 昨晚睡眠 - 尚未同步")

        # ── 心率趋势（每日） ──
        hr = self._health_data.get("heart_rate", {})
        resting = hr.get("resting", 0)
        trend = hr.get("trend_7d", "")
        if resting > 0 or trend:
            parts = []
            if resting > 0:
                parts.append(f"静息 {resting}")
            if trend:
                icon = {"上升": "📈", "下降": "📉", "持平": "→"}.get(trend, trend)
                parts.append(f"近7天 {icon} {trend}")
            lines.append("💓 " + " ".join(parts))

        # ── 短期快照行 ──
        snap_parts = []
        # 心率
        hr_now = hr.get("current", 0)
        if hr_now > 0:
            flag = ""
            if hr_now > 100:
                flag = " ⚠偏高"
            elif hr_now < 50:
                flag = " ⚠偏低"
            stale = ""
            if age > 600:
                stale = "（{}分钟前）".format(int(age / 60))
            snap_parts.append(f"💓{hr_now}{flag}{stale}")
        else:
            snap_parts.append("💓心率 -")

        # 步数
        steps = self._health_data.get("steps", {})
        st = steps.get("today", 0)
        sg = steps.get("goal", 8000)
        if st > 0:
            pct = int(st / sg * 100) if sg else 0
            snap_parts.append(f"🚶{st}/{sg}（{pct}%）")
        else:
            snap_parts.append("🚶步数 -")

        # 压力
        stress = self._health_data.get("stress", {})
        sl = stress.get("level", "")
        if sl:
            snap_parts.append(f"🧘{sl}")
        else:
            snap_parts.append("🧘压力 -")

        # 血压
        bp = self._health_data.get("blood_pressure", {})
        bp_sys = bp.get("systolic", 0)
        bp_dia = bp.get("diastolic", 0)
        if bp_sys > 0 and bp_dia > 0:
            bp_time = bp.get("last_measured", "")
            bp_time_str = f"（{bp_time}测）" if bp_time else ""
            bp_status = ""
            if bp.get("status") and bp["status"] != "正常":
                bp_status = " ⚠" + bp["status"]
            snap_parts.append(f"🩺{bp_sys}/{bp_dia}{bp_time_str}{bp_status}")
        else:
            snap_parts.append("🩺血压 -")

        lines.append(" | ".join(snap_parts))

        # ── 运动（如有） ──
        ex = self._health_data.get("exercise", {})
        ex_min = ex.get("today_minutes", 0)
        if ex_min > 0:
            ex_type = ex.get("type", "")
            ex_cal = ex.get("today_calories", 0)
            parts = [f"🏃 今日运动 {ex_min}min"]
            if ex_type:
                parts.append(f"（{ex_type}）")
            if ex_cal > 0:
                parts.append(f"{ex_cal}kcal")
            lines.append("".join(parts))

        if not lines:
            return ""

        # 全局 staleness 标注
        header = "健康"
        if age > 1800:
            header += "（{}分钟未更新）".format(int(age / 60))
        return header + ": " + "。".join(lines)

    def _build_current_activity(self) -> str:
        from datetime import datetime
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        now_min = now.hour * 60 + now.minute
        try:
            from storage.api import Storage
            events = Storage().get_daily_events(today)
            if not events:
                return ""
            for ev in events:
                t = ev.get("time", "00:00")
                ev_end = ev.get("end", "")
                act = ev.get("activity", "")
                start_min = _pmin(t)
                end_min = _pmin(ev_end) if ev_end else start_min + 60
                if act == "睡觉" and end_min <= start_min:
                    end_min += 24 * 60
                check = now_min
                if act == "睡觉" and now_min < end_min:
                    check = now_min + 24 * 60
                if start_min <= check < end_min:
                    detail = ev.get("detail", "")
                    desc = f"{act}: {detail}" if detail else act
                    lines = [f"【你正在 {desc}】"]
                    for se in ev.get("sub_events", []):
                        se_min = _pmin(se.get("time", ""))
                        se_check = se_min
                        if act == "睡觉" and se_min < start_min:
                            se_check = se_min + 24 * 60
                        if se_check <= check:
                            lines.append(f"  · {se.get('what', '')}")
                    return "\n".join(lines)
        except Exception:
            pass
        return ""

    def _build_resume(self, session_id: str) -> str:
        try:
            from maica_protocol import get_session_snapshot
            s = get_session_snapshot(session_id)
            if s:
                return f"[恢复] {s}"
        except ImportError:
            pass
        return ""

    # ==================== 收集记忆碎片（不区分来源） ====================

    def _collect_semantic_memory(self, user_msg: str) -> list:
        """RAG 向量检索。返回 [(text, vector), ...]，vector 可能为 None。"""
        pieces = []
        try:
            from rag.rag_manager import get_rag_manager
            rag = get_rag_manager()
            if not rag.is_ready:
                rag.initialize()
            if not rag.is_ready:
                return pieces
            q_vec = self._embed_query(user_msg)
            if q_vec is None:
                return pieces

            for idx in [rag.index_manager.mas_index, rag.index_manager.memory_index, rag.index_manager.corpus_index]:
                if idx is None or idx.is_empty:
                    continue
                results = idx.search(q_vec, k=5)
                for text, score in results:
                    if score >= RELEVANCE_THRESHOLD * 1.2:  # RAG 已有预计算分数
                        pieces.append((text, None))
        except Exception:
            pass
        return pieces

    def _collect_journal_pieces(self) -> list:
        """经历日志，每条作为独立碎片。返回 [(text, None), ...]"""
        pieces = []
        try:
            from rag.journal_manager import get_recent_entries
            entries = get_recent_entries(days=3, max_count=5)
            for e in entries:
                t = e.get("time", "")
                s = e.get("summary", "")
                if s:
                    pieces.append((f"[{t}] {s}", None))
        except Exception:
            pass
        return pieces

    def _collect_past_event_pieces(self) -> list:
        """今日事件，每条作为独立碎片。"""
        pieces = []
        from datetime import datetime
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        now_min = now.hour * 60 + now.minute
        try:
            from storage.api import Storage
            events = Storage().get_daily_events(today)
            if not events:
                return pieces
            for ev in events:
                t = ev.get("time", "00:00")
                ev_end = ev.get("end", "")
                act = ev.get("activity", "")
                detail = ev.get("detail", "")
                start_min = _pmin(t)
                end_min = _pmin(ev_end) if ev_end else start_min + 60
                if act == "睡觉" and end_min <= start_min:
                    end_min += 24 * 60
                check = now_min
                if act == "睡觉" and now_min < end_min:
                    check = now_min + 24 * 60
                if check >= end_min:
                    desc = f"[{t}-{ev_end}] {act}: {detail}" if detail else f"[{t}-{ev_end}] {act}"
                    pieces.append((desc, None))
                    for se in ev.get("sub_events", []):
                        pieces.append((f"  · {se.get('what', '')}", None))
        except Exception:
            pass
        return pieces

    def _collect_self_state_pieces(self) -> list:
        """自我认知，每条作为独立碎片。"""
        pieces = []
        try:
            from storage.api import Storage
            state = Storage().get_all_self_state()
            for _category, items in state.items():
                for key, value in items.items():
                    pieces.append((f"内在: {key}={value}", None))
        except ImportError:
            pass
        return pieces

    # ==================== 相关性排序（纯数学，无 if-else 决策） ====================

    def _rank_by_relevance(self, user_msg: str, pieces: list) -> list:
        """
        pieces: [(text, vector or None), ...]
        返回: [(similarity, text), ...] 按相似度降序排列
        """
        q_vec = self._embed_query(user_msg)
        if q_vec is None:
            # 嵌入失败时，不分排序，原样返回
            return [(1.0, t) for t, _v in pieces]

        scored = []
        for text, pre_vec in pieces:
            try:
                if pre_vec is not None:
                    v = np.array(pre_vec).astype(np.float32)
                else:
                    v = self._embed_text(text)
                if v is None:
                    scored.append((0.0, text))
                    continue
                sim = self._cosine_similarity(q_vec, v)
                scored.append((sim, text))
            except Exception:
                scored.append((0.0, text))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    # ==================== 向量工具 ====================

    def _embed_query(self, text: str):
        try:
            from rag.embedding import get_embedding_model
            embed = get_embedding_model()
            if hasattr(embed, 'encode_query'):
                vec = embed.encode_query(text)
            else:
                vec = embed.encode(text)
            v = np.array(vec).astype(np.float32)
            norm = np.linalg.norm(v)
            return v / norm if norm > 0 else v
        except Exception:
            return None

    def _embed_text(self, text: str):
        try:
            from rag.embedding import get_embedding_model
            embed = get_embedding_model()
            vec = embed.encode(text)
            v = np.array(vec).astype(np.float32)
            norm = np.linalg.norm(v)
            return v / norm if norm > 0 else v
        except Exception:
            return None

    def _cosine_similarity(self, a, b):
        return float(np.dot(a, b))


# ── 工具 ──

def _pmin(t: str) -> int:
    parts = t.split(":")
    if len(parts) >= 2:
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except Exception:
            pass
    return 0
