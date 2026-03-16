"""
tests/test_bot_formatters.py — Unit tests for apps/bot/formatters.py.
"""
from __future__ import annotations

import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "testkey")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("ENCRYPTION_KEY", "a" * 64)
os.environ.setdefault("JWT_SECRET", "b" * 64)
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test:token")
os.environ.setdefault("TELEGRAM_ADMIN_UID", "1")
os.environ.setdefault("ENV", "development")

from apps.bot.formatters import format_status_line, format_table  # noqa: E402


# ---------------------------------------------------------------------------
# format_status_line
# ---------------------------------------------------------------------------

def test_format_status_line_ok() -> None:
    line = format_status_line("Supabase DB", True)
    assert "\u2705" in line
    assert "Supabase DB" in line


def test_format_status_line_fail() -> None:
    line = format_status_line("Redis", False)
    assert "\u274c" in line
    assert "Redis" in line


def test_format_status_line_ok_not_fail() -> None:
    ok_line = format_status_line("X", True)
    fail_line = format_status_line("X", False)
    assert ok_line != fail_line


def test_format_status_line_no_cross_when_ok() -> None:
    line = format_status_line("Bot", True)
    assert "\u274c" not in line


def test_format_status_line_no_check_when_fail() -> None:
    line = format_status_line("API", False)
    assert "\u2705" not in line


# ---------------------------------------------------------------------------
# format_table
# ---------------------------------------------------------------------------

def test_format_table_contains_headers() -> None:
    result = format_table(["Name", "Status"], [["Alice", "active"]])
    assert "Name" in result
    assert "Status" in result


def test_format_table_contains_rows() -> None:
    result = format_table(["Col"], [["hello"], ["world"]])
    assert "hello" in result
    assert "world" in result


def test_format_table_has_separator() -> None:
    result = format_table(["A", "B"], [["1", "2"]])
    assert "-" in result
    assert "|" in result


def test_format_table_is_code_block() -> None:
    result = format_table(["H"], [["v"]])
    assert result.startswith("```")
    assert result.endswith("```")


def test_format_table_empty_rows() -> None:
    result = format_table(["H1", "H2"], [])
    assert "H1" in result
    assert "H2" in result


def test_format_table_multiple_rows() -> None:
    headers = ["ID", "Email", "Provider"]
    rows = [
        ["1", "a@gmail.com", "Gmail"],
        ["2", "b@yahoo.com", "Yahoo"],
    ]
    result = format_table(headers, rows)
    assert "Gmail" in result
    assert "Yahoo" in result
    assert "Email" in result


def test_format_table_columns_aligned() -> None:
    """All rows should have the same number of separator characters."""
    result = format_table(["Name", "Value"], [["short", "x"], ["longervalue", "y"]])
    data_lines = [line for line in result.split("\n") if "|" in line]
    pipe_counts = [line.count("|") for line in data_lines]
    assert len(set(pipe_counts)) == 1, "All data rows must have the same pipe count"
