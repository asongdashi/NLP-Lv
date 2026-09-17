#!/bin/bash
# ============================================
# Monika 重置脚本
# 用法:
#   bash reset_monika.sh today     # 重置今天
#   bash reset_monika.sh week      # 重置本周
#   bash reset_monika.sh month     # 重置本月
#   bash reset_monika.sh allinall  # 完全重置（极其危险）
# ============================================

cd "$(dirname "$0")"
SCOPE="${1}"

case "$SCOPE" in
    today)   LABEL="今天"; CUTOFF=$(date +%Y-%m-%d) ;;
    week)    LABEL="本周 (7天)"; CUTOFF=$(python -c "from datetime import datetime,timedelta; print((datetime.now()-timedelta(days=7)).strftime('%Y-%m-%d'))") ;;
    month)   LABEL="本月 (30天)"; CUTOFF=$(python -c "from datetime import datetime,timedelta; print((datetime.now()-timedelta(days=30)).strftime('%Y-%m-%d'))") ;;
    allinall) LABEL="⚠️  完全重置（所有记忆、日志、情绪、自我认知、室友关系）"; CUTOFF="" ;;
    *)
        echo "=== Monika 重置脚本 ==="
        echo ""
        echo "用法: bash reset_monika.sh <范围>"
        echo ""
        echo "  范围:"
        echo "    today      — 只清今天的数据（日程 + 聊天）"
        echo "    week       — 清最近 7 天"
        echo "    month      — 清最近 30 天"
        echo "    allinall   — 完全重置（所有记忆、认知、情绪、关系）"
        echo ""
        exit 1
        ;;
esac

echo "============================================"
echo "  Monika 重置 — $LABEL"
echo "============================================"
echo ""

if [ "$SCOPE" = "allinall" ]; then
    echo "此操作将清除:"
    echo "  • SQLite 全部运行时表"
    echo "    self_state / beliefs / goals / life_events"
    echo "    emotion_events / reflections / long_term_memory"
    echo "    short_term_memory / chat_messages"
    echo "  • FAISS 向量索引 + Qdrant"
    echo "  • 全部聊天记录 (chat_logs)"
    echo "  • 全部记忆 (short_term / long_term)"
    echo "  • 全部对话经历 (journals)"
    echo "  • 全部每日事件日志 (daily)"
    echo "  • 情绪状态、自我认知、室友关系、目标"
    echo "  • 人格文档 (persona)"
    echo ""
    echo "保留:"
    echo "  • world.json / habits.json / characters.json"
    echo "  • timeline.json / config.json"
else
    echo "此操作将清除 (>= $CUTOFF):"
    echo "  • SQLite: life_events, chat_messages"
    echo "  • 聊天记录 (chat_logs)"
    echo "  • 对话经历 (journals)"
    echo "  • 每日事件日志 (daily)"
fi
echo ""

# ── 确认 ──
read -p "确认执行？输入 YES 继续: " CONFIRM
if [ "$CONFIRM" != "YES" ]; then
    echo "已取消。"
    exit 0
fi

echo ""
echo ">>> 开始执行..."

# ── 1. SQLite ──
echo "[1/5] SQLite..."
if [ "$SCOPE" = "allinall" ]; then
    python -c "
import sqlite3
db = sqlite3.connect('maica_bridge/data/maica_data.db')
tables = [
    'self_state','beliefs','goals','life_events',
    'emotion_events','reflections','long_term_memory',
    'short_term_memory','chat_messages'
]
for t in tables:
    db.execute(f'DELETE FROM {t}')
db.execute('DELETE FROM sqlite_sequence')
db.commit()
db.close()
print(f'  全部 {len(tables)} 张表已清空（含自增序列）')
"
else
    python -c "
import sqlite3
db = sqlite3.connect('maica_bridge/data/maica_data.db')
db.execute('DELETE FROM life_events WHERE date >= ?', ('$CUTOFF',))
db.execute('DELETE FROM chat_messages WHERE timestamp >= ?', ('$CUTOFF',))
db.commit()
db.close()
print(f'  life_events + chat_messages >= $CUTOFF 已清空')
"
fi

# ── 2. FAISS + Qdrant ──
echo "[2/5] 向量索引..."
if [ "$SCOPE" = "allinall" ]; then
    rm -rf maica_bridge/data/qdrant
    rm -f maica_bridge/data/indexes/*.faiss
    rm -f maica_bridge/data/indexes/*_texts.json
    rm -f maica_bridge/data/indexes/embedding_type.txt
    echo "  已清空 (FAISS + Qdrant)"
else
    echo "  跳过（部分重置不清理向量索引）"
fi

# ── 3. JSONL / JSON 运行时文件 ──
echo "[3/5] 运行时文件..."
if [ "$SCOPE" = "allinall" ]; then
    # 聊天记录
    rm -f maica_bridge/data/chat_logs/*.jsonl
    # 记忆
    rm -f maica_bridge/memory/short_term.json
    rm -f maica_bridge/memory/long_term.json
    rm -f maica_bridge/memory/short_term_archive.json
    rm -f maica_bridge/memory/memory_archive.json
    # 经历
    rm -f maica_bridge/journals/experience.jsonl
    rm -f maica_reality/data/journals/experience.jsonl
    # 状态
    rm -f maica_reality/data/life/state.json
    rm -f maica_reality/data/state/last_weather.json
    rm -f maica_reality/data/state/cared_topics.json
    rm -f maica_reality/data/self/*.json
    # 每日事件日志
    rm -f maica_reality/data/life/daily/*.json
    # 人格（下次启动时从 MAS 语料手动重新生成，或保留空文件）
    rm -f maica_bridge/rag/persona/monika_persona.txt
    echo "  全部运行时文件已清理"
else
    # journal (按行过滤)
    for jp in maica_bridge/journals/experience.jsonl maica_reality/data/journals/experience.jsonl; do
        if [ -f "$jp" ]; then
            python -c "
import json
with open('$jp','r',encoding='utf-8') as f:
    lines = f.readlines()
cutoff = '$CUTOFF'
kept = []
for line in lines:
    if not line.strip(): continue
    try:
        e = json.loads(line)
        if e.get('time','')[:10] < cutoff: kept.append(line)
    except: kept.append(line)
with open('$jp','w',encoding='utf-8') as f:
    f.writelines(kept)
print(f'  Journal: 保留 {len(kept)}/{len(lines)} 条')
"
        fi
    done
    # chat_logs
    for f in maica_bridge/data/chat_logs/*.jsonl; do
        [ -e "$f" ] || continue
        base=$(basename "$f" .jsonl)
        if [ "$base" \> "$CUTOFF" ] || [ "$base" = "$CUTOFF" ]; then
            rm -f "$f"
        fi
    done
    # daily events
    for f in maica_reality/data/life/daily/*.json; do
        [ -e "$f" ] || continue
        base=$(basename "$f" .json)
        if [ "$base" \> "$CUTOFF" ] || [ "$base" = "$CUTOFF" ]; then
            rm -f "$f"
        fi
    done
    echo "  chat_logs + daily >= $CUTOFF 已清空"
fi

# ── 4. 确保关键目录存在 ──
echo "[4/5] 重建目录..."
mkdir -p maica_bridge/data/chat_logs
mkdir -p maica_bridge/data/indexes
mkdir -p maica_bridge/data/qdrant
mkdir -p maica_bridge/memory
mkdir -p maica_bridge/journals
mkdir -p maica_bridge/rag/persona
mkdir -p maica_reality/data/life/daily
mkdir -p maica_reality/data/life/weekly
mkdir -p maica_reality/data/life/monthly
mkdir -p maica_reality/data/state
echo "  目录已就绪"

# ── 5. 重置 state.json（非 allinall 时） ──
echo "[5/5] 状态..."
if [ "$SCOPE" != "allinall" ]; then
    # 用保留的最早 life_events 日期更新 last_known_date
    python -c "
import sqlite3, json, os
db = sqlite3.connect('maica_bridge/data/maica_data.db')
row = db.execute('SELECT MAX(date) as d FROM life_events').fetchone()
if row and row[0]:
    last = row[0]
else:
    from datetime import datetime
    last = (datetime.now().strftime('%Y-%m-%d'))
sf = 'maica_reality/data/life/state.json'
os.makedirs(os.path.dirname(sf), exist_ok=True)
with open(sf, 'w') as f:
    json.dump({'last_known_date': last}, f)
print(f'  state.json → last_known_date = {last}')
db.close()
"
fi

echo ""
echo "=== 重置完成 ($LABEL) ==="
echo ""
if [ "$SCOPE" = "allinall" ]; then
    echo "核心设定 (world.json / habits.json / characters.json / timeline.json / config.json) 未受影响。"
    echo "下次启动时会自动从 JSON 文件重建默认数据、重新构建 RAG 索引。"
else
    echo "状态已更新，生成器下次运行将识别到最新日期。"
fi
