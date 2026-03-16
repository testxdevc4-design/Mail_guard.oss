"""
apps/bot/formatters.py — Message formatting utilities for MailGuard bot.
"""
from __future__ import annotations

from typing import List

_OK_ICON = "\u2705"   # ✅
_FAIL_ICON = "\u274c"  # ❌


def format_status_line(label: str, ok: bool) -> str:
    """Return a single status line with a checkmark or cross icon.

    Examples
    --------
    >>> format_status_line("Supabase DB", True)
    '✅ Supabase DB'
    >>> format_status_line("Redis", False)
    '❌ Redis'
    """
    icon = _OK_ICON if ok else _FAIL_ICON
    return f"{icon} {label}"


def format_table(headers: List[str], rows: List[List[str]]) -> str:
    """Return a monospaced text table suitable for Telegram messages.

    The table is wrapped in a Markdown code block so Telegram renders it
    in a fixed-width font.

    Parameters
    ----------
    headers:
        Column header strings.
    rows:
        List of rows — each a list of string values (same length as
        *headers*).
    """
    all_rows: List[List[str]] = [headers] + rows
    col_widths = [
        max(len(str(r[i])) for r in all_rows if i < len(r))
        for i in range(len(headers))
    ]

    def _fmt(row: List[str]) -> str:
        cells = [
            str(row[i]).ljust(col_widths[i]) if i < len(row) else " " * col_widths[i]
            for i in range(len(headers))
        ]
        return " | ".join(cells)

    separator = "-+-".join("-" * w for w in col_widths)
    lines = [_fmt(headers), separator, *(_fmt(r) for r in rows)]
    return "```\n" + "\n".join(lines) + "\n```"
