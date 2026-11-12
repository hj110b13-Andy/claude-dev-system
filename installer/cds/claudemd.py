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
    if BEGIN_RE.search(text, m.end()):  # IN-10：兩個區塊（例如複製貼上）時只動第一個會留下半套
        raise ValueError("CLAUDE.md 有兩個以上的 claude-dev-system 開始標記，請手動合併成一個區塊（或刪掉多的那個）後再執行")
    end = e + len(END)
    if text[end:end + 2] == chr(13) + chr(10):  # CRLF 檔
        end += 2
    elif text[end:end + 1] == chr(10):
        end += 1
    return m.start(), end


LF, CRLF = chr(10), chr(13) + chr(10)


def newline_of(text: str) -> str:
    """區塊要用的換行：已有區塊就沿用區塊自己的換行；沒有就用檔案的主要換行（CRLF 比單獨的 LF 多才用 CRLF）。
    IN-09：原本「出現一個 CRLF 就整檔視為 CRLF」並把整份檔改寫成同一種換行，混合換行的檔區塊外位元組會變。"""
    r = find_block(text)
    if r:
        return CRLF if CRLF in text[r[0]:r[1]] else LF
    crlf = text.count(CRLF)
    return CRLF if crlf > text.count(LF) - crlf else LF


def block_hash(text: str) -> str | None:
    """雜湊的計算域：以 LF 正規化後的區塊（與 0.27.0 前「整檔先轉 LF 再取區塊」算出的值相同，舊 manifest 的 blockSha256 仍比得上）。"""
    r = find_block(text)
    return sha256_bytes(text[r[0]:r[1]].replace(CRLF, LF).encode("utf-8")) if r else None


def upsert(text: str, block: str, nl: str | None = None) -> tuple[str, str]:
    """回傳 (新文字, 本次在區塊前加的分隔字串)。已有區塊就原位取代（分隔不變，回傳 None 以保留舊紀錄）。
    text 是檔案原文（不轉換換行）；區塊與分隔換成 nl（預設 newline_of），區塊外一個位元組都不動。分隔字串一律以 LF 形式回傳／記錄。"""
    nl = nl or newline_of(text)
    b = block.replace(LF, nl)
    r = find_block(text)
    if r:
        return text[:r[0]] + b + text[r[1]:], None
    if not text:
        return b, ""
    sep = ("" if text.endswith(LF) else LF) + LF
    return text + sep.replace(LF, nl) + b, sep


def remove(text: str, sep: str, nl: str | None = None) -> str:
    r = find_block(text)
    if not r:
        return text
    start, end = r
    s = (sep or "").replace(LF, nl or newline_of(text))  # 分隔是和區塊同一次、用同一種換行寫進去的
    if s and text[max(0, start - len(s)):start] == s:
        start -= len(s)
    return text[:start] + text[end:]
