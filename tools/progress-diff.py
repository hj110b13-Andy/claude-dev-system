#!/usr/bin/env python3
"""文件瘦身逐句比對（claude-dev-system 通用版；來源 Stock-web scripts/audit/progress-diff.py）。

用途：精簡、搬移、重排任何紀錄檔（PROGRESS、CLAUDE.md、規則檔）後，確認舊版每一句仍存在於新位置，
避免「精簡時把數字、驗收標準、使用者原話刪掉或改掉」。這支工具是拿來「證明沒有遺漏」的，所以寧可多報、不可漏報。

比對方式（0.27.0 起；舊版只做「去掉所有空白後的子字串比對」、把新文跨行拼接，5→15、80→800、日期少一位、句首加「不」都判成找得到）：
  1. 舊文依「。；！？｜」與換行切句（去掉清單／標題符號）；每句正規化：全形轉半形（NFKC）、不分空白多寡、
     去掉逗號冒號括號引號等標點與 Markdown 的 * 和反引號（緊鄰數字的標點保留：1,5 與 15、5.5 與 55 不同）。
  2. 新文以「每一行」為單位（不跨行拼接；句號、驚嘆號、分號、豎線保留成隔開記號，比對不會跨過它）。
  3. 舊句必須在新文某一行裡「整句出現」才算找得到：
     - 整行相同、或被併進更長的句子（前後是句號、逗號、字首字尾、一般文字）→ 找得到。
     - 命中處前面或後面緊鄰數字、小數點、百分號、負號、否定字（不／非／未／無／別／勿／沒；英文 not／no／never／n't）
       且沒有任何一處乾淨的命中 → 「疑似改寫」，要人看（舊句只是新句的一部分，但意思可能被改了）。
     - 完全沒出現 → 「找不到」（遺漏）。
  4. 含數字的短句不略過；沒有數字且少於 --min 字的才略過。

用法（不寫死任何路徑）：
  python progress-diff.py --old-file 舊版.md --new 新版.md [--new 封存.md ...]
  python progress-diff.py --old-ref HEAD --git-path PROGRESS.md --new PROGRESS.md --new PROGRESS-ARCHIVE.md [--repo .]
  其他：--min 6（略過沒有數字的短句字數）、--no-hint、--report 輸出檔（預設不寫檔）
結束碼：0＝全部找得到；1＝有「找不到」或「疑似改寫」；2＝參數錯誤或讀檔失敗（檔案不存在、不是 UTF-8、git 取不到舊版）。
"""
import argparse
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

SPLIT = re.compile(r"[。；！？｜\r\n]")
LEAD = re.compile(r"^\s*(?:[-*]\s+|\d+\.\s+|#+\s+)")
REMOVABLE = set(",、:()[]【】《》〈〉“”\"'‘’…—–·「」『』.")  # 正規化時去掉的標點（緊鄰數字的保留）；。!?;| 是隔開記號，不去掉
ALWAYS_REMOVE = set("*`")  # Markdown 強調與行內程式碼的標記
NEG_CHARS = set("不非未無别別勿沒没无")
ENG_NEG_BEFORE = re.compile(r"(?:^|[^a-z])(?:not|no|never|non|cannot|without)\s?$|n't\s?$", re.I)
ENG_NEG_AFTER = re.compile(r"^\s?(?:not|no|never)(?![a-z])|^n't", re.I)
BOUNDARY = set("\n。!?;|")  # 新文裡一句的邊界（換行與保留下來的句末記號）；命中處兩邊都是邊界才算「整句相同」
DIGITS = set("0123456789")
UNSAFE_CHARS = DIGITS | set(".%-") | NEG_CHARS  # 命中處前後出現這些字 → 疑似改寫


def squash(s: str) -> str:
    """相容舊介面：去掉所有空白。"""
    return re.sub(r"\s+", "", s)


def normalize(s: str) -> str:
    """句子正規化（見模組說明第 1 點）；新文與舊文用同一個函式。"""
    s = unicodedata.normalize("NFKC", s)
    s = "".join(" " if ch in ALWAYS_REMOVE else ch for ch in s)
    s = re.sub(r"\s+", " ", s)
    out = []
    n = len(s)
    for i, ch in enumerate(s):
        if ch in REMOVABLE:
            j = i - 1
            while j >= 0 and s[j] == " ":
                j -= 1
            k = i + 1
            while k < n and s[k] == " ":
                k += 1
            near_digit = (j >= 0 and s[j] in DIGITS) or (k < n and s[k] in DIGITS)
            if not near_digit:
                out.append(" ")
                continue
        out.append(ch)
    s = "".join(out)
    s = re.sub(r" +", " ", s).strip()
    # 空白只留在「兩邊都是英數字」之間（英文單字、數字之間），其餘（中文與任何東西之間）全部去掉
    res = []
    for i, ch in enumerate(s):
        if ch == " ":
            a = s[i - 1] if i > 0 else ""
            b = s[i + 1] if i + 1 < len(s) else ""
            if not (a.isascii() and a.isalnum() and b.isascii() and b.isalnum()):
                continue
        res.append(ch)
    return "".join(res)


def sentences(text: str):
    """舊文的句子：(原文, 正規化)。"""
    for piece in SPLIT.split(text):
        yield piece.strip(), normalize(LEAD.sub("", piece))


@dataclass
class Result:
    total: int = 0
    skipped: int = 0
    exact: int = 0
    merged: int = 0
    missing: list = field(default_factory=list)   # (原文, 正規化)
    suspect: list = field(default_factory=list)   # (原文, 正規化, 原因, 新文脈絡)
    text: str = ""

    @property
    def found(self) -> int:
        return self.exact + self.merged

    @property
    def problems(self) -> int:
        return len(self.missing) + len(self.suspect)


def _unsafe_reason(joined: str, pos: int, end: int):
    """命中 [pos, end) 前後是否緊鄰數字、小數點、百分號、負號、否定字；是就回原因文字，否回 None。"""
    if pos > 0:
        c = joined[pos - 1]
        if c in UNSAFE_CHARS:
            return f"前面緊鄰「{c}」"
        if ENG_NEG_BEFORE.search(joined[max(0, pos - 12):pos]):
            return "前面緊鄰英文否定字"
    if end < len(joined):
        c = joined[end]
        if c in UNSAFE_CHARS:
            return f"後面緊鄰「{c}」"
        if ENG_NEG_AFTER.search(joined[end:end + 8]):
            return "後面緊鄰英文否定字"
    return None


def compare(old: str, new_texts, min_len: int = 6, hint: bool = True) -> Result:
    # 新文：每個檔每一行各自正規化，用換行隔開（舊句裡沒有換行，所以任何命中都不會跨行）
    joined = "\n".join(normalize(LEAD.sub("", ln)) for t in new_texts for ln in re.split(r"\r\n|\r|\n", t))
    res = Result()
    seen = set()
    for raw, s in sentences(old):
        if not s:
            continue
        if len(s) < min_len and not (set(s) & DIGITS):
            res.skipped += 1
            continue
        if s in seen:
            continue
        seen.add(s)
        res.total += 1
        pos = joined.find(s)
        if pos < 0:
            res.missing.append((raw, s))
            continue
        first_reason = first_ctx = None
        status = None
        while pos >= 0:
            end = pos + len(s)
            reason = _unsafe_reason(joined, pos, end)
            if reason is None:
                whole = (pos == 0 or joined[pos - 1] in BOUNDARY) and (end == len(joined) or joined[end] in BOUNDARY)
                status = "exact" if whole else "merged"
                if whole:
                    break
            elif first_reason is None:
                first_reason, first_ctx = reason, joined[max(0, pos - 15):end + 25].replace("\n", "↵")
            pos = joined.find(s, pos + 1)
        if status == "exact":
            res.exact += 1
        elif status == "merged":
            res.merged += 1
        else:
            res.suspect.append((raw, s, first_reason, first_ctx))
    lines = [f"舊版句數（>= {min_len} 字或含數字）{res.total}；略過短句 {res.skipped}；"
             f"找得到 {res.found}（整句相同 {res.exact}、併入更長的句子 {res.merged}）；疑似改寫 {len(res.suspect)}；找不到 {len(res.missing)}"]
    for i, (raw, s) in enumerate(res.missing, 1):
        lines.append(f"[找不到 {i}] {raw[:300]}")
        if hint:
            for tag, key in (("頭", s[:12]), ("尾", s[-12:])):
                p = joined.find(key)
                if p >= 0:
                    lines.append(f"    ({tag}部12字在新文 {p} 處) ...{joined[max(0, p - 10):p + 60]}".replace("\n", "↵"))
    for i, (raw, s, why, ctx) in enumerate(res.suspect, 1):
        lines.append(f"[疑似改寫 {i}] {raw[:300]}")
        lines.append(f"    新文裡這句只是更長句子的一部分，{why}：...{ctx}...")
    res.text = "\n".join(lines)
    return res


def diff(old: str, new_texts, min_len: int = 6, hint: bool = True):
    """相容舊介面：回 (需要人看的句子清單, 報告文字)。清單含「找不到」與「疑似改寫」，每筆 (原文, 正規化)；空清單才是全部找得到。
    要分開統計用 compare()。"""
    r = compare(old, new_texts, min_len, hint)
    return [*r.missing, *[(raw, s) for raw, s, _w, _c in r.suspect]], r.text


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8-sig")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-file")
    ap.add_argument("--old-ref")
    ap.add_argument("--git-path", help="搭配 --old-ref：舊版在 repo 內的路徑")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--new", action="append", default=[], help="改後的檔案（可多次，合併比對）")
    ap.add_argument("--min", type=int, default=6)
    ap.add_argument("--no-hint", action="store_true")
    ap.add_argument("--report")
    a = ap.parse_args()
    if not a.new or not (a.old_file or (a.old_ref and a.git_path)):
        ap.print_usage(sys.stderr)
        return 2
    try:
        if a.old_file:
            old = _read(a.old_file)
        else:
            old = subprocess.run(["git", "show", f"{a.old_ref}:{a.git_path}"], cwd=a.repo,
                                 capture_output=True, check=True).stdout.decode("utf-8-sig")
        new_texts = [_read(p) for p in a.new]
    except (OSError, UnicodeDecodeError, subprocess.CalledProcessError) as e:
        detail = e.stderr.decode("utf-8", "replace").strip() if isinstance(e, subprocess.CalledProcessError) and e.stderr else str(e)
        sys.stderr.write(f"讀檔失敗（不是「有遺漏」，沒有比對）：{detail}\n")
        return 2
    r = compare(old, new_texts, a.min, not a.no_hint)
    if a.report:
        Path(a.report).write_text(r.text, encoding="utf-8")
    sys.stdout.buffer.write((r.text + "\n").encode("utf-8", "replace"))
    return 1 if r.problems else 0


if __name__ == "__main__":
    sys.exit(main())
