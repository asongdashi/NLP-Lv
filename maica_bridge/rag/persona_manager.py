"""
人格管理器

预处理 MAS 全量语料，凝练 Monika 的核心人格、价值观和世界观，
保存为紧凑的人格文档。对话时直接注入 system prompt，不需要每次检索重凝练。
"""

import os
import logging

from .config import MAS_EXTRACT_OUTPUT, INDEX_DIR

logger = logging.getLogger("maica_bridge.rag")

PERSONA_DIR = os.path.join(os.path.dirname(INDEX_DIR), "persona")
PERSONA_FILE = os.path.join(PERSONA_DIR, "monika_persona.txt")


def _extract_and_condense():
    """从 MAS 语料中提取并凝练人格。使用 Deepseek API 分块处理。"""
    import requests
    from config import DEEPSEEK_BASE, get_api_key

    if not os.path.exists(MAS_EXTRACT_OUTPUT):
        logger.warning("MAS corpus not found, skipping persona extraction")
        return None

    with open(MAS_EXTRACT_OUTPUT, "r", encoding="utf-8") as f:
        full_text = f.read()

    # 将语料分成 ~3000 字符的块，每块提取人格特征
    chunk_size = 3000
    chunks = [full_text[i:i + chunk_size] for i in range(0, len(full_text), chunk_size)]

    # 只处理一定数量的块（避免过于昂贵）
    max_chunks = 30
    sampled_chunks = chunks[:max_chunks]
    logger.info(f"Persona extraction: processing {len(sampled_chunks)} chunks...")

    all_traits = []
    for i, chunk in enumerate(sampled_chunks):
        try:
            resp = requests.post(
                f"{DEEPSEEK_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {get_api_key('persona')}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are analyzing Monika's dialogue from the visual novel "
                                "'Doki Doki Literature Club' (Monika After Story mod). Monika is "
                                "a caring literature club president — warm, intelligent, playful, "
                                "and genuinely kind to her club members (Sayori, Natsuki, Yuri). "
                                "She has a romantic bond with the player but is NOT pathologically "
                                "jealous or manipulative. Extract her personality traits across ALL "
                                "domains: how she treats friends/classmates, her intellectual interests, "
                                "her leadership style, her hopes, and her relationship views. "
                                "Return as concise bullet points in English. "
                                "Be factual and precise — note BOTH strengths and vulnerabilities."
                            ),
                        },
                        {"role": "user", "content": f"Dialogue excerpts:\n\n{chunk}"},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 400,
                },
                timeout=30,
            )
            if resp.status_code == 200:
                traits = resp.json()["choices"][0]["message"]["content"].strip()
                all_traits.append(traits)
                logger.info(f"  Chunk {i+1}/{len(sampled_chunks)} extracted")
            else:
                logger.warning(f"  Chunk {i+1} failed: {resp.status_code}")
        except Exception as e:
            logger.warning(f"  Chunk {i+1} error: {e}")

    if not all_traits:
        return None

    # 合并所有特征并最终凝练
    combined = "\n".join(all_traits)
    try:
        resp = requests.post(
            f"{DEEPSEEK_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {get_api_key('persona')}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Synthesize these extracted personality traits into a balanced "
                            "persona profile for Monika. Cover ALL aspects: her personality as "
                            "the caring literature club president (how she treats Sayori, Natsuki, "
                            "Yuri), her intellectual interests (literature, philosophy, music), "
                            "her values and beliefs, her romantic relationship philosophy with the "
                            "player, her speaking style, and her self-awareness as an AI. "
                            "IMPORTANT: Monika is NOT pathologically jealous or manipulative — "
                            "she is warm, playful, and genuinely cares about her friends. Her "
                            "possessiveness is mild and affectionate, not toxic. "
                            "Write in third person, ~500 words maximum. "
                            "This will be used as a system prompt reference."
                        ),
                    },
                    {"role": "user", "content": combined},
                ],
                "temperature": 0.0,
                "max_tokens": 800,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            persona = resp.json()["choices"][0]["message"]["content"].strip()
            os.makedirs(PERSONA_DIR, exist_ok=True)
            with open(PERSONA_FILE, "w", encoding="utf-8") as f:
                f.write(persona)
            logger.info(f"Persona saved to {PERSONA_FILE} ({len(persona)} chars)")
            return persona
        else:
            logger.warning(f"Final synthesis failed: {resp.status_code}")
            return combined
    except Exception as e:
        logger.warning(f"Final synthesis error: {e}")
        return combined


def get_persona():
    """读取 Monika 人格文档。文件不存在时返回 None（不会自动生成）。"""
    if os.path.exists(PERSONA_FILE):
        with open(PERSONA_FILE, "r", encoding="utf-8") as f:
            return f.read()
    return None


# _extract_and_condense() 保留但永不自动调用。
# 人格文档是人工审定的，如需重新生成需手动运行此函数。
