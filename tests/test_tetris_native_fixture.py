import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'more_core'))

from more_core.core.native_executor.tetris_original_prompt import TETRIS_ORIGINAL_LAUNCH_PROMPT


def test_tetris_prompt_min_length():
    assert len(TETRIS_ORIGINAL_LAUNCH_PROMPT) >= 3000, (
        f"TETRIS_ORIGINAL_LAUNCH_PROMPT 长度不足 3000 字符，实际长度: {len(TETRIS_ORIGINAL_LAUNCH_PROMPT)}"
    )


def test_tetris_prompt_first_40_chars():
    expected_start = "通过『任务导入』机制启动并持续推进俄罗斯方块"
    actual_start = TETRIS_ORIGINAL_LAUNCH_PROMPT[:len(expected_start)]
    assert TETRIS_ORIGINAL_LAUNCH_PROMPT.startswith(expected_start), (
        f"TETRIS_ORIGINAL_LAUNCH_PROMPT 开头不匹配\n"
        f"期望开头: {repr(expected_start)}\n"
        f"实际开头: {repr(actual_start)}"
    )
