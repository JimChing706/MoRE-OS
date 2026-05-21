"""Tests for CJK/Unicode compliance across MoRE Core.

Verifies that Chinese, Japanese, and Korean text is handled correctly
in critical paths: difficulty estimation, language detection, memory
search normalization, query length checks, and prompt selection.
"""

from __future__ import annotations

import pytest

from more_core.core.unicode_utils import (
    cjk_ratio,
    detect_language,
    display_width,
    is_cjk_char,
    is_predominantly_cjk,
    is_wide_char,
    normalize_for_search,
    semantic_length,
    truncate_display,
)


# ---- unicode_utils unit tests ----


class TestCJKDetection:
    def test_is_cjk_char_chinese(self):
        assert is_cjk_char("你")
        assert is_cjk_char("好")
        assert is_cjk_char("世")

    def test_is_cjk_char_ascii(self):
        assert not is_cjk_char("A")
        assert not is_cjk_char("1")
        assert not is_cjk_char(" ")

    def test_is_wide_char(self):
        assert is_wide_char("中")
        assert is_wide_char("ア")  # Katakana
        assert not is_wide_char("a")

    def test_cjk_ratio_pure_chinese(self):
        assert cjk_ratio("你好世界") == 1.0

    def test_cjk_ratio_mixed(self):
        ratio = cjk_ratio("hello你好")
        assert 0.2 < ratio < 0.4

    def test_cjk_ratio_empty(self):
        assert cjk_ratio("") == 0.0

    def test_is_predominantly_cjk(self):
        assert is_predominantly_cjk("今天天气真好")
        assert not is_predominantly_cjk("hello world")
        assert is_predominantly_cjk("请用Python写一个函数")


class TestSemanticLength:
    def test_pure_english(self):
        assert semantic_length("hello") == 5

    def test_pure_chinese(self):
        # 4 CJK chars × 2 = 8
        assert semantic_length("你好世界") == 8

    def test_mixed(self):
        # "hello" (5) + "你好" (2×2=4) = 9
        assert semantic_length("hello你好") == 9

    def test_empty(self):
        assert semantic_length("") == 0


class TestDisplayWidth:
    def test_ascii(self):
        assert display_width("hello") == 5

    def test_chinese(self):
        assert display_width("你好") == 4  # 2 chars × 2 cols

    def test_mixed(self):
        assert display_width("hi你好") == 6  # 2 + 4


class TestDetectLanguage:
    def test_chinese(self):
        assert detect_language("请帮我写一段快速排序的代码") == "zh"

    def test_english(self):
        assert detect_language("Please write a quicksort algorithm") == "en"

    def test_mixed_chinese_dominant(self):
        # "请帮我用Python来实现排序" has enough CJK chars (>0.2 ratio)
        assert detect_language("请帮我用Python来实现排序") == "zh"

    def test_empty(self):
        assert detect_language("") == "en"

    def test_japanese(self):
        assert detect_language("こんにちは世界") == "ja"

    def test_korean(self):
        assert detect_language("안녕하세요") == "ko"


class TestNormalizeForSearch:
    def test_fullwidth_to_halfwidth(self):
        # Fullwidth "Ａ" → halfwidth "a" (via NFKC + casefold)
        assert normalize_for_search("Ａ") == "a"

    def test_chinese_preserved(self):
        assert "你好" in normalize_for_search("你好世界")

    def test_casefold(self):
        assert normalize_for_search("Hello") == normalize_for_search("hello")


class TestTruncateDisplay:
    def test_no_truncation(self):
        assert truncate_display("hello", 10) == "hello"

    def test_truncation_ascii(self):
        result = truncate_display("hello world", 8)
        assert result.endswith("…")
        assert display_width(result) <= 8

    def test_truncation_cjk(self):
        result = truncate_display("你好世界测试", 8)
        assert result.endswith("…")
        assert display_width(result) <= 8


# ---- integration: L4 difficulty with CJK ----


class TestL4CJKDifficulty:
    @pytest.fixture
    def settings(self):
        from more_core.core.config import Settings
        return Settings(providers=[], fallback_chain=[])

    @pytest.fixture
    def core(self, settings):
        from more_core.runtime.orchestrator import MoRECore
        return MoRECore(settings)

    @pytest.mark.asyncio
    async def test_chinese_query_higher_difficulty(self, core):
        """A 200-char Chinese query should score higher difficulty than 200-char English
        because semantic_length doubles CJK chars."""
        from more_core.core.types import TaskRequest, TaskType
        from more_core.layers.base import LayerContext
        from more_core.layers.l4_cognition import CognitionLayer

        # 200 CJK chars → semantic_length = 400 → 400//400 = 1 bonus
        chinese_query = "分" * 200
        ctx = LayerContext(core=core, request=TaskRequest(type=TaskType.NLP_TASK, query=chinese_query))
        l4 = CognitionLayer()
        result = await l4.process(ctx)
        # Base NLP difficulty=3, bonus=1 → difficulty=4
        assert result.output["difficulty"] == 4

    @pytest.mark.asyncio
    async def test_english_query_same_length_lower_difficulty(self, core):
        """A 200-char English query → semantic_length=200 → 200//400=0 bonus."""
        from more_core.core.types import TaskRequest, TaskType
        from more_core.layers.base import LayerContext
        from more_core.layers.l4_cognition import CognitionLayer

        english_query = "a" * 200
        ctx = LayerContext(core=core, request=TaskRequest(type=TaskType.NLP_TASK, query=english_query))
        l4 = CognitionLayer()
        result = await l4.process(ctx)
        # Base NLP difficulty=3, semantic_length=200, 200//400=0, so difficulty=3
        assert result.output["difficulty"] == 3


# ---- integration: L0 language detection ----


class TestL0LanguageDetection:
    def test_chinese_system_prompt_selected(self):
        """Chinese queries should trigger the Chinese system prompt."""
        from more_core.layers.l0_execution import _SYSTEM_PROMPTS
        from more_core.core.unicode_utils import detect_language

        query = "请帮我实现一个快速排序算法"
        lang = detect_language(query)
        assert lang == "zh"
        assert "中文" in _SYSTEM_PROMPTS["zh"]

    def test_english_system_prompt_selected(self):
        from more_core.core.unicode_utils import detect_language
        query = "Please implement a quicksort algorithm"
        lang = detect_language(query)
        assert lang == "en"


# ---- integration: memory search normalization ----


class TestMemorySearchCJK:
    def test_fullwidth_halfwidth_match(self):
        """Fullwidth query should match halfwidth content."""
        from more_core.memory.store import MemoryEntry, MemoryKind, MemoryStore

        store = MemoryStore()
        store.put(MemoryEntry(content="Python编程", kind=MemoryKind.SEMANTIC))
        # Search with fullwidth "Ｐython" should still match via NFKC normalization
        results = store.search("Ｐython", kind=MemoryKind.SEMANTIC)
        assert len(results) > 0
        assert "Python" in results[0].content

    def test_chinese_search(self):
        """Direct Chinese search should work."""
        from more_core.memory.store import MemoryEntry, MemoryKind, MemoryStore

        store = MemoryStore()
        store.put(MemoryEntry(content="快速排序算法实现", kind=MemoryKind.SEMANTIC))
        store.put(MemoryEntry(content="二分查找", kind=MemoryKind.SEMANTIC))
        results = store.search("排序", kind=MemoryKind.SEMANTIC)
        assert results[0].content == "快速排序算法实现"


# ---- integration: query length check with CJK ----


class TestQueryLengthCJK:
    @pytest.mark.asyncio
    async def test_cjk_query_length_semantic(self):
        """5001 Chinese chars = 10002 semantic length → should trigger violation."""
        from more_core.ontology.rule_engine import Fact, RuleEngine, default_governance_rules

        engine = RuleEngine()
        for rule in default_governance_rules():
            engine.add_rule(rule)
        # 5001 CJK chars → semantic_length = 10002 > 10000
        long_query = "测" * 5001
        facts = [Fact(kind="request", data={"query": long_query})]
        result = engine.run(facts)
        assert "query exceeds 10 000 chars" in result.violations

    @pytest.mark.asyncio
    async def test_ascii_query_same_char_count_no_violation(self):
        """5001 ASCII chars = 5001 semantic length → should NOT trigger violation."""
        from more_core.ontology.rule_engine import Fact, RuleEngine, default_governance_rules

        engine = RuleEngine()
        for rule in default_governance_rules():
            engine.add_rule(rule)
        short_query = "a" * 5001
        facts = [Fact(kind="request", data={"query": short_query})]
        result = engine.run(facts)
        assert "query exceeds 10 000 chars" not in result.violations
