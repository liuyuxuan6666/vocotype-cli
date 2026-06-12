"""Text post-processing: filler removal and retraction correction."""

from __future__ import annotations

import logging
import re


logger = logging.getLogger(__name__)

_FILLERS = frozenset({"嗯", "啊", "呃", "哦", "嘛", "吖", "唷"})
_CHINESE_PUNCT = frozenset("，。！？；、：""''（）【】《》")


# ---------------------------------------------------------------------------
# Filler removal
# ---------------------------------------------------------------------------

def remove_fillers(text: str) -> str:
    """Remove common Chinese hesitation sounds (嗯啊呃哦嘛)."""
    if not text:
        return text
    fc = "".join(_FILLERS)

    text = re.sub(f"^[{fc}]+", "", text)
    text = re.sub(f"[{fc}]+(?=[，。！？；、])", "", text)
    text = re.sub(f"(?<=[，。！？；、])[{fc}]+", "", text)
    text = re.sub(f"[{fc}]+$", "", text)

    # Clean orphaned / double punctuation
    text = re.sub(r"^[，。；、]+", "", text)
    text = re.sub(r"([，。！？；、])\1+", r"\1", text)
    text = re.sub(r"[，。；、]+$", "", text)

    return text.strip()


# ---------------------------------------------------------------------------
# Utils
# ---------------------------------------------------------------------------

def _strip_punct(s: str) -> str:
    """Remove trailing/leading Chinese punctuation for clean comparison."""
    return s.strip().rstrip("".join(_CHINESE_PUNCT)).lstrip("".join(_CHINESE_PUNCT)).strip()


# ---------------------------------------------------------------------------
# Retraction / false-start correction
# ---------------------------------------------------------------------------

def fix_retractions(text: str) -> str:
    """Detect and correct speech retractions and false starts.

    Handles:
      重复词       "那个那个"          → "那个"        (in-segment word dedup)
      短片段修正   "我今，我们今天"    → "我们今天"    (chars spread-match)
    """
    if not text:
        return text

    # Stage 1: in-segment duplicate word dedup (2-4 char words)
    text = re.sub(r"(([\u4e00-\u9fff]{2,4})\2)", r"\2", text)

    # Stage 2: cross-segment (split by Chinese punctuation)
    parts = re.split(r"(?<=[，。！？；、])", text)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) < 2:
        return text

    merged = [parts[0]]
    for i in range(1, len(parts)):
        prev = merged[-1]
        curr = parts[i]

        if _is_retraction(prev, curr):
            logger.debug("修正说错: '%s' → 保留 '%s'", prev, curr)
            merged[-1] = curr
        else:
            merged.append(curr)

    return "".join(merged)


def _is_retraction(prev: str, curr: str) -> bool:
    p = _strip_punct(prev)
    c = _strip_punct(curr)
    if not p or not c:
        return False

    if p == c:
        return True

    # p is exact prefix of c: "不是不是" → c.startswith("不是不是")?
    if c.startswith(p) and len(p) >= 2:
        return True

    # Short false start (≤3 chars) + fuzzy char-in-order match
    # "我今，我们今天" → "我今" chars "我"+"今" both appear in order in "我们今天" → retraction
    # "我去，我回来了" → "我去" chars "我"+"去" → "去" NOT in "我回来了" → not retraction
    if len(p) <= 3 and p[0] == c[0]:
        check_window = c[:len(p) + 2]
        idx = 0
        for ch in p:
            pos = check_window.find(ch, idx)
            if pos < 0:
                return False
            idx = pos + 1
        return True

    return False


# ---------------------------------------------------------------------------
# Combined entry point
# ---------------------------------------------------------------------------

def postprocess(text: str, remove_fillers_flag: bool = True, fix_retractions_flag: bool = True) -> str:
    if not text:
        return text
    if remove_fillers_flag:
        text = remove_fillers(text)
    if fix_retractions_flag:
        text = fix_retractions(text)
    return text.strip()