"""~/.claude/CLAUDE.md 的標記區塊：只動開始／結束標記之間（含標記），區塊外一字不動。"""
from __future__ import annotations

import re

from . import MARK
from .fsio import sha256_bytes

BEGIN_RE = re.compile(r"<!-- " + re.escape(MARK) + r":begin[^\n]*?-->")
END = f"<!-- {MARK}:end -->"


def make_block(body: str, version: str) -> str:
    begin = f"<!-- {MARK}:begin v{version}（此區塊由 claude-dev-system 安裝器管理；區塊外內容不會被改動） -->"
    return f"{begin}\n{body.rstrip()}\n{END}\n"


def find_block(text: str) -> tuple[int, int] | None:
    m = BEGIN_RE.search(text)
    if not m:
        return None
    e = text.find(END, m.end())
    if e < 0:
        raise ValueError("CLAUDE.md 有 claude-dev-system 開始標記但找不到結束標記，請手動修復後再執行")
    end = e + len(END)
    if text[end:end + 2] == chr(13) + chr(10):  # CRLF 檔
        end += 2
    elif text[end:end + 1] == chr(10):
        end += 1
    return m.start(), end


def block_hash(text: str) -> str | None:
    r = find_block(text)
    return sha256_bytes(text[r[0]:r[1]].encode("utf-8")) if r else None


def upsert(text: str, block: str) -> tuple[str, str]:
    """回傳 (新文字, 本次在區塊前加的分隔字串)。已有區塊就原位取代（分隔不變，回傳 None 以保留舊紀錄）。"""
    r = find_block(text)
    if r:
        return text[:r[0]] + block + text[r[1]:], None
    if not text:
        return block, ""
    sep = ("" if text.endswith("\n") else "\n") + "\n"
    return text + sep + block, sep


def remove(text: str, sep: str) -> str:
    r = find_block(text)
    if not r:
        return text
    start, end = r
    if sep and text[max(0, start - len(sep)):start] == sep:
        start -= len(sep)
    return text[:start] + text[end:]
