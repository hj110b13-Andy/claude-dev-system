"""`install.py selftest`：用全新無頭 `claude -p` session 重跑 config/selftest.json 的題目，比對它實際呼叫的工具。

目的：安裝或改規則後，一鍵確認 Claude Code 真的會「該用的時候自己用」每個工具／MCP／API（不是人工看對話）。
每題只給問題、不提工具名；--output-format stream-json 逐事件讀 tool_use，整理成「工具名 :: 參數摘要」清單，
再對 expect（全部要命中）與 forbid（一個都不能命中）的正規表達式判定 ✅／❌。
費用：每題約一場短對話的用量（訂閱制下 USD 只是估算值），九題約 20～40 分鐘，所以只手動觸發、可用 --only 挑題。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .paths import REPO, Layout, claude_home
from . import web

OK, BAD, WARN = "✅", "❌", "⚠️"
SUMMARY_KEYS = ("command", "url", "query", "search_queries", "objective", "prompt", "libraryName", "question", "repoName", "file_path", "pattern", "urls", "content", "new_string")  # content／new_string：Claude 先 Write 腳本再執行時，金鑰與網址在檔案內容裡


def load_cases(path: Path | None = None) -> dict:
    """題目檔：repo 的 config/selftest.json；沒有 repo（例如只裝了執行檔）就用已安裝的那份。"""
    p = path or (REPO / "config" / "selftest.json")
    if not p.exists():
        p = Layout(claude_home(None)).payload / "config" / "selftest.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _masker():
    """把本機 local.json 的金鑰值從呼叫摘要與回答裡遮掉（Bash 指令或 Write 內容常直接帶金鑰）。"""
    try:
        local = web.load_local(Layout(claude_home(None)))
    except Exception:  # noqa: BLE001
        local = {}
    return lambda t: web.mask(t, local)


def summarize_input(inp) -> str:
    """把 tool_use 的 input 壓成一行（給正規表達式比對與人看）。"""
    if not isinstance(inp, dict):
        return str(inp)[:200]
    parts = []
    for k in SUMMARY_KEYS:
        if k in inp and inp[k] not in (None, ""):
            v = inp[k]
            parts.append(" ".join(map(str, v)) if isinstance(v, list) else str(v))
    if not parts:
        parts.append(json.dumps(inp, ensure_ascii=False))
    return " ".join(" ".join(parts).split())[:300]


def parse_stream(raw: str) -> tuple[list[str], dict]:
    """stream-json 每行一個事件；收 assistant 訊息裡的 tool_use 與最後的 result。回 (["工具 :: 摘要", ...], result 事件)。"""
    calls: list[str] = []
    result: dict = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if ev.get("type") == "assistant":
            for blk in ((ev.get("message") or {}).get("content") or []):
                if isinstance(blk, dict) and blk.get("type") == "tool_use":
                    calls.append(f"{blk.get('name')} :: {summarize_input(blk.get('input'))}")
        elif ev.get("type") == "result":
            result = ev
    return calls, result


def judge(case: dict, calls: list[str]) -> tuple[bool, list[str]]:
    """expect 每條至少命中一個呼叫；forbid 每條都不得命中。回 (通過?, 說明列)。"""
    notes = []
    ok = True
    if not case.get("expect"):
        return False, [f"{BAD} 題目沒有 expect，無法判定"]
    for pat in case.get("expect", []):
        hit = [c for c in calls if re.search(pat, c)]
        if hit:
            notes.append(f"{OK} 預期 {pat} ← {hit[0][:90]}")
        else:
            ok = False
            notes.append(f"{BAD} 預期 {pat} 沒有出現")
    for pat in case.get("forbid", []):
        hit = [c for c in calls if re.search(pat, c)]
        if hit:
            ok = False
            notes.append(f"{BAD} 不該出現 {pat} ← {hit[0][:90]}")
        else:
            notes.append(f"{OK} 未出現 {pat}")
    for pat in case.get("warn", []):  # 規則允許在退路時用、但不該是第一步的工具：只標 ⚠️ 不算失敗（順序無法從清單判定）
        hit = [c for c in calls if re.search(pat, c)]
        notes.append(f"{WARN} 有用到 {pat}（規則只允許當退路，請看報告確認順序）← {hit[0][:90]}" if hit else f"{OK} 未用到 {pat}")
    return ok, notes


def default_runner(cmd: list[str], cwd: str, timeout: int) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout,
                           env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    except subprocess.TimeoutExpired as e:
        out = e.stdout or b""
        return 124, (out.decode("utf-8", "replace") if isinstance(out, bytes) else str(out)), f"{timeout} 秒內沒跑完"
    return r.returncode, (r.stdout or b"").decode("utf-8", "replace"), (r.stderr or b"").decode("utf-8", "replace")


def build_cmd(exe: str, case: dict, cfg: dict) -> list[str]:
    cmd = [exe, "-p", case["prompt"], "--output-format", "stream-json", "--verbose", "--no-session-persistence",
           "--max-turns", str(case.get("maxTurns") or cfg.get("maxTurns") or 24),
           "--allowedTools", cfg.get("allowed", "")]
    cmd.append("--chrome" if case.get("chrome") else "--no-chrome")
    return cmd


def run(only: list[str] | None = None, list_only: bool = False, cases_path: Path | None = None, runner=default_runner,
        which=shutil.which, log=print, report_dir: Path | None = None, dry_run: bool = False) -> int:
    """跑題目並印表。回 0 全過、1 有 ❌、2 用法錯誤。report_dir 給了就把每題的呼叫清單與回答存成 JSON（不含金鑰）。
    dry_run=True：不跑 claude，只印每題會執行的完整指令（確認旗標與題目，零用量）。"""
    cfg = load_cases(cases_path)
    cases = cfg.get("cases") or []
    if only:
        unknown = [o for o in only if o not in {c["id"] for c in cases}]
        if unknown:
            log(f"{BAD} 沒有這些題目：{', '.join(unknown)}；可用：{', '.join(c['id'] for c in cases)}")
            return 2
        cases = [c for c in cases if c["id"] in only]
    if list_only:
        for c in cases:
            log(f"{c['id']:10s} {c['name']}" + ("（需 Chrome）" if c.get("chrome") else ""))
        return 0
    exe = which("claude")
    if not exe:
        log(f"{BAD} 找不到 claude 指令")
        return 2
    timeout = int(cfg.get("timeoutSec") or 540)
    if dry_run:
        for c in cases:
            log(f"── {c['id']}：{c['name']}")
            log("   " + " ".join(f'"{a}"' if " " in a or "，" in a else a for a in build_cmd(exe, c, cfg)))
        log(f"{OK} dry-run：{len(cases)} 題的指令如上，未執行")
        return 0
    results = []
    mask = _masker()
    with tempfile.TemporaryDirectory(prefix="cds-selftest-", ignore_cleanup_errors=True) as cwd:  # 空資料夾：只吃全域規則；Windows 上孫程序佔住也不讓結果消失
        for c in cases:
            t0 = time.time()
            log(f"── {c['id']}：{c['name']}")
            code, out, err = runner(build_cmd(exe, c, cfg), cwd, timeout)
            calls, res = parse_stream(out)
            calls = [mask(x) for x in calls]
            ok, notes = judge(c, calls)
            if code != 0 and not calls:
                ok = False
                notes.append(f"{BAD} claude 結束碼 {code}：{mask((err or out)[-200:].strip())}")
            for n in notes:
                log("   " + n)
            cost = res.get("total_cost_usd")
            log(f"   工具呼叫 {len(calls)} 次、{time.time() - t0:.0f} 秒" + (f"、用量約 ${cost:.2f} 等值（訂閱制為估算）" if isinstance(cost, (int, float)) else ""))
            results.append({"id": c["id"], "name": c["name"], "ok": ok, "calls": calls, "notes": notes, "cost_usd": cost,
                            "answer": mask((res.get("result") or "")[:4000]), "exit": code})
        passed = sum(1 for r in results if r["ok"])
        log(f"{OK if passed == len(results) else BAD} 自我測試 {passed}/{len(results)} 題通過")
        if report_dir:  # 在 with 裡面寫：就算暫存資料夾清不掉，20～40 分鐘的結果也已存好
            report_dir.mkdir(parents=True, exist_ok=True)
            rp = report_dir / f"selftest-{time.strftime('%Y%m%d-%H%M%S')}.json"
            rp.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
            log(f"報告：{rp}")
    return 0 if passed == len(results) else 1
