"""Unicode & CJK-aware text utilities.

Provides helper functions for correctly handling Chinese/Japanese/Korean
(CJK) text throughout the MoRE Core pipeline — including semantic length
estimation, language detection, and normalization.
"""

from __future__ import annotations

import unicodedata

# CJK Unified Ideographs and common extension blocks
_CJK_RANGES = (
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0x3400, 0x4DBF),  # CJK Extension A
    (0x20000, 0x2A6DF),  # CJK Extension B
    (0x2A700, 0x2B73F),  # CJK Extension C
    (0x2B740, 0x2B81F),  # CJK Extension D
    (0xF900, 0xFAFF),  # CJK Compatibility Ideographs
    (0x2F800, 0x2FA1F),  # CJK Compatibility Supplement
)

# Full-width punctuation and Kana
_FULLWIDTH_RANGES = (
    (0x3000, 0x303F),  # CJK Symbols and Punctuation
    (0xFF00, 0xFFEF),  # Halfwidth and Fullwidth Forms
    (0x3040, 0x309F),  # Hiragana
    (0x30A0, 0x30FF),  # Katakana
    (0xAC00, 0xD7AF),  # Hangul Syllables
)


def is_cjk_char(char: str) -> bool:
    """Return True if *char* is a CJK ideograph."""
    cp = ord(char)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def is_wide_char(char: str) -> bool:
    """Return True if *char* occupies two display columns (CJK, fullwidth)."""
    cp = ord(char)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES + _FULLWIDTH_RANGES)


def cjk_ratio(text: str) -> float:
    """Return the ratio of CJK characters in *text* (0.0–1.0)."""
    if not text:
        return 0.0
    cjk_count = sum(1 for ch in text if is_cjk_char(ch))
    return cjk_count / len(text)


def is_predominantly_cjk(text: str, threshold: float = 0.3) -> bool:
    """Return True if CJK characters exceed *threshold* of total characters."""
    return cjk_ratio(text) >= threshold


def semantic_length(text: str) -> int:
    """Estimate the 'semantic length' of text normalized to English word-equivalents.

    CJK characters convey ~2x the information per character compared to
    Latin script.  This function returns an adjusted length that reflects
    approximate semantic content rather than raw code-point count.

    Examples:
        - "hello world" (11 chars) → 11
        - "你好世界" (4 chars) → 8 (each CJK char ≈ 2 English chars semantically)
    """
    cjk_count = sum(1 for ch in text if is_cjk_char(ch))
    non_cjk_count = len(text) - cjk_count
    return non_cjk_count + cjk_count * 2


def display_width(text: str) -> int:
    """Calculate the terminal display width of *text* (wide chars = 2 cols)."""
    width = 0
    for ch in text:
        if is_wide_char(ch):
            width += 2
        else:
            width += 1
    return width


def detect_language(text: str) -> str:
    """Detect the dominant script/language of *text*.

    Returns one of: "zh" (Chinese-dominant), "ja" (Japanese-dominant),
    "ko" (Korean-dominant), "en" (Latin/English), or "mixed".
    """
    if not text:
        return "en"
    cjk = 0
    kana = 0
    hangul = 0
    latin = 0
    for ch in text:
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in _CJK_RANGES):
            cjk += 1
        elif 0x3040 <= cp <= 0x30FF:
            kana += 1
        elif 0xAC00 <= cp <= 0xD7AF:
            hangul += 1
        elif cp < 0x0100 and ch.isalpha():
            latin += 1
    total = cjk + kana + hangul + latin
    if total == 0:
        return "en"
    if hangul / total > 0.3:
        return "ko"
    if kana / total > 0.2:
        return "ja"
    if cjk / total > 0.2:
        return "zh"
    return "en"


def normalize_for_search(text: str) -> str:
    """Normalize text for search: NFKC normalization + case folding.

    Converts fullwidth ASCII to halfwidth, decomposes compatibility chars,
    and lowercases Latin script — all while preserving CJK ideographs.
    """
    # NFKC: fullwidth → halfwidth, compatibility decomposition + composition
    normalized = unicodedata.normalize("NFKC", text)
    # Case-fold for case-insensitive Latin matching
    return normalized.casefold()


def truncate_display(text: str, max_width: int, suffix: str = "…") -> str:
    """Truncate *text* to fit within *max_width* display columns."""
    width = 0
    suffix_width = display_width(suffix)
    result: list[str] = []
    for ch in text:
        ch_w = 2 if is_wide_char(ch) else 1
        if width + ch_w > max_width - suffix_width:
            result.append(suffix)
            break
        result.append(ch)
        width += ch_w
    else:
        return text  # no truncation needed
    return "".join(result)
