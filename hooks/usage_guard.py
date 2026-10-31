"""claude-dev-system 用量守門 hook（通用版；來源：Stock-web tools/claude-setup/usage_guard.py，2026-10-17 抽成跨專案版）。

掛在 UserPromptSubmit 與 PostToolUse：
1. 讀本機 Claude 登入憑證（<CLAUDE_HOME>/.credentials.json）的 OAuth access token，呼叫 Anthropic 用量端點
   （非公開文件、社群工具同做法）取得 5 小時／7 天用量 %。端點改版時本腳本安靜失效、不擋操作。
2. 寫進 <CLAUDE_HOME>/state/usage.json（只有百分比與重置時間，不含權杖）。
3. 達門檻時注入「立刻收尾」提醒。門檻讀取順序（先找到者為準）：①專案 `.claude/dispatch-config.json`（從 hook 的 cwd 往上層找）
   →②全域 <CLAUDE_HOME>/claude-dev-system/config/dispatch-config.json →③內建預設 80／97。
   設定檔結構（0.7.0 起）：usageThresholdPct 直接給 fiveHour／sevenDay 兩個數字，沒到門檻完全不動、不提示。
   舊結構仍支援：plan.current 指定目前方案，usageThresholdPct[方案] 給 fiveHour／sevenDay；方案若有 until 日期，
   到期日（含）起自動改用 plan.after。--print 會印出實際採用的是哪一份。
4. 若有任務看板檔（<CLAUDE_HOME>/state/task-board.md），對標「該追問」的 agent 注入逾時提醒；沒有就略過。

安全：權杖只在記憶體使用、只送往 api.anthropic.com，不印、不寫檔、不記 log。任何錯誤一律 exit 0 不輸出。
手動檢查：python usage_guard.py --print
"""
import json
import os
import re
import sys
import time
import urllib.request

DEFAULTS = {"fiveHourLimit": 80.0, "sevenDayLimit": 97.0, "checkTtl": 300, "checkTtlNear": 60, "alertRepeat": 600,
            "nearFiveHour": 70.0, "nearSevenDay": 90.0}
STALE_REPEAT = 600
URL = "https://api.anthropic.com/api/oauth/usage"


def claude_home():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


HOME = claude_home()
CRED = os.path.join(HOME, ".credentials.json")
STATE_DIR = os.path.join(HOME, "state")
USAGE = os.path.join(STATE_DIR, "usage.json")
BOARD_FILE = os.path.join(STATE_DIR, "task-board.md")
CONFIG = os.path.join(HOME, "claude-dev-system", "config", "dispatch-config.json")
PROJECT_CONFIG_REL = os.path.join(".claude", "dispatch-config.json")


def find_project_config(start):
    """從 start 往上層找 .claude/dispatch-config.json；找不到回 None。"""
    try:
        d = os.path.abspath(start or os.getcwd())
    except Exception:
        return None
    while True:
        cand = os.path.join(d, PROJECT_CONFIG_REL)
        if os.path.isfile(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def pick_thresholds(cfg, today=None):
    """取 usageThresholdPct。0.7.0 起的扁平格式：{"fiveHour": 95, "sevenDay": 99}（沒有方案概念，GUI 直接改數字）。
    舊格式（依 plan.current 選方案、until 到期改用 plan.after）仍支援。回 (五小時, 七天) 或 None。"""
    plan = cfg.get("plan") or {}
    table = cfg.get("usageThresholdPct") or {}
    if isinstance(table.get("fiveHour"), (int, float)) and isinstance(table.get("sevenDay"), (int, float)):
        return float(table["fiveHour"]), float(table["sevenDay"])
    cur = plan.get("current")
    today = today or time.strftime("%Y-%m-%d")
    until = (plan.get(cur) or {}).get("until") if isinstance(plan.get(cur), dict) else None
    if until and today >= until and plan.get("after"):
        cur = plan["after"]
    t = table.get(cur) if isinstance(table.get(cur), dict) else None
    if t and isinstance(t.get("fiveHour"), (int, float)) and isinstance(t.get("sevenDay"), (int, float)):
        return float(t["fiveHour"]), float(t["sevenDay"])
    return None


def load_limits(cwd=None):
    """回 (限制 dict, 來源說明)。來源：專案設定檔／全域設定檔／內建預設。"""
    cfg = dict(DEFAULTS)
    source = "內建預設"
    for label, path in (("專案", find_project_config(cwd)), ("全域", CONFIG)):
        if not path:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            continue
        th = pick_thresholds(data)
        if th is None:
            continue
        cfg["fiveHourLimit"], cfg["sevenDayLimit"] = th
        adj = data.get("dispatchUsageAdjust") or {}
        if isinstance(adj.get("fiveHourBelowPct"), (int, float)):
            cfg["nearFiveHour"] = float(adj["fiveHourBelowPct"])
        if isinstance(adj.get("sevenDayAbovePct"), (int, float)):
            cfg["nearSevenDay"] = float(adj["sevenDayAbovePct"])
        source = f"{label}設定檔 {path}"
        break
    return cfg, source


def load_state():
    try:
        with open(USAGE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(s):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = USAGE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)
    os.replace(tmp, USAGE)


def fetch():
    with open(CRED, encoding="utf-8") as f:
        c = json.load(f)
    token = (c.get("claudeAiOauth") or {}).get("accessToken") or c.get("accessToken")
    if not token:
        return None
    req = urllib.request.Request(URL, headers={
        "Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20",
        "Content-Type": "application/json", "User-Agent": "claude-dev-system-usage-guard"})
    with urllib.request.urlopen(req, timeout=8) as r:
        d = json.loads(r.read().decode("utf-8"))

    def pick(k):
        w = d.get(k) or {}
        u = w.get("utilization")
        return (float(u) if isinstance(u, (int, float)) else None), w.get("resets_at")
    five, five_reset = pick("five_hour")
    seven, seven_reset = pick("seven_day")
    return {"five_hour_pct": five, "five_hour_resets_at": five_reset, "seven_day_pct": seven, "seven_day_resets_at": seven_reset}


def stale_agents():
    try:
        with open(BOARD_FILE, encoding="utf-8") as f:
            text = f.read()
    except Exception:
        return []
    out = []
    for m in re.finditer(r'<div class="ct">[^<]*?\s([^<]+)</div><div class="cm">([^<]*)</div>', text):
        title, meta = m.group(1).strip(), m.group(2)
        if "該追問" in meta and not title.startswith("主對話"):
            out.append(title)
    return out


def main():
    printing = "--print" in sys.argv
    event = ""
    payload = {}
    if not printing:
        try:
            payload = json.load(sys.stdin) or {}
            event = payload.get("hook_event_name", "")
        except Exception:
            event = ""
    hook_cwd = None
    if not printing:
        try:
            hook_cwd = payload.get("cwd")
        except Exception:
            hook_cwd = None
    lim, source = load_limits(hook_cwd)
    s = load_state()
    now = time.time()
    near = (s.get("five_hour_pct") or 0) >= lim["nearFiveHour"] or (s.get("seven_day_pct") or 0) >= lim["nearSevenDay"]
    ttl = lim["checkTtlNear"] if near else lim["checkTtl"]
    if printing or now - s.get("fetched_at", 0) >= ttl:
        got = fetch()
        if got is None:
            return
        s.update(got)
        s["fetched_at"] = now
        s["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        save_state(s)
    five, seven = s.get("five_hour_pct"), s.get("seven_day_pct")
    if printing:
        print(f"5 小時 {five}%（重置 {s.get('five_hour_resets_at')}）；7 天 {seven}%（重置 {s.get('seven_day_resets_at')}）"
              f"；門檻 {lim['fiveHourLimit']:.0f}／{lim['sevenDayLimit']:.0f}（來源：{source}）")
        return
    hit = []
    if five is not None and five >= lim["fiveHourLimit"]:
        hit.append(f"5 小時用量 {five:.0f}%（門檻 {lim['fiveHourLimit']:.0f}%）")
    if seven is not None and seven >= lim["sevenDayLimit"]:
        hit.append(f"7 天用量 {seven:.0f}%（門檻 {lim['sevenDayLimit']:.0f}%，收尾要做詳細版）")
    msgs = []
    if hit and not (event == "PostToolUse" and now - s.get("alerted_at", 0) < lim["alertRepeat"]):
        s["alerted_at"] = now
        msgs.append("【用量守門（自動）】" + "、".join(hit) + "。主 agent：依全域規則「用量收尾」執行收尾"
                    "（不再派新 agent、列出已完成與未完成、通知執行中的 agent 收尾、更新專案的交接紀錄、推送）。"
                    "子 agent：把可運作的部分 commit、未完成改動存 patch，回報 main 後結束。")
    stale = stale_agents()
    key = "|".join(sorted(stale))
    if stale and (key != s.get("stale_key") or now - s.get("stale_alerted_at", 0) >= STALE_REPEAT):
        s["stale_key"] = key
        s["stale_alerted_at"] = now
        msgs.append("【看板逾時提醒（自動）】這些 agent 超過預估 10 分鐘以上沒有新回報：" + "、".join(stale) +
                    "。主 agent：SendMessage 追問；已交最終報告的就 TaskStop。子 agent 忽略此則。")
    if not msgs:
        return
    save_state(s)
    out = {"hookSpecificOutput": {"hookEventName": event or "UserPromptSubmit", "additionalContext": "\n".join(msgs)}}
    print(json.dumps(out, ensure_ascii=True))  # Windows 主控台 cp950 會讓 UTF-8 中文變亂碼，ASCII 跳脫最安全


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
