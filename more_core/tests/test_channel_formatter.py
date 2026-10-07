"""渠道消息格式化测试（channels/formatter.py 覆盖补齐）。

顺带修复：D-9 telegram 二次转义 / D-10 truncate 超出上限 / D-11 空列表多余符号。
"""

from __future__ import annotations

import pytest

from more_core.channels.formatter import MessageFormatter as F


# ---------------------------------------------------------------------------
# Markdown 基础
# ---------------------------------------------------------------------------


def test_to_markdown_passthrough():
    assert F.to_markdown("hello") == "hello"


@pytest.mark.parametrize("channel", ["telegram", "discord", "slack", "unknown"])
def test_from_markdown_dispatch(channel):
    assert F.from_markdown("plain", channel) == "plain"


@pytest.mark.parametrize(
    "src,expected",
    [
        ("**b**", "<b>b</b>"),
        ("*i*", "<i>i</i>"),
        ("__u__", "<u>u</u>"),
        ("~~s~~", "<s>s</s>"),
        ("`c`", "<code>c</code>"),
        ("[t](https://x)", '<a href="https://x">t</a>'),
    ],
)
def test_telegram_conversions(src, expected):
    assert F.from_markdown(src, "telegram") == expected


def test_telegram_code_block():
    """回归 D-12：围栏代码块此前被内联 ` 规则拆坏成 <code>`</code>python…。"""
    out = F.from_markdown("```python\nprint(1)\n```", "telegram")
    assert out == "<pre>print(1)\n</pre>"
    assert "```" not in out


def test_discord_conversions():
    assert F.from_markdown("**b**", "discord") == "**b**"
    assert F.from_markdown("[t](https://x)", "discord") == "[t](https://x)"


@pytest.mark.parametrize("channel", ["discord", "slack"])
def test_fenced_code_block_preserves_language(channel):
    """回归 D-12/D-14：围栏代码块此前丢失语言标签。"""
    out = F.from_markdown("```python\nprint(1)\n```", channel)
    assert out == "```python\nprint(1)\n```"


def test_slack_conversions():
    """回归 D-13：Slack 粗体此前被斜体规则二次改写为 _b_。"""
    assert F.from_markdown("**b**", "slack") == "*b*"
    assert F.from_markdown("*i*", "slack") == "_i_"
    assert F.from_markdown("**b** and *i*", "slack") == "*b* and _i_"
    assert F.from_markdown("[t](https://x)", "slack") == "<https://x|t>"


# ---------------------------------------------------------------------------
# 转义（D-9）
# ---------------------------------------------------------------------------


def test_telegram_escape_does_not_double_escape():
    """回归 D-9：< 必须先转成 &lt;、且 & 不能再被二次转义。"""
    assert F.escape_special_chars("a < b & c", "telegram") == "a &lt; b &amp; c"
    assert F.escape_special_chars("x > y", "telegram") == "x &gt; y"


def test_slack_escape():
    assert F.escape_special_chars("a < b & c", "slack") == "a &lt; b &amp; c"


def test_unknown_channel_escape_is_noop():
    assert F.escape_special_chars("a < b & c", "irc") == "a < b & c"


# ---------------------------------------------------------------------------
# 截断（D-10）
# ---------------------------------------------------------------------------


def test_truncate_basic():
    assert F.truncate("hello", 10) == "hello"
    assert F.truncate("hello world", 8) == "hello..."
    assert F.truncate("hello", 5) == "hello"


def test_truncate_never_exceeds_max_length():
    """回归 D-10：max_length 小于后缀长度时结果仍不得超过上限。"""
    out = F.truncate("abcdef", 2)
    assert len(out) <= 2 and out == "ab"
    assert len(F.truncate("abcdef", 3)) <= 3
    assert F.truncate("abcdef", 0) == ""
    assert F.truncate("abcdef", -1) == ""


def test_truncate_custom_suffix():
    assert F.truncate("hello world", 7, suffix="…") == "hello …"


# ---------------------------------------------------------------------------
# 代码块 / 列表 / 表格
# ---------------------------------------------------------------------------


def test_format_code_block():
    assert F.format_code_block("x=1", "python") == "```python\nx=1\n```"
    assert F.format_code_block("x=1") == "```\nx=1\n```"


def test_format_list_unordered_and_ordered():
    assert F.format_list(["a", "b"]) == "\n• a\n• b"
    assert F.format_list(["a", "b"], ordered=True) == "1. a\n2. b"


def test_format_list_empty_has_no_stray_bullet():
    """回归 D-11：空列表此前返回 '\\n• '。"""
    assert F.format_list([]) == ""
    assert F.format_list([], ordered=True) == ""


def test_format_table_aligns_columns():
    out = F.format_table(["a", "bb"], [["1", "2"], ["333", "4"]])
    lines = out.split("\n")
    assert len(lines) == 4  # 表头 + 分隔 + 2 行
    assert lines[0].startswith("a")
    assert "---" in lines[1]
    # 每列宽度取该列最大值
    assert lines[0] == "a   | bb"
    assert lines[2].startswith("1")
    assert lines[3].startswith("333")
