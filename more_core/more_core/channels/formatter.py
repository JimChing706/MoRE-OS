"""Message formatter for channel messages."""

from __future__ import annotations

import re
from typing import Any


class MessageFormatter:
    """Formats messages for different channels."""

    @staticmethod
    def to_markdown(text: str) -> str:
        """Convert text to Markdown format."""
        return text

    @staticmethod
    def from_markdown(text: str, channel_type: str) -> str:
        """Convert Markdown to channel-specific format."""
        if channel_type == "telegram":
            return MessageFormatter._to_telegram(text)
        elif channel_type == "discord":
            return MessageFormatter._to_discord(text)
        elif channel_type == "slack":
            return MessageFormatter._to_slack(text)
        return text

    @staticmethod
    def _to_telegram(text: str) -> str:
        """Convert to Telegram format."""
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
        text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
        text = re.sub(r"__(.+?)__", r"<u>\1</u>", text)
        text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
        text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
        text = re.sub(r"```(\w+)?\n(.+?)```", r"<pre>\2</pre>", text, flags=re.DOTALL)

        text = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', text)

        return text

    @staticmethod
    def _to_discord(text: str) -> str:
        """Convert to Discord format."""
        text = re.sub(r"\*\*(.+?)\*\*", r"**\1**", text)
        text = re.sub(r"\*(.+?)\*", r"*\1*", text)
        text = re.sub(r"__(.+?)__", r"__\1__", text)
        text = re.sub(r"~~(.+?)~~", r"~~\1~~", text)
        text = re.sub(r"`(.+?)`", r"`\1`", text)
        text = re.sub(r"```(\w+)?\n(.+?)```", r"```\2```", text, flags=re.DOTALL)

        text = re.sub(r"\[(.+?)\]\((.+?)\)", r"[\1](\2)", text)

        return text

    @staticmethod
    def _to_slack(text: str) -> str:
        """Convert to Slack format."""
        text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
        text = re.sub(r"\*(.+?)\*", r"_\1_", text)
        text = re.sub(r"~~(.+?)~~", r"~\1~", text)
        text = re.sub(r"`(.+?)`", r"`\1`", text)
        text = re.sub(r"```(\w+)?\n(.+?)```", r"```\2```", text, flags=re.DOTALL)

        text = re.sub(r"\[(.+?)\]\((.+?)\)", r"<\2|\1>", text)

        return text

    @staticmethod
    def truncate(text: str, max_length: int, suffix: str = "...") -> str:
        """Truncate text to max length."""
        if len(text) <= max_length:
            return text
        return text[: max_length - len(suffix)] + suffix

    @staticmethod
    def escape_special_chars(text: str, channel_type: str) -> str:
        """Escape special characters for channel."""
        if channel_type == "telegram":
            text = text.replace("<", "&lt;")
            text = text.replace(">", "&gt;")
            text = text.replace("&", "&amp;")
        elif channel_type == "slack":
            text = text.replace("&", "&amp;")
            text = text.replace("<", "&lt;")
            text = text.replace(">", "&gt;")

        return text

    @staticmethod
    def format_code_block(code: str, language: str = "") -> str:
        """Format code block."""
        return f"```{language}\n{code}\n```"

    @staticmethod
    def format_list(items: list[str], ordered: bool = False) -> str:
        """Format list."""
        if ordered:
            return "\n".join(f"{i + 1}. {item}" for i, item in enumerate(items))
        else:
            return "\n• " + "\n• ".join(items)

    @staticmethod
    def format_table(headers: list[str], rows: list[list[str]]) -> str:
        """Format table."""
        col_widths = [len(h) for h in headers]

        for row in rows:
            for i, cell in enumerate(row):
                col_widths[i] = max(col_widths[i], len(str(cell)))

        def format_row(cells: list[Any]) -> str:
            return " | ".join(str(c).ljust(w) for c, w in zip(cells, col_widths))

        lines = [
            format_row(headers),
            "-+-".join("-" * w for w in col_widths),
        ]

        for row in rows:
            lines.append(format_row(row))

        return "\n".join(lines)
