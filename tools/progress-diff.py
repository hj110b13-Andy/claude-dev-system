#!/usr/bin/env python3
"""文件瘦身逐句比對（claude-dev-system 通用版；來源 Stock-web scripts/audit/progress-diff.py）。

用途：精簡、搬移、重排任何紀錄檔（PROGRESS、CLAUDE.md、規則檔）後，確認舊版每一句仍存在於新位置，
避免「精簡時把數字、驗收標準、使用者原話刪掉」。
把「改前」文字依「。；！？｜」與換行切句，去除空白後，檢查每句是否為「改後所有檔案合併文字」（同樣去空白）的子字串。

用法（不寫死任何路徑）：
  python progress-diff.py --old-file 舊版.md --new 新版.md [--new 封存.md ...]
  python progress-diff.py --old-ref HEAD --git-path PROGRESS.md --new PROGRESS.md --new PROGRESS-ARCHIVE.md [--repo .]
  其他：--min 6（略過短句字數）、--no-hint、--report 輸出檔（預設不寫檔）
結束碼：0＝全部找得到；1＝有找不到的句子；2＝參數錯誤。
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

SPLIT = re.compile(r"[。；！？｜\r\n]")
LEAD = re.compile(r"^\s*(?:[-*]\s+|\d+\.\s+|#+\s+)")


def squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def sentences(text: str):
    for piece in SPLIT.split(text):
        yield piece.strip(), squash(LEAD.sub("", piece))


def diff(old: str, new_texts, min_len: int = 6, hint: bool = True):
    new_sq = squash("\n".join(new_texts))
    skipped = total = 0
    missing, seen = [], set()
    for raw, s in sentences(old):
        if not s:
            continue
        if len(s) < min_len:
            skipped += 1
            continue
        total += 1
        if s in seen:
            continue
        seen.add(s)
        if s not in new_sq:
            missing.append((raw, s))
    lines = [f"舊版句數（>= {min_len} 字）{total}；略過短句 {skipped}；找不到 {len(missing)}"]
    for i, (raw, s) in enumerate(missing, 1):
        lines.append(f"[{i}] {raw[:300]}")
        if hint:
            for tag, key in (("頭", s[:12]), ("尾", s[-12:])):
                pos = new_sq.find(key)
                if pos >= 0:
                    lines.append(f"    ({tag}部12字在新文 {pos} 處) ...{new_sq[max(0, pos - 10):pos + 60]}")
    return missing, "\n".join(lines)


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
    if a.old_file:
        old = Path(a.old_file).read_text(encoding="utf-8")
    else:
        old = subprocess.run(["git", "show", f"{a.old_ref}:{a.git_path}"], cwd=a.repo,
                             capture_output=True, check=True).stdout.decode("utf-8")
    missing, out = diff(old, [Path(p).read_text(encoding="utf-8") for p in a.new], a.min, not a.no_hint)
    if a.report:
        Path(a.report).write_text(out, encoding="utf-8")
    sys.stdout.buffer.write((out + "\n").encode("utf-8", "replace"))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
