"""
MAS 语料提取器

从 MAS_MonikaAfterStory/game 的原始 .rpy 源文件中提取 Monika 对话。
同时合并 MAICA 子模组的 chat.rpy 对话。
"""

import os
import re
import hashlib
import logging

from .config import MAS_CORPUS_DIR, MAS_EXTRACT_OUTPUT, CHUNK_SIZE, CHUNK_OVERLAP

logger = logging.getLogger("maica_bridge.rag")

# MAS 源码目录
MAS_SOURCE_DIR = r"E:\MAS2\MonikaAfterStory\game"

# MAICA 子模组目录
MAICA_SUBMOD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def find_rpy_files(directory):
    """递归搜索所有 .rpy 对话文件。"""
    files = []
    for root, _, fnames in os.walk(directory):
        for fn in fnames:
            if fn.endswith(".rpy") and os.path.getsize(os.path.join(root, fn)) > 1000:
                files.append(os.path.join(root, fn))
    return sorted(files)


# ── Monika say 语句匹配 ──
SAY_PATTERNS = [
    re.compile(r'^\s*m\s+\S+\s+"(.+?)"[ \t]*(?:#.*)?$'),
    re.compile(r"^\s*m\s+\S+\s+\'(.+?)\'[ \t]*(?:#.*)?$"),
]
EXTEND_PATTERNS = [
    re.compile(r'^\s*extend\s+\S*\s*"(.+?)"'),
    re.compile(r"^\s*extend\s+\S*\s*\'(.+?)\'"),
]

# Ren'Py 标记
TAG_CLEANUP = [
    (re.compile(r'\{w=[^}]*\}'), ''),
    (re.compile(r'\{nw\}'), ''),
    (re.compile(r'\{/?[ibus]\}'), ''),
    (re.compile(r'\{/?sc\}'), ''),
    (re.compile(r'\{/?rt\}'), ''),
    (re.compile(r'\{/?rb\}'), ''),
    (re.compile(r'\{/?font\}'), ''),
    (re.compile(r'\{a=[^}]*\}'), ''),
    (re.compile(r'\{/a\}'), ''),
    (re.compile(r'\{p=[^}]*\}'), ''),
    (re.compile(r'\{clear\}'), ''),
    (re.compile(r'\{v?space=[^}]*\}'), ''),
    (re.compile(r'\{(?:\d+)?image=[^}]*\}'), ''),
    (re.compile(r'\{cps=[^}]*\}'), ''),
    (re.compile(r'\{/cps\}'), ''),
]

VAR_REPLACE = [
    (re.compile(r'\[player\]'), '{player}'),
    (re.compile(r'\[m_name\]'), 'Monika'),
    (re.compile(r'\[mas_curr_date\]'), '{date}'),
    (re.compile(r'\[current_user\]'), '{user}'),
]


def clean_dialogue(text):
    for pat, repl in TAG_CLEANUP:
        text = pat.sub(repl, text)
    for pat, repl in VAR_REPLACE:
        text = pat.sub(repl, text)
    text = text.replace('\\"', '"').replace("\\'", "'").replace('\\n', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def extract_from_file(filepath):
    dialogues = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return dialogues

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        for pat in SAY_PATTERNS + EXTEND_PATTERNS:
            m = pat.match(line)
            if m:
                text = clean_dialogue(m.group(1))
                if text and len(text) >= 4 and not text.startswith("_"):
                    dialogues.append(text)
                break
    return dialogues


def extract_and_save():
    # 收集所有源文件
    all_files = []

    if os.path.isdir(MAS_SOURCE_DIR):
        mas_files = find_rpy_files(MAS_SOURCE_DIR)
        logger.info(f"MAS source: {len(mas_files)} .rpy files")
        all_files.extend(mas_files)
    else:
        logger.warning(f"MAS source not found: {MAS_SOURCE_DIR}")

    if os.path.isdir(MAICA_SUBMOD_DIR):
        maica_files = find_rpy_files(MAICA_SUBMOD_DIR)
        logger.info(f"MAICA submod: {len(maica_files)} .rpy files")
        all_files.extend(maica_files)

    # 只处理对话相关文件
    dialogue_files = [fp for fp in all_files
                      if any(k in os.path.basename(fp)
                             for k in ["script", "chat", "trigger", "heaven", "forest", "introduction",
                                       "farewells", "greetings", "holidays", "stories", "compliments",
                                       "moods", "fun-facts", "songs", "affection", "easter-eggs"])]

    logger.info(f"Processing {len(dialogue_files)} dialogue files")

    all_texts = []
    for fp in dialogue_files:
        name = os.path.basename(fp)
        dlgs = extract_from_file(fp)
        if dlgs:
            logger.info(f"  {name}: {len(dlgs)} lines")
            all_texts.extend(dlgs)

    # 去重
    seen = set()
    unique = []
    for d in all_texts:
        h = hashlib.md5(d.encode("utf-8")).hexdigest()
        if h not in seen:
            seen.add(h)
            unique.append(d)

    logger.info(f"Unique dialogue lines: {len(unique)}")

    # 切块
    full = "\n".join(unique)
    chunks = []
    for i in range(0, len(full), CHUNK_SIZE - CHUNK_OVERLAP):
        chunk = full[i:i + CHUNK_SIZE].strip()
        if chunk:
            chunks.append(chunk)

    os.makedirs(MAS_CORPUS_DIR, exist_ok=True)
    with open(MAS_EXTRACT_OUTPUT, "w", encoding="utf-8") as f:
        f.write("\n\n---\n\n".join(chunks))

    logger.info(f"Saved {len(chunks)} chunks to {MAS_EXTRACT_OUTPUT}")
    return MAS_EXTRACT_OUTPUT


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    extract_and_save()
