#!/usr/bin/env python3
"""規則觸發統計（0.28.0）：每個 hook 提醒／守門被觸發幾次、退回幾次、最後一次是什麼時候，列出很久沒觸發的。只用標準庫。

起因（使用者 2026-11-25 同意的優化第 5 項）：「定期刪掉沒觸發過、或從來沒被照做的規則」。官方建議「delete anything stale,
since outdated instructions are worse than none」（support.claude.com/en/articles/14553240），意思：過時的指示比沒有更糟，要定期刪。

資料：hook 每次輸出都把裡面的【標籤】附加一行到 <CLAUDE_HOME>/state/rule-hits.log（hooks/usage_guard.py 的 _emit，唯一來源），
格式「時間<TAB>事件<TAB>標籤<TAB>block 或 -」；超過 1 MB 會改名成 rule-hits.log.1，這裡兩份都讀。
所有標籤清單取自 rules/workflow.md〈hook 標籤對照〉表（唯一來源），表上有、紀錄裡沒有的就是「沒觸發過」。

只產生清單、不改任何規則：哪條要刪由使用者決定。agent 端有沒有照規則做（讀記憶、先讀 web-quick 等）看 tools/agent-audit.py。

用法：
  python rule-stats.py                 # 全部紀錄
  python rule-stats.py --days 30       # 只看最近 30 天
  python rule-stats.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

TAG = re.compile(r"【[^】\n]{2,20}】")


def claude_home(arg=None) -> Path:
    if arg:
        return Path(arg)
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env) if env else Path.home() / ".claude"


def known_tags(workflow_md: Path) -> list:
    """rules/workflow.md〈hook 標籤對照〉表第一欄的所有標籤（保留表上順序、去重）。讀不到回 []。"""
    try:
        text = workflow_md.read_text(encoding="utf-8")
    except OSError:
        return []
    m = re.search(r"〈?hook 標籤對照〉?.*?\n(\|.*?)(?:\n\n|\Z)", text, flags=re.S)
    body = m.group(1) if m else text
    out = []
    for line in body.splitlines():
        if not line.startswith("|"):
            continue
        first = line.split("|")[1] if line.count("|") >= 2 else ""
        for t in TAG.findall(first):
            if t not in out:
                out.append(t)
    return out


def read_hits(state_dir: Path, since: float | None = None) -> list:
    """[(epoch, 事件, 標籤, blocked)]，舊檔在前。壞行略過。"""
    rows = []
    for name in ("rule-hits.log.1", "rule-hits.log"):
        try:
            lines = (state_dir / name).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            parts = line.split("\t")
            if len(parts) != 4:
                continue
            try:
                ts = time.mktime(time.strptime(parts[0], "%Y-%m-%dT%H:%M:%S"))
            except ValueError:
                continue
            if since is not None and ts < since:
                continue
            rows.append((ts, parts[1], parts[2], parts[3] == "block"))
    return rows


def summarize(rows: list, tags: list) -> list:
    """每個標籤一列：{tag, count, blocked, last, events}。表上有但沒觸發的 count=0；紀錄裡有、表上沒有的也列（排在後面）。"""
    stat: dict = {}
    for ts, ev, tag, blocked in rows:
        s = stat.setdefault(tag, {"tag": tag, "count": 0, "blocked": 0, "last": None, "events": set()})
        s["count"] += 1
        s["blocked"] += 1 if blocked else 0
        s["last"] = max(s["last"] or 0, ts)
        s["events"].add(ev)
    out = []
    for t in tags + sorted(k for k in stat if k not in tags):
        s = stat.get(t) or {"tag": t, "count": 0, "blocked": 0, "last": None, "events": set()}
        out.append({**s, "events": sorted(s["events"]), "inTable": t in tags})
    return out


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="hook 提醒／守門的觸發統計（只列清單，不改規則）")
    ap.add_argument("--claude-home")
    ap.add_argument("--days", type=float, help="只看最近 N 天")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    home = claude_home(a.claude_home)
    wf = home / "claude-dev-system" / "rules" / "workflow.md"
    if not wf.exists():
        wf = Path(__file__).resolve().parents[1] / "rules" / "workflow.md"
    rows = read_hits(home / "state", time.time() - a.days * 86400 if a.days else None)
    res = summarize(rows, known_tags(wf))
    if a.json:
        print(json.dumps({"since": min((r[0] for r in rows), default=None), "rows": res}, ensure_ascii=False, indent=1))
        return 0
    if not rows:
        print("還沒有任何觸發紀錄（0.28.0 起 hook 才開始記；累積幾週再看）。")
    else:
        first = time.strftime("%Y-%m-%d", time.localtime(min(r[0] for r in rows)))
        print(f"紀錄期間：{first} 起，共 {len(rows)} 筆")
    print("| 標籤 | 觸發 | 退回 | 最後一次 | 事件 |")
    print("|---|---|---|---|---|")
    for s in res:
        last = time.strftime("%Y-%m-%d", time.localtime(s["last"])) if s["last"] else "—"
        note = "" if s["inTable"] else "（不在 workflow.md 表上）"
        print(f"| {s['tag']}{note} | {s['count']} | {s['blocked']} | {last} | {'、'.join(s['events']) or '—'} |")
    never = [s["tag"] for s in res if s["count"] == 0]
    if rows and never:
        print(f"\n紀錄期間內沒觸發過的 {len(never)} 個：{'、'.join(never)}。沒觸發不等於沒用（例如磁碟清理本來就少見），"
              "要不要刪由使用者決定；常被退回的標籤代表那條規則模型常不照做，考慮改寫或改成更明確的 hook。")
    print("agent 端的規則遵守度：py -3 ~/.claude/claude-dev-system/tools/agent-audit.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
