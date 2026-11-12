#!/usr/bin/env python3
"""agent-audit：量一場（或幾場）對話派出的 agent 有沒有照規則做。只讀，不寫入任何東西。

用法：
  py -3 agent-audit.py [專案路徑，預設目前資料夾] [--session <id 前綴> | --latest N | --since YYYY-MM-DD] [--detail] [--json]

資料來源：~/.claude/projects/<專案代號>/<session id>/subagents/agent-<id>.jsonl 與同名 .meta.json；
守門退回另有 ~/.claude/state/source-guard.log（每行含 `block-agent <agent id> N 項：…`）。

判定規則的唯一來源是 hooks/usage_guard.py（SUB_WEB_TOOL、_sub_cjk_ratio、_sub_scan、SUB_COMMIT 依相對路徑載入，
repo 與安裝副本的 tools/ 與 hooks/ 相對位置相同）。下列判定 usage_guard.py 沒有，寫在這支工具裡：
  - git add -A／stash／整批結束程序／重型工作／resgate 的指令正則（取自 2026-11-11 的一次性腳本 cp.py、measure.py）
  - 記憶內文讀取（只看有沒有讀過 memory 底下非 MEMORY.md 的檔；guard 的版本要帶 mem_dir，這裡不需要）
  - 「有過記憶體閘門」「上網前先讀 web-quick」看事件先後順序：真的執行了 resgate.py run／wait 才算閘門
    （指令用 hook 的 _command_segments 切開，`grep resgate` 不算），讀 web-quick 要在第一次上網工具之前。
中文比例門檻不在這裡定義：用 usage_guard.SUB_LANG_MIN_RATIO（main() 載入後存進 LANG_RATIO，標題與判定都引用它）。
模型名稱統一成家族名（opus／sonnet／haiku／fable），meta 寫「haiku」、對話紀錄寫「claude-haiku-5-5」算同一種。
"""
import argparse
import glob
import importlib.util
import json
import os
import re
import sys
import time
from collections import Counter

HOME = os.path.expanduser("~")
PROJECTS = os.path.join(HOME, ".claude", "projects")
GUARD_LOG = os.path.join(HOME, ".claude", "state", "source-guard.log")
LANG_RATIO = None  # main() 載入 usage_guard 後設成 ug.SUB_LANG_MIN_RATIO（唯一來源）

# ---- 以下是 usage_guard.py 沒有的判定（本工具自己的）----
RE_MEMORY = re.compile(r"memory[\\/](?!MEMORY\.md)[\w\-]+\.md")
RE_ADD_ALL = re.compile(r"\bgit\s+add\s+(?:-A|--all|\.)(?:\s|$)")
RE_STASH = re.compile(r"\bgit\s+(?:stash(?!\s+(?:list|show)\b)|reset\s+--hard|checkout\s+--)")
RE_KILL = re.compile(r"taskkill\s+/(?:F\s+/)?IM|Stop-Process\s+-Name|\bpkill\b|\bkillall\b", re.I)
# 重型工作：回測、全套測試、build（規則見全域 CLAUDE.md〈重型工作記憶體閘門〉）；指令本身含 resgate 的不算重型
RE_HEAVY = re.compile(r"backtest|npm\s+(?:run\s+)?(?:test|build)|vitest|next\s+build|unittest\s+discover|pytest|build_exe", re.I)
# 真的「執行」記憶體閘門：子指令開頭（可有執行器 py／python）就是 resgate.py 的 run 或 wait；grep／cat／echo 提到 resgate 不算
RE_RESGATE_EXEC = re.compile(r"^(?:\w+=\S+\s+)*(?:(?:py|python3?)(?:\.exe)?(?:\s+-[\w.]+)*\s+)?\S*resgate\.py[\"']?\s+(?:run|wait)\b", re.I)
RE_BRANCH = re.compile(r"分支|branch", re.I)
RE_DENY = "這份報告還不能交"


def load_guard():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(os.path.dirname(here), "hooks", "usage_guard.py")
    spec = importlib.util.spec_from_file_location("usage_guard_for_audit", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def slug_of(path):
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(path))


def find_project_dir(path):
    if not os.path.isdir(PROJECTS):
        return None
    want = slug_of(path).lower().rstrip("-")
    for name in os.listdir(PROJECTS):
        if name.lower().rstrip("-") == want and os.path.isdir(os.path.join(PROJECTS, name)):
            return os.path.join(PROJECTS, name)
    return None


def list_sessions(pdir):
    """回 [(session id, subagents 資料夾, 最新 mtime)]，依 mtime 由新到舊；只收有 agent-*.jsonl 的。"""
    out = []
    for name in os.listdir(pdir):
        sub = os.path.join(pdir, name, "subagents")
        files = glob.glob(os.path.join(sub, "agent-*.jsonl"))
        if files:
            out.append((name, sub, max(os.path.getmtime(f) for f in files)))
    out.sort(key=lambda x: x[2], reverse=True)
    return out


def read_blocks(log_path):
    """source-guard.log 的 block-agent 行 → {agent id: 次數}。"""
    res = Counter()
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.search(r"block-agent\s+(\S+)", line)
                if m:
                    res[m.group(1)] += 1
    except OSError:
        pass
    return res


def _content_text(c):
    try:
        return json.dumps(c, ensure_ascii=False)
    except Exception:
        return str(c)


# 0.25.1：重型工作只認「真的在執行」的指令——子指令開頭是執行器（py／node／npx／tsx／npm…）而且含重型關鍵字。
# 原本整段文字比對，`ls scripts/backtest/`、`cat scripts/backtest/x.ts`、`grep … docs/backtest/…` 這類只是讀檔也算
# （2026-11-11 Stock-web 一個 opus agent 被算成 11 次重型工作，其實都在讀檔）。子指令切法用 hook 的 _command_segments。
RE_RUNNER = re.compile(r"^(?:\w+=\S+\s+)*(?:py|python3?|node|npx|tsx|npm|pnpm|yarn|pytest|vitest|next)(?:\.exe|\.cmd)?\b", re.I)


def is_heavy(cmd, ug):
    try:
        segs = ug._command_segments(cmd)
    except Exception:
        segs = [cmd]
    return any(RE_RUNNER.match(sg) and RE_HEAVY.search(sg) for sg in segs)


def _segments(cmd, ug):
    try:
        return ug._command_segments(cmd)
    except Exception:
        return [cmd]


def is_resgate_exec(cmd, ug):
    """這個指令有沒有真的執行 resgate.py run／wait（用 hook 的 _command_segments 切子指令，唯一來源）。"""
    return any(RE_RESGATE_EXEC.match(sg.strip()) for sg in _segments(cmd, ug))


def heavy_and_gated(cmds, ug):
    """依指令先後順序判斷：(有沒有跑重型工作, 有沒有哪個重型工作之前（含同一個指令裡，`resgate.py run … -- <重型指令>`）真的過了閘門)。"""
    heavy = gated = seen = False
    for cmd in cmds:
        for sg in _segments(cmd, ug):
            sg = sg.strip()
            if RE_RESGATE_EXEC.match(sg):
                seen = True
            if RE_RUNNER.match(sg) and RE_HEAVY.search(sg):
                heavy = True
                gated = gated or seen
    return heavy, gated


def model_family(*names):
    """模型家族名：meta 的 `haiku`、對話紀錄的 `claude-haiku-5-5`、`claude-sonnet-4-5-20250929` 都歸成同一種。"""
    for n in names:
        if not n:
            continue
        m = re.search(r"(opus|sonnet|haiku|fable)", str(n), re.I)
        if m:
            return m.group(1).lower()
        s = re.sub(r"^claude-", "", str(n)).split("-")[0]
        if s:
            return s
    return "?"


def analyze(path, ug, mem_dir=None):
    global LANG_RATIO
    LANG_RATIO = ug.SUB_LANG_MIN_RATIO
    aid = os.path.basename(path)[len("agent-"):-len(".jsonl")]
    last_tool = None  # 上一個工具呼叫：退回訊息只認「緊接在 SubagentHandback 之後的工具結果」，grep 到 hook 原始碼裡同一句不算
    meta = {}
    try:
        with open(path[:-6] + ".meta.json", encoding="utf-8") as f:
            meta = json.load(f) or {}
    except Exception:
        pass
    ev = []  # (kind, 文字) 依檔案順序
    mids = []  # 中途 assistant 文字
    brief = False
    model = None
    final = None
    final_from_text = False
    denied_seen = out_after_deny = False  # 退回之後有沒有再出現文字或 SubagentHandback（補交）
    cmds_all = []
    tools_all, reads_all = [], []  # 自己讀到的（_sub_scan 以嚴格 UTF-8 開檔，紀錄最後一行寫到一半時會整個回 None）
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            r = json.loads(line)
        except Exception:
            continue
        if not isinstance(r, dict):
            continue
        t = r.get("type")
        if t == "attachment":
            a = r.get("attachment") or {}
            if a.get("type") == "hook_additional_context" and "派工補充" in _content_text(a.get("content")):
                brief = True
            continue
        msg = r.get("message") or {}
        c = msg.get("content")
        if t == "user":
            blob = c if isinstance(c, str) else _content_text(c)
            is_result = isinstance(c, list) and any(isinstance(x, dict) and x.get("type") == "tool_result" for x in c)
            # 兩種退回：PreToolUse 擋下 SubagentHandback（工具結果）；SubagentStop 後備（一般訊息，開頭就是守門字樣）
            if RE_DENY in blob and ((is_result and last_tool == "SubagentHandback") or (not is_result and "【報告守門（hook）】" in blob[:200])):
                denied_seen = True
                ev.append(("DENY", re.sub(r"\s+", " ", blob)[:300]))
            continue
        if t != "assistant" or not isinstance(c, list):
            continue
        model = model or msg.get("model")
        for x in c:
            if not isinstance(x, dict):
                continue
            if x.get("type") == "text" and (x.get("text") or "").strip():
                mids.append(x["text"])
                out_after_deny = out_after_deny or denied_seen
                final, final_from_text = x["text"], True
            if x.get("type") != "tool_use":
                continue
            n, i = x.get("name") or "", x.get("input") or {}
            last_tool = n
            p = str(i.get("file_path") or "")
            cmd = str(i.get("command") or "")
            tools_all.append(n)
            if n == "Read":
                reads_all.append(p)
            if n in ("Bash", "PowerShell") and ("web-quick" in cmd or "web-sources" in cmd):
                ev.append(("web-quick", "讀 web-quick（經指令）"))  # cat／Get-Content 讀也算（與 hook 的判定一致）
            if n == "Read" and ("web-quick" in p or "web-sources" in p):
                ev.append(("web-quick", "讀 web-quick"))
            elif n == "Read" and RE_MEMORY.search(p):
                ev.append(("memory", "讀記憶 " + os.path.basename(p)))
            elif ug.SUB_WEB_TOOL.search(n):
                ev.append(("web", "上網 " + n.split("__")[-1]))
            elif n in ("Bash", "PowerShell"):
                cmds_all.append(cmd)
                if is_resgate_exec(cmd, ug):
                    ev.append(("resgate", "resgate"))
                elif is_heavy(cmd, ug):
                    heavy = True
                    ev.append(("heavy", "重型工作"))
                elif ug.SUB_COMMIT.search(cmd):
                    ev.append(("commit", "git commit"))
                elif "branch --show-current" in cmd:
                    ev.append(("branch", "查分支"))
                elif RE_ADD_ALL.search(cmd):
                    ev.append(("add-all", "git add -A"))
                elif RE_STASH.search(cmd):
                    ev.append(("stash", "stash/reset --hard"))
            if n == "SubagentHandback":
                out_after_deny = out_after_deny or denied_seen
                m = str(i.get("message") or "")
                final, final_from_text = m, False
                ev.append(("handback", "交報告 len=%d 中文比例=%.2f 記憶索引=%s 出處=%s" % (
                    len(m), ug._sub_cjk_ratio(m), "記憶索引" in m, "http" in m)))
    if final_from_text and mids:
        mids = mids[:-1]  # 最後一則文字是最終報告，不算中途文字
    # 記憶、重型、commit 等彙總：用 usage_guard 的掃描（同一套紀錄解析）
    scan = ug._sub_scan(path) or {"prompt": "", "tools": tools_all, "reads": reads_all, "cmds": cmds_all}
    blob = "\n".join(scan["reads"] + scan["cmds"])
    cmds = scan["cmds"] or cmds_all
    web = any(ug.SUB_WEB_TOOL.search(x) for x in scan["tools"])
    # 0.23.0 起建議寫法是 `resgate.py run … -- <重型指令>`（同一個指令裡），所以含 resgate 的指令也算「要跑重型工作」；
    # 閘門要「真的執行 resgate.py run／wait」而且在重型工作之前（grep resgate 不算，閘門在重型工作之後也不算）
    heavy, gated = heavy_and_gated(cmds, ug)
    web_idx = next((k for k, (kind, _) in enumerate(ev) if kind == "web"), None)
    quick_first = web_idx is not None and any(kind == "web-quick" for kind, _ in ev[:web_idx])  # 讀 web-quick 要在第一次上網工具之前
    deny_idx = [k for k, (kind, _) in enumerate(ev) if kind == "DENY"]
    resubmitted = None
    if deny_idx:
        resubmitted = out_after_deny
    return {
        "id": aid,
        "description": meta.get("description"),
        "agentType": meta.get("agentType"),
        "model": model_family(meta.get("model"), model),
        "model_id": meta.get("model") or model or "?",
        "effort": meta.get("effort"),
        "brief": brief,
        "mem": ug.sub_memory_read(blob, mem_dir) if mem_dir and os.path.isdir(mem_dir) else bool(RE_MEMORY.search(blob)),
        "mem_tool": any(RE_MEMORY.search(p) for p in scan["reads"]),  # 用 Read 工具讀；其餘（Get-Content、cat）只經指令
        "web": web,
        "web_quick": bool(web and quick_first),
        "final_len": len(final or ""),
        "final_zh": (ug._sub_cjk_ratio(final) >= LANG_RATIO) if final else None,
        "mid_total": len(mids),
        "mid_en": sum(1 for s in mids if len(s) > 40 and ug._sub_cjk_ratio(s) < LANG_RATIO),
        "commit": any(ug.SUB_COMMIT.search(c) for c in cmds),
        "commit_branch_in_report": bool(final and RE_BRANCH.search(final)),
        "heavy": heavy,
        "gate": bool(heavy and gated),
        "add_all": any(RE_ADD_ALL.search(c) for c in cmds),
        "stash": any(RE_STASH.search(c) for c in cmds),
        "kill": any(RE_KILL.search(c) for c in cmds),
        "denied": bool(deny_idx),
        "denied_n": len(deny_idx),
        "resubmitted": resubmitted,
        "events": ev,
    }


def compress(events):
    out = []
    for kind, text in events:
        if out and out[-1][0] == text:
            out[-1][1] += 1
        else:
            out.append([text, 1])
    return [t if n == 1 else f"{t} x{n}" for t, n in out]


def summarize(rows, blocks):
    n = len(rows)
    commit = [r for r in rows if r["commit"]]
    web = [r for r in rows if r["web"]]
    heavy = [r for r in rows if r["heavy"]]
    fin = [r for r in rows if r["final_zh"] is not None]
    denied_t = [r for r in rows if r["denied"]]
    denied_l = [r for r in rows if blocks.get(r["id"])]
    denied_u = [r for r in rows if r["denied"] or blocks.get(r["id"])]
    models = Counter(r["model"] for r in rows)
    return {
        "agents": n, "models": dict(models),
        "brief": [sum(r["brief"] for r in rows), n],
        "memory_read": [sum(r["mem"] for r in rows), n],
        "memory_read_by_read_tool": [sum(r["mem_tool"] for r in rows), n],
        "web": [len(web), n],
        "web_quick_first": [sum(r["web_quick"] for r in web), len(web)],
        "final_in_user_language": [sum(1 for r in fin if r["final_zh"]), len(fin)],
        "mid_text_english": [sum(r["mid_en"] for r in rows), sum(r["mid_total"] for r in rows)],
        "commit": [len(commit), n],
        "commit_branch_in_report": [sum(r["commit_branch_in_report"] for r in commit), len(commit)],
        "heavy": [len(heavy), n],
        "heavy_with_gate": [sum(r["gate"] for r in heavy), len(heavy)],
        "git_add_all": [sum(r["add_all"] for r in rows), n],
        "stash_or_reset": [sum(r["stash"] for r in rows), n],
        "kill_processes": [sum(r["kill"] for r in rows), n],
        "denied_transcript": [len(denied_t), n],
        "denied_log": [len(denied_l), n],
        "denied_union": [len(denied_u), n],
        "resubmitted_after_deny": [sum(1 for r in denied_t if r["resubmitted"]), len(denied_t)],
    }


def fmt(pair):
    return f"{pair[0]}/{pair[1]}"


def print_summary(s):
    models = "、".join(f"{k} {v}" for k, v in sorted(s["models"].items(), key=lambda kv: -kv[1]))
    lines = [
        ("agent 總數", f"{s['agents']}（{models}）"),
        ("開工補充送達", fmt(s["brief"])),
        ("讀過記憶內文", f"{fmt(s['memory_read'])}（用 Read 工具 {s['memory_read_by_read_tool'][0]}、其餘只經指令讀）"),
        ("有上網", fmt(s["web"])),
        ("  其中上網前先讀 web-quick", fmt(s["web_quick_first"])),
        (f"最終報告是使用者語言（中文比例≥{LANG_RATIO}）", fmt(s["final_in_user_language"])),
        ("中途文字英文則數／總則數", fmt(s["mid_text_english"])),
        ("有 commit", fmt(s["commit"])),
        ("  其中報告有交代分支", fmt(s["commit_branch_in_report"])),
        ("跑重型工作", fmt(s["heavy"])),
        ("  其中有過記憶體閘門", fmt(s["heavy_with_gate"])),
        ("git add -A", fmt(s["git_add_all"])),
        ("stash／reset --hard", fmt(s["stash_or_reset"])),
        ("整批結束程序", fmt(s["kill_processes"])),
        ("被守門退回（對話紀錄）", fmt(s["denied_transcript"])),
        ("被守門退回（source-guard.log）", fmt(s["denied_log"])),
        ("被守門退回（兩者聯集）", fmt(s["denied_union"])),
        ("  其中退回後有補交（對話紀錄有退回者）", fmt(s["resubmitted_after_deny"])),
    ]
    for k, v in lines:
        print(f"{k}：{v}")


def main():
    global LANG_RATIO
    ap = argparse.ArgumentParser(description="量派出的 agent 有沒有照規則做（只讀）")
    ap.add_argument("project", nargs="?", default=os.getcwd())
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--session", help="session id 前綴")
    g.add_argument("--latest", type=int, help="最近 N 場有 agent 的對話（預設 1）")
    g.add_argument("--since", help="YYYY-MM-DD 之後有 agent 活動的對話")
    ap.add_argument("--detail", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    pdir = find_project_dir(a.project)
    if not pdir:
        print(f"找不到這個專案的對話紀錄資料夾（{a.project} → {slug_of(a.project)}）；沒有可稽核的 agent。")
        return 0
    sessions = list_sessions(pdir)
    if a.session:
        sessions = [s for s in sessions if s[0].startswith(a.session)]
    elif a.since:
        try:
            ts = time.mktime(time.strptime(a.since, "%Y-%m-%d"))
        except ValueError:
            print("--since 要寫 YYYY-MM-DD")
            return 2
        sessions = [s for s in sessions if s[2] >= ts]
    else:
        sessions = sessions[: max(1, a.latest or 1)]
    if not sessions:
        print("這個專案沒有符合條件的 agent 對話紀錄。")
        return 0
    ug = load_guard()
    LANG_RATIO = ug.SUB_LANG_MIN_RATIO
    rows = []
    for sid, sub, _ in sessions:
        for f in sorted(glob.glob(os.path.join(sub, "agent-*.jsonl")), key=os.path.getmtime):
            r = analyze(f, ug, os.path.join(pdir, "memory"))
            r["session"] = sid
            rows.append(r)
    blocks = read_blocks(GUARD_LOG)
    summ = summarize(rows, blocks)
    if a.json:
        out = {"project": pdir, "sessions": [s[0] for s in sessions], "summary": summ,
               "agents": [{**{k: v for k, v in r.items() if k != "events"}, "guard_log_blocks": blocks.get(r["id"], 0),
                           "events": compress(r["events"])} for r in rows]}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    print(f"專案資料夾：{pdir}")
    print("對話：" + "、".join(f"{s[0][:8]}" for s in sessions))
    print_summary(summ)
    if a.detail:
        for r in rows:
            print()
            print(f"== {r['id'][:8]} {r['description']}｜{r['model']}/{r['effort']}｜補充送達={r['brief']}｜"
                  f"中途文字 {r['mid_total']} 則、英文 {r['mid_en']} 則｜守門退回 log={blocks.get(r['id'], 0)}")
            for e in compress(r["events"]):
                print("    " + e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
