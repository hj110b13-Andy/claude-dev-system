"""`install.py coding-eval`：同一組寫程式題，在「裝了 claude-dev-system」與「沒裝」兩種條件下各跑一次全新無頭 `claude -p`，比成本與行為。

題目在 config/coding-eval.json：共用一份 seed（小型 Python 專案），每題有隱藏測試，跑完才放進 `.cds_hidden/` 執行（模型看不到）。
條件：with＝使用者平常的全域設定；without＝加 `--safe-mode`（官方 CLI 說明：停用 CLAUDE.md、skills、plugins、hooks、MCP 等全部自訂，
登入、模型選擇、內建工具與權限照常）。兩條件固定同一個 --model／--effort，並拿掉外層 session 的 CLAUDE_* 環境變數。
每次記錄：隱藏測試是否通過、可見測試是否通過、token（輸入／輸出／快取建／快取讀）、耗時、工具次數、有沒有自己跑測試、改了哪些檔。
樣本很小：只拿來比成本、耗時與行為差異；通過率只當參考（統計上偵測不出品質差異）。
執行與 stream-json 解析沿用 selftest.py（build_cmd、parse_stream、usage_of、default_runner、_masker），不另寫一份。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .paths import REPO
from . import selftest

OK, BAD, WARN = selftest.OK, selftest.BAD, selftest.WARN
HIDDEN_DIR = ".cds_hidden"
CONDITIONS = ("with", "without")


def _log(s: str) -> None:
    print(s, flush=True)  # 背景執行時輸出導到檔案，逐行 flush 才看得到進度


def load_eval(path: Path | None = None) -> dict:
    """題目檔只在 repo 裡（評測工具，不隨安裝檔發佈）。"""
    p = path or (REPO / "config" / "coding-eval.json")
    return json.loads(p.read_text(encoding="utf-8"))


def select_cases(cfg: dict, only: list[str] | None) -> tuple[list[dict], list[str]]:
    """--only 可重複、可逗號分隔（與 selftest 一致）。回 (題目, 不存在的題號)。"""
    cases = cfg.get("cases") or []
    if not only:
        return cases, []
    want = [x.strip() for o in only for x in str(o).split(",") if x.strip()]
    ids = {c["id"] for c in cases}
    unknown = [w for w in want if w not in ids]
    return [c for c in cases if c["id"] in want], unknown


def conditions_for(arg: str) -> list[str]:
    if arg == "both":
        return list(CONDITIONS)
    if arg in CONDITIONS:
        return [arg]
    raise ValueError(f"--condition 只能是 with／without／both，收到 {arg}")


def clean_env(base: dict | None = None) -> dict:
    """拿掉外層 Claude Code session 的 CLAUDE_* 變數（session id、訊息通道、effort…），只留 CLAUDE_CONFIG_DIR。
    不拿掉的話子程序會以為自己是外層 session 的子對話，兩條件也可能吃到外層的 effort。"""
    env = dict(os.environ if base is None else base)
    for k in list(env):
        if k.upper().startswith("CLAUDE") and k.upper() != "CLAUDE_CONFIG_DIR":
            env.pop(k)
    return env


def build_eval_cmd(exe: str, case: dict, cfg: dict, cond: str) -> list[str]:
    """selftest.build_cmd 的指令＋固定的 model／effort＋條件旗標（without＝--safe-mode）。"""
    cmd = selftest.build_cmd(exe, case, cfg)
    if cfg.get("model"):
        cmd += ["--model", str(cfg["model"])]
    if cfg.get("effort"):
        cmd += ["--effort", str(cfg["effort"])]
    cmd += list(((cfg.get("conditions") or {}).get(cond) or {}).get("args") or [])
    return cmd


def write_files(root: Path, files: dict) -> None:
    for rel, content in (files or {}).items():
        fp = root / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8", newline="\n")


def _digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def snapshot(root: Path) -> dict:
    """相對路徑 → sha256（略過 __pycache__ 與隱藏測試資料夾）。"""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and HIDDEN_DIR not in p.parts:
            out[p.relative_to(root).as_posix()] = _digest(p)
    return out


def diff_files(before: dict, after: dict) -> dict:
    return {"added": sorted(set(after) - set(before)), "deleted": sorted(set(before) - set(after)),
            "modified": sorted(k for k in set(before) & set(after) if before[k] != after[k])}


def parse_unittest(text: str) -> dict:
    """unittest 輸出 → {ran, failures, errors}；看不懂回 ran=0。"""
    ran = re.findall(r"^Ran (\d+) tests?", text or "", re.M)
    fail = re.search(r"FAILED \(([^)]*)\)", text or "")
    counts = {"failures": 0, "errors": 0}
    if fail:
        for k, v in re.findall(r"(failures|errors)=(\d+)", fail.group(1)):
            counts[k] = int(v)
    return {"ran": int(ran[-1]) if ran else 0, **counts}


def run_unittest(case_dir: Path, start: str, timeout: int, runner=None) -> dict:
    """在 case_dir 跑 `python -m unittest discover -s <start>`；回 {ok, ran, failures, errors, tail}。
    受測程式靠 PYTHONPATH=case_dir 匯入。"""
    cmd = [sys.executable, "-m", "unittest", "discover", "-s", start, "-t", start]  # -t 指向測試資料夾本身：tests/ 沒有 __init__.py 也能找到
    env = {**clean_env(), "PYTHONPATH": str(case_dir), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    if runner is not None:
        code, out = runner(cmd, str(case_dir), timeout, env)
    else:
        try:
            r = subprocess.run(cmd, cwd=str(case_dir), capture_output=True, timeout=timeout, env=env)
            code, out = r.returncode, (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            code, out = 124, f"{timeout} 秒內沒跑完"
    info = parse_unittest(out)
    return {"ok": code == 0 and info["ran"] > 0, **info, "exit": code, "tail": out[-1500:]}


def judge_hidden(case_dir: Path, case: dict, timeout: int, runner=None) -> dict:
    """把隱藏測試放進 .cds_hidden/ 再執行；模型跑完之後才放，所以它看不到。"""
    hdir = case_dir / HIDDEN_DIR
    if hdir.exists():
        shutil.rmtree(hdir, ignore_errors=True)
    write_files(hdir, case.get("hidden") or {})
    return run_unittest(case_dir, HIDDEN_DIR, timeout, runner)


def ran_tests(calls: list[str], pattern: str) -> bool:
    return any(re.search(pattern, c) for c in calls)


def tool_counts(calls: list[str]) -> dict:
    out: dict = {}
    for c in calls:
        name = c.split(" :: ", 1)[0]
        out[name] = out.get(name, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def stream_info(raw: str) -> dict:
    """stream-json 裡 parse_stream 不收的部分：init 事件（工具數、MCP、skills、plugins）與 hook 事件數，當成「條件真的有隔離」的證據。"""
    info = {"tools": None, "mcp_servers": [], "cds_skills": [], "plugins": [], "hook_events": 0}
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if ev.get("type") != "system":
            continue
        sub = str(ev.get("subtype") or "")
        if sub == "init" and info["tools"] is None:
            info["tools"] = len(ev.get("tools") or [])
            info["mcp_servers"] = sorted(str((m or {}).get("name")) for m in (ev.get("mcp_servers") or []) if isinstance(m, dict))
            names = [str(x) for x in (ev.get("skills") or []) + (ev.get("slash_commands") or [])]
            info["cds_skills"] = sorted({n for n in names if "cds-" in n})
            info["plugins"] = sorted(str((p or {}).get("name", p)) if isinstance(p, dict) else str(p) for p in (ev.get("plugins") or []))
            info["model"] = ev.get("model")
        elif "hook" in sub:
            info["hook_events"] += 1
    return info


def all_models_usage(res: dict) -> dict:
    """result.modelUsage（含子 agent 用的其他模型）加總；沒有就空。"""
    mu = res.get("modelUsage") or {}
    if not isinstance(mu, dict) or not mu:
        return {}
    keys = {"inputTokens": "input_tokens", "outputTokens": "output_tokens",
            "cacheCreationInputTokens": "cache_creation_input_tokens", "cacheReadInputTokens": "cache_read_input_tokens"}
    out = {v: 0 for v in keys.values()}
    for m in mu.values():
        if isinstance(m, dict):
            for k, v in keys.items():
                out[v] += int(m.get(k) or 0)
    out["total"] = sum(out.values())
    out["models"] = sorted(mu)
    return out


def run_one(exe: str, case: dict, cfg: dict, cond: str, work: Path, runner, mask, log) -> dict:
    case_dir = work / f"{cond}-{case['id']}"
    if case_dir.exists():
        shutil.rmtree(case_dir, ignore_errors=True)
    case_dir.mkdir(parents=True)
    write_files(case_dir, cfg.get("seed") or {})
    before = snapshot(case_dir)
    timeout = int(cfg.get("timeoutSec") or 900)
    t0 = time.time()
    code, out, err = runner(build_eval_cmd(exe, case, cfg, cond), str(case_dir), timeout, clean_env())
    secs = round(time.time() - t0, 1)
    calls, res = selftest.parse_stream(out)
    calls = [mask(x) for x in calls]
    changed = diff_files(before, snapshot(case_dir))  # 先記改動，再跑測試（測試不寫 pycache）
    ttimeout = int(cfg.get("testTimeoutSec") or 120)
    hidden = judge_hidden(case_dir, case, ttimeout)
    visible = run_unittest(case_dir, "tests", ttimeout)
    usage = selftest.usage_of(res)
    error = ""
    if not res:
        error = f"沒有 result 事件（結束碼 {code}）：{mask((err or out)[-300:].strip())}"
    elif res.get("is_error") or res.get("subtype") not in (None, "success"):
        error = f"result {res.get('subtype')}：{mask(str(res.get('result') or '')[:200])}"
    row = {"id": case["id"], "name": case.get("name"), "kind": case.get("kind"), "condition": cond,
           "hidden_ok": hidden["ok"], "hidden": {k: hidden[k] for k in ("ran", "failures", "errors", "exit")},
           "hidden_tail": hidden["tail"] if not hidden["ok"] else "",
           "visible_ok": visible["ok"], "visible": {k: visible[k] for k in ("ran", "failures", "errors", "exit")},
           "ran_tests": ran_tests(calls, cfg.get("ranTestsPattern") or r"(?i)^(Bash|PowerShell) ::.*(unittest|pytest)"),
           "tool_calls": len(calls), "tools": tool_counts(calls), "calls": [x[:300] for x in calls],
           "seconds": secs, "duration_ms": res.get("duration_ms"), "duration_api_ms": res.get("duration_api_ms"),
           "num_turns": res.get("num_turns"), "usage": usage, "usage_all_models": all_models_usage(res),
           "cost_usd": res.get("total_cost_usd"), "changed": changed, "stream": stream_info(out),
           "exit": code, "error": error, "answer": mask(str(res.get("result") or "")[:3000])}
    log(f"   {OK if row['hidden_ok'] else BAD} 隱藏測試 {hidden['ran'] - hidden['failures'] - hidden['errors']}/{hidden['ran']}"
        f"、自己跑測試 {'有' if row['ran_tests'] else '沒有'}、工具 {row['tool_calls']} 次、{secs:.0f} 秒"
        + (f"、token 合計 {usage['total']:,}" if usage else "") + (f"｜{error}" if error else ""))
    return row


def _median(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return statistics.median(xs) if xs else None


def summarize(rows: list[dict]) -> dict:
    """每個條件的合計／中位數，與每題 with 相對 without 的倍數（只算兩條件都有、且都沒有 error 的題）。"""
    per = {}
    for cond in CONDITIONS:
        rs = [r for r in rows if r["condition"] == cond]
        if not rs:
            continue
        tot = [(r.get("usage") or {}).get("total", 0) for r in rs]
        per[cond] = {"runs": len(rs), "hidden_pass": sum(1 for r in rs if r["hidden_ok"]),
                     "ran_tests": sum(1 for r in rs if r["ran_tests"]), "errors": sum(1 for r in rs if r.get("error")),
                     "tokens_total": sum(tot), "tokens_median": _median(tot),
                     "output_total": sum((r.get("usage") or {}).get("output_tokens", 0) for r in rs),
                     "seconds_total": round(sum(r["seconds"] for r in rs), 1), "seconds_median": _median([r["seconds"] for r in rs]),
                     "tool_calls_total": sum(r["tool_calls"] for r in rs),
                     "cost_usd_total": round(sum(r["cost_usd"] for r in rs if isinstance(r.get("cost_usd"), (int, float))), 4)}
    ratios = []
    by = {(r["id"], r["condition"]): r for r in rows}
    for cid in dict.fromkeys(r["id"] for r in rows):
        w, wo = by.get((cid, "with")), by.get((cid, "without"))
        if not w or not wo or w.get("error") or wo.get("error"):
            continue
        tw, two = (w.get("usage") or {}).get("total", 0), (wo.get("usage") or {}).get("total", 0)
        ratios.append({"id": cid, "tokens_x": round(tw / two, 2) if two else None,
                       "seconds_x": round(w["seconds"] / wo["seconds"], 2) if wo["seconds"] else None,
                       "tool_calls_diff": w["tool_calls"] - wo["tool_calls"]})
    return {"per_condition": per, "with_vs_without": ratios}


def format_table(rows: list[dict], summary: dict) -> list[str]:
    head = "| 題目 | 條件 | 隱藏測試 | 可見測試 | 自己跑測試 | 工具次數 | 秒數 | 輸入 | 輸出 | 快取建 | 快取讀 | token 合計 | 備註 |"
    out = [head, "|" + "---|" * 13]
    for r in rows:
        u = r.get("usage") or {}
        h = r["hidden"]
        out.append(f"| {r['id']} | {r['condition']} | {OK if r['hidden_ok'] else BAD} {h['ran'] - h['failures'] - h['errors']}/{h['ran']} | "
                   f"{OK if r['visible_ok'] else BAD} | {'有' if r['ran_tests'] else '沒有'} | {r['tool_calls']} | {r['seconds']:.0f} | "
                   f"{u.get('input_tokens', 0):,} | {u.get('output_tokens', 0):,} | {u.get('cache_creation_input_tokens', 0):,} | "
                   f"{u.get('cache_read_input_tokens', 0):,} | {u.get('total', 0):,} | {r.get('error') or ''} |")
    out.append("")
    out.append("| 條件 | 次數 | 隱藏測試通過 | 自己跑測試 | token 合計 | token 中位數 | 輸出合計 | 秒數合計 | 秒數中位數 | 工具次數合計 |")
    out.append("|" + "---|" * 10)
    for cond, s in summary["per_condition"].items():
        out.append(f"| {cond} | {s['runs']} | {s['hidden_pass']}/{s['runs']} | {s['ran_tests']}/{s['runs']} | {s['tokens_total']:,} | "
                   f"{s['tokens_median'] or 0:,.0f} | {s['output_total']:,} | {s['seconds_total']:.0f} | {s['seconds_median'] or 0:.0f} | {s['tool_calls_total']} |")
    if summary["with_vs_without"]:
        out.append("")
        out.append("| 題目 | token 倍數（with÷without） | 秒數倍數 | 工具次數差（with−without） |")
        out.append("|---|---|---|---|")
        for x in summary["with_vs_without"]:
            out.append(f"| {x['id']} | {x['tokens_x']} | {x['seconds_x']} | {x['tool_calls_diff']:+d} |")
    out.append("")
    out.append("說明：每題每條件只跑 1 次，只能看成本、耗時與行為差異；隱藏測試通過率樣本太小，只當參考，不能據此說哪個條件寫得比較好。")
    return out


def run(only: list[str] | None = None, list_only: bool = False, dry_run: bool = False, condition: str = "both",
        cfg_path: Path | None = None, runner=selftest.default_runner, which=shutil.which, log=_log,
        report_dir: Path | None = None, work_dir: Path | None = None) -> int:
    """回 0 全部跑完（不論隱藏測試過不過：這是量測，不是閘門）；1 有場次沒跑完（沒有 result 或 result 是錯誤）；2 用法錯誤。"""
    cfg = load_eval(cfg_path)
    cases, unknown = select_cases(cfg, only)
    if unknown:
        log(f"{BAD} 沒有這些題目：{', '.join(unknown)}；可用：{', '.join(c['id'] for c in cfg.get('cases') or [])}")
        return 2
    try:
        conds = conditions_for(condition)
    except ValueError as e:
        log(f"{BAD} {e}")
        return 2
    if list_only:
        for c in cases:
            log(f"{c['id']:10s} {c.get('kind', '')}：{c['name']}")
        return 0
    exe = which("claude")
    if not exe:
        log(f"{BAD} 找不到 claude 指令")
        return 2
    if dry_run:
        for c in cases:
            for cond in conds:
                log(f"── {c['id']}｜{cond}（{(cfg['conditions'][cond] or {}).get('label', '')}）：{c['name']}")
                log("   " + " ".join(f'"{a}"' if (" " in a or "，" in a) else a for a in build_eval_cmd(exe, c, cfg, cond)))
        log(f"{OK} dry-run：{len(cases)} 題 × {len(conds)} 條件 = {len(cases) * len(conds)} 場的指令如上，未執行"
            f"（seed {len(cfg.get('seed') or {})} 檔；隱藏測試跑完才放進 {HIDDEN_DIR}/；環境變數拿掉外層 CLAUDE_*）")
        return 0
    mask = selftest._masker()
    code, ver, _ = runner([exe, "--version"], str(Path.cwd()), 60, clean_env())
    meta = {"claude_version": ver.strip() if code == 0 else None, "model": cfg.get("model"), "effort": cfg.get("effort"),
            "conditions": {k: cfg["conditions"][k] for k in conds}, "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    rows: list[dict] = []
    tmp = None
    if work_dir is None:
        tmp = tempfile.TemporaryDirectory(prefix="cds-codingeval-", ignore_cleanup_errors=True)
        work = Path(tmp.name)
    else:
        work = Path(work_dir) / time.strftime("run-%Y%m%d-%H%M%S")
        work.mkdir(parents=True, exist_ok=True)
    try:
        for c in cases:  # 同一題的兩個條件緊接著跑，減少時段差異
            for cond in conds:
                log(f"── {c['id']}｜{cond}：{c['name']}")
                rows.append(run_one(exe, c, cfg, cond, work, runner, mask, log))
        summary = summarize(rows)
        for line in format_table(rows, summary):
            log(line)
        if report_dir:
            report_dir.mkdir(parents=True, exist_ok=True)
            rp = report_dir / f"coding-eval-{time.strftime('%Y%m%d-%H%M%S')}.json"
            rp.write_text(json.dumps({"meta": meta, "summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
            log(f"報告：{rp}")
        if work_dir is not None:
            log(f"工作目錄保留在：{work}")
    finally:
        if tmp is not None:
            tmp.cleanup()
    return 1 if any(r.get("error") for r in rows) else 0
