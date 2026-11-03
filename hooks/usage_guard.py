"""claude-dev-system 用量守門 hook（通用版；來源：Stock-web tools/claude-setup/usage_guard.py，2026-10-17 抽成跨專案版）。

掛在 UserPromptSubmit、PostToolUse、Stop（0.11.8 起，只做查證守門，見 source_guard）與 SessionStart（0.12.0 起，壓縮／接續後重新開工，見 compact_msg）：
1. 讀本機 Claude 登入憑證（<CLAUDE_HOME>/.credentials.json）的 OAuth access token，呼叫 Anthropic 用量端點
   （非公開文件、社群工具同做法）取得 5 小時／7 天用量 %。端點改版時本腳本安靜失效、不擋操作。
2. 寫進 <CLAUDE_HOME>/state/usage.json（只有百分比與重置時間，不含權杖）。
3. 達門檻時注入「立刻收尾」提醒。門檻讀取順序（先找到者為準）：①專案 `.claude/dispatch-config.json`（從 hook 的 cwd 往上層找）
   →②全域 <CLAUDE_HOME>/claude-dev-system/config/dispatch-config.json →③內建預設 85／97。
   設定檔結構（0.7.0 起）：usageThresholdPct 直接給 fiveHour／sevenDay 兩個數字，沒到門檻完全不動、不提示。
   舊結構仍支援：plan.current 指定目前方案，usageThresholdPct[方案] 給 fiveHour／sevenDay；方案若有 until 日期，
   到期日（含）起自動改用 plan.after。--print 會印出實際採用的是哪一份。
4. 若有任務看板檔（<CLAUDE_HOME>/state/task-board.md），對標「該追問」的 agent 注入逾時提醒；沒有就略過。
5. 專案自動化（0.11.1）：UserPromptSubmit 時看 cwd——沒有 CLAUDE.md 且算專案 → 注入「先跑 cds-project-init」；有 CLAUDE.md 沒索引 → 注入「先跑 cds-project-audit」。
   同一場對話同一資料夾只注入一次（state/project-auto.json）。規則寫在 core.md 但 Claude 會漏（QTranslate 2026-11-01 實測沒觸發），所以改由 hook 判定。

安全：權杖只在記憶體使用、只送往 api.anthropic.com，不印、不寫檔、不記 log。任何錯誤一律 exit 0 不輸出。
手動檢查：python usage_guard.py --print
"""
import json
import os
import re
import sys
import time
import urllib.request

DEFAULTS = {"fiveHourLimit": 85.0, "sevenDayLimit": 97.0, "checkTtl": 300, "checkTtlNear": 60, "alertRepeat": 600,
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


# ---------- 專案自動化（0.11.1）：hook 判定、注入提示，不靠 Claude 自己記得 ----------
PA_STATE = os.path.join(STATE_DIR, "project-auto.json")
PA_EXCLUDE = {"node_modules", ".git", "dist", "build", ".venv", "venv", "__pycache__", ".next", "out", "coverage", ".pytest_cache",
              ".mypy_cache", ".idea", ".vscode", "vendor", "third_party", ".cache", "worktrees"}
PA_SOURCE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".cs", ".go", ".rs", ".java", ".kt", ".swift", ".c", ".cpp", ".h", ".rb", ".php",
                 ".ps1", ".cmd", ".bat", ".sh"}


PA_INT_KEYS = ("minSourceFiles", "staleFiles", "claudeMdMaxLines", "claudeMdMaxKB", "progressMaxLines", "newSessionAfterCompactions")


def _pa_config(cwd):
    """projectAutomation：專案 .claude/dispatch-config.json 優先，再全域，再預設。"""
    cfg = {"autoInit": True, "autoAudit": True, "autoRefactor": False, "minSourceFiles": 10,
           # 0.12.0 專案健康檢查（doc-governance 的門檻：CLAUDE.md 180 行、交接紀錄 600 行；盤點改過 >20 檔要重跑）
           "staleFiles": 20, "claudeMdMaxLines": 180, "claudeMdMaxKB": 20, "progressMaxLines": 600, "newSessionAfterCompactions": 3}
    for path in (CONFIG, os.path.join(cwd, ".claude", "dispatch-config.json")):
        try:
            with open(path, encoding="utf-8") as f:
                t = (json.load(f) or {}).get("projectAutomation") or {}
        except Exception:
            continue
        for k in ("autoInit", "autoAudit", "autoRefactor"):
            if isinstance(t.get(k), bool):
                cfg[k] = t[k]
        for k in PA_INT_KEYS:
            if isinstance(t.get(k), (int, float)) and not isinstance(t.get(k), bool) and t[k] >= 0:
                cfg[k] = int(t[k])
    return cfg


def _pa_count_sources(cwd, limit=3000, budget=0.5):
    """快速數原始碼檔：最多看 limit 個檔或 budget 秒，夠判定「算不算專案」就停。回 (原始碼檔數, 是否被截斷)。"""
    n = seen = 0
    t0 = time.time()
    for dp, dns, fns in os.walk(cwd):
        dns[:] = [d for d in dns if d not in PA_EXCLUDE and not d.startswith(".")]
        for fn in fns:
            seen += 1
            if os.path.splitext(fn)[1].lower() in PA_SOURCE_EXT:
                n += 1
            if seen >= limit or time.time() - t0 > budget:
                return n, True
    return n, False


def _pa_skip(cwd):
    """家目錄、磁碟根目錄、claude-dev-system 本身不做。回正規化的 cwd 或 None。"""
    if not cwd or not os.path.isdir(cwd):
        return None
    cwd = os.path.abspath(cwd)
    home = os.path.expanduser("~")
    if cwd in (home, os.path.dirname(cwd)) or os.path.dirname(cwd) == cwd:
        return None
    if os.path.exists(os.path.join(cwd, "installer", "cds", "paths.py")) and os.path.exists(os.path.join(cwd, "rules", "core.md")):
        return None
    return cwd


def _pa_load():
    try:
        with open(PA_STATE, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _pa_save(st):
    try:
        os.makedirs(os.path.dirname(PA_STATE), exist_ok=True)
        with open(PA_STATE, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
    except Exception:
        pass


def _count_newer(cwd, since, limit=20000, budget=0.8):
    """比 since（時間戳）新的檔案數，排除 PA_EXCLUDE 與點開頭的資料夾。回 (數量, 是否被截斷)。"""
    n = seen = 0
    t0 = time.time()
    for dp, dns, fns in os.walk(cwd):
        dns[:] = [d for d in dns if d not in PA_EXCLUDE and not d.startswith(".")]
        for fn in fns:
            seen += 1
            try:
                if os.path.getmtime(os.path.join(dp, fn)) > since:
                    n += 1
            except OSError:
                pass
            if seen >= limit or time.time() - t0 > budget:
                return n, True
    return n, False


def _lines(path):
    try:
        with open(path, "rb") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


HANDOFF_FILES = ("PROGRESS.md", "HANDOFF.md", "TODO.md", os.path.join("docs", "progress.md"))


def project_health(cwd):
    """可判定的健康檢查（0.12.0；Stock-web 一場對話開 19 天、盤點改過 205 檔沒重跑、CLAUDE.md 25 KB 超過上限才加）。回問題字串清單。"""
    cwd = _pa_skip(cwd)
    if not cwd:
        return []
    cfg = _pa_config(cwd)
    out = []
    idx = os.path.join(cwd, ".claude", "project-scan.json")
    if os.path.exists(idx) and cfg["staleFiles"]:
        n, trunc = _count_newer(cwd, os.path.getmtime(idx))
        if n > cfg["staleFiles"]:
            out.append(f"盤點索引之後改過 {n}{'+' if trunc else ''} 個檔（門檻 {cfg['staleFiles']}）→ 先跑 `py -3 ~/.claude/claude-dev-system/tools/project-scan.py . --check` 看改了什麼，"
                       "再照 skill `cds-project-audit` 重跑盤點更新 docs/PROJECT-INVENTORY.md 與問題清單（不用再問要不要重整）")
    md = os.path.join(cwd, "CLAUDE.md")
    if os.path.exists(md):
        ln, kb = _lines(md), os.path.getsize(md) / 1024
        over = []
        # 行數或大小任一超過都算：Stock-web 的 CLAUDE.md 不到 180 行但每行很長，25 KB 超過它自訂的 20 KB
        if cfg["claudeMdMaxKB"] and kb > cfg["claudeMdMaxKB"]:
            over.append(f"{kb:.0f} KB（上限 {cfg['claudeMdMaxKB']} KB）")
        if cfg["claudeMdMaxLines"] and ln > cfg["claudeMdMaxLines"]:
            over.append(f"{ln} 行（上限 {cfg['claudeMdMaxLines']} 行）")
        if over:
            out.append(f"專案 CLAUDE.md {'、'.join(over)} → 在收尾或空檔用 skill `cds-doc-governance` 瘦身（內容搬到分層檔，數字、原話、日期只能移不能刪；專案若自訂其他上限以專案為準）")
    for h in HANDOFF_FILES:
        p = os.path.join(cwd, h)
        if os.path.exists(p) and cfg["progressMaxLines"]:
            ln = _lines(p)
            if ln > cfg["progressMaxLines"]:
                out.append(f"{h} {ln} 行（上限 {cfg['progressMaxLines']} 行）→ 用 skill `cds-doc-governance` 把舊日誌搬到封存檔")
            break
    return out


def health_msg(cwd, force=False):
    """UserPromptSubmit：同一資料夾每天最多提醒一次；SessionStart（壓縮後）force=True 每次都看。"""
    try:
        c = _pa_skip(cwd)
        if not c:
            return None
        st = _pa_load()
        key = "health|" + c.lower()
        today = time.strftime("%Y-%m-%d")
        if not force and st.get(key) == today:
            return None
        probs = project_health(c)
        st[key] = today
        _pa_save(st)
        if not probs:
            return None
        return "【專案健康檢查（hook）】" + "；".join(f"{i}. {p}" for i, p in enumerate(probs, 1)) + "。在回答使用者這則之前或收尾時做，不要問要不要做。"
    except Exception:
        return None


def compact_msg(cwd, session_id):
    """SessionStart（compact／resume）：壓縮會把前面讀過的 skill、規則細節與開工檢查摘要掉；重新注入開工清單＋健康檢查＋專案自動化。
    同一場對話壓縮滿 newSessionAfterCompactions 次（及其倍數）建議開新對話。"""
    try:
        c = _pa_skip(cwd)
        parts = ["【壓縮後重新開工（hook）】對話剛被壓縮或接續，前面讀過的 skill 與規則細節可能只剩摘要。繼續工作前："
                 "①讀這個專案交接紀錄（PROGRESS.md、HANDOFF.md、TODO.md、docs/progress.md 任一）最後一節與專案 CLAUDE.md 的關鍵規則；"
                 "②有盤點索引就跑 `project-scan.py . --check`；③要上網查資料先重讀 `~/.claude/claude-dev-system/rules/web-quick.md`；"
                 "④改到被 3 處以上引用的函式／資料層前用 skill `cds-blast-radius`，派 agent 前用 `cds-agent-dispatch`。"]
        if c:
            h = health_msg(c, force=True)
            if h:
                parts.append(h)
            pa = project_auto_msg(c, None)
            if pa:
                parts.append(pa)
        if session_id:
            st = _pa_load()
            k = "compactions|" + session_id
            n = int(st.get(k, 0)) + 1
            st[k] = n
            _pa_save(st)
            lim = _pa_config(c)["newSessionAfterCompactions"] if c else 3
            if lim and n >= lim and n % lim == 0:
                parts.append(f"【建議開新對話（hook）】這場對話已被壓縮 {n} 次，早期內容只剩層層摘要，容易漏規則、記錯狀況。"
                             "在這則回答末尾用一句話建議使用者：先讓你更新交接紀錄（做了什麼、沒做完什麼、下一步），再開新對話接手。只建議，不要自己停工。")
        return LF_JOIN.join(parts)
    except Exception:
        return None


LF_JOIN = chr(10)


def project_auto_msg(cwd, session_id=None):
    """回要注入的提示字串，或 None。可判定條件（與 core.md「專案自動化」同一套）：
    init  ＝ 沒有 CLAUDE.md、算專案（git 或原始碼 ≥ minSourceFiles）、autoInit；
    audit ＝ 有 CLAUDE.md、沒有 .claude/project-scan.json、原始碼 ≥ minSourceFiles、autoAudit。
    同一個資料夾同一場對話只注入一次；claude-dev-system 自己、家目錄、磁碟根目錄不做。"""
    try:
        cwd = _pa_skip(cwd)
        if not cwd:
            return None
        cfg = _pa_config(cwd)
        has_md = os.path.exists(os.path.join(cwd, "CLAUDE.md"))
        has_idx = os.path.exists(os.path.join(cwd, ".claude", "project-scan.json"))
        is_git = os.path.exists(os.path.join(cwd, ".git"))
        n, truncated = _pa_count_sources(cwd)
        is_project = is_git or n >= cfg["minSourceFiles"]
        if not is_project:
            return None
        if not has_md and cfg["autoInit"]:
            what, skill = "init", "cds-project-init"
        elif has_md and not has_idx and n >= cfg["minSourceFiles"] and cfg["autoAudit"]:
            what, skill = "audit", "cds-project-audit"
        else:
            return None
        # 同一場對話同一資料夾只提醒一次
        key = cwd.lower()
        st = _pa_load()
        if session_id and isinstance(st.get(key), dict) and st[key].get("session") == session_id:
            return None
        st[key] = {"session": session_id, "what": what, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        _pa_save(st)
        facts = f"沒有 CLAUDE.md、" if not has_md else "有 CLAUDE.md 但沒有盤點索引、"
        facts += f"原始碼約 {n}{'+' if truncated else ''} 檔、{'git 專案' if is_git else '非 git'}"
        if what == "init":
            return ("【專案自動化（hook）】這個資料夾" + facts + f"，autoInit=true → 回答使用者之前先執行 skill `{skill}`"
                    "（project-scan.py 盤點、寫專案 CLAUDE.md、裝閘門、建 PROGRESS.md），做完用一句話告知再回答原本的問題；不要問要不要做。")
        return ("【專案自動化（hook）】這個資料夾" + facts + f"，autoAudit=true → 回答使用者之前先執行 skill `{skill}`"
                "（project-scan.py 盤點、docs/ARCHITECTURE.md、docs/PROJECT-ISSUES.md），達門檻只問一次要不要分階段重整"
                + ("（autoRefactor=true：不問，直接 cds-modularize）" if cfg["autoRefactor"] else "") + "，然後回答原本的問題。")
    except Exception:
        return None


# ---------- 查證守門（Stop）----------
# 另一台裝置的 Claude 2026-11-02 自評：規則只是指示，它判定「這題不算查證型」就整段跳過，寫了「2024 年 Google 披薩加膠水」
# 卻沒附來源。這裡把規則變成機械檢查：問答題的最後一則回覆含年份／數字卻沒有「來源」段 → block 一次要它補；
# 它補完再 Stop 時 stop_hook_active=true，不再擋。程式工作（回覆含程式碼區塊）、純概念（沒有數字）、非問句都不擋。
SG_LOCAL = os.path.join(HOME, "claude-dev-system", "config", "local.json")
SG_YEAR = re.compile(r"(?<![\d.])(?:19|20)\d{2}\s*年")
SG_NUM = re.compile(r"\d[\d,.]*\s*(?:萬|億|兆|元|％|%|美元|日圓|歐元|人民幣|公里|公尺|公分|公斤|公噸|公頃|坪|人|戶|家|km|kg|GB|MB|TB|kWh|ppm|μg|µg)")
SG_SOURCE = ("來源", "http://", "https://", "未附來源", "未能確認", "不含待查證事實")
SG_QUESTION = ("嗎", "?", "？", "多少", "什麼", "甚麼", "如何", "怎麼", "為什麼", "為何", "哪", "是不是", "有沒有", "幾")
SG_MIN_ANSWER = 200


def sg_enabled():
    try:
        with open(SG_LOCAL, encoding="utf-8") as f:
            return bool((json.load(f) or {}).get("sourceGuard", True))
    except Exception:
        return True


def _sg_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None  # 工具結果不是使用者的話
        return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return None


def sg_last_turn(transcript_path):
    """回 (最後一則使用者提示, 之後所有助理文字合併)。讀不到回 (None, None)。"""
    prompt, answer = None, []
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"type":"user"' in line or '"type": "user"' in line:
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    if d.get("type") != "user" or d.get("isSidechain"):
                        continue
                    t = _sg_text((d.get("message") or {}).get("content"))
                    if t is not None and t.strip():
                        prompt, answer = t, []
                elif '"type":"assistant"' in line or '"type": "assistant"' in line:
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    if d.get("type") != "assistant" or d.get("isSidechain"):
                        continue
                    for b in (d.get("message") or {}).get("content") or []:
                        if isinstance(b, dict) and b.get("type") == "text" and b.get("text"):
                            answer.append(b["text"])
    except Exception:
        return None, None
    return prompt, "\n".join(answer)


def sg_judge(prompt, answer):
    """要不要退回。回 None（放行）或原因字串。"""
    if not prompt or not answer or len(answer) < SG_MIN_ANSWER:
        return None
    if "```" in answer:  # 程式工作：回覆裡的數字多半是行數、測試數，不是事實宣稱
        return None
    if not any(q in prompt for q in SG_QUESTION):
        return None
    if any(m in answer for m in SG_SOURCE):
        return None
    years = SG_YEAR.findall(answer)
    nums = SG_NUM.findall(answer)
    if not years and not nums:
        return None
    return f"含 {len(years)} 個年份、{len(nums)} 個帶單位數字"


def source_guard(payload):
    if payload.get("stop_hook_active") or not sg_enabled():
        return None
    prompt, answer = sg_last_turn(payload.get("transcript_path") or "")
    why = sg_judge(prompt, answer)
    if not why:
        return None
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(os.path.join(STATE_DIR, "source-guard.log"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} block {why}｜問：{(prompt or '')[:60]!r}" + chr(10))
    except Exception:
        pass
    return {"decision": "block",
            "reason": "【查證守門（hook）】這則回覆" + why + "，但沒有「來源」段。請補上：每個關鍵年份／數字旁附網址、資料日期、來源原句逐字短引；"
                      "查不到的標〔未附來源〕或刪掉沒把握的數字；自己的推論另立「我的補充／推測」段；末尾固定「來源」與「查證過程」（最多 3 行）。"
                      "若這些數字不是事實宣稱（例如純概念舉例、你自己算的），在回覆末尾加一行「〔不含待查證事實〕」即可，不必重寫。只補這一次，之後不會再退回。"}


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
    if event == "Stop":  # 查證守門：只看回覆，不查用量
        out = source_guard(payload)
        if out:
            print(json.dumps(out, ensure_ascii=True))
        return
    if event == "SessionStart":  # 0.12.0：壓縮或接續後重新開工；新對話（startup）由 UserPromptSubmit 的專案自動化處理
        if payload.get("source") in ("compact", "resume"):
            msg = compact_msg(payload.get("cwd"), payload.get("session_id"))
            if msg:
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": msg}}, ensure_ascii=True))
        return
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
        try:
            got = fetch()
        except Exception:  # noqa: BLE001  離線、權杖過期、429、逾時：都不能每次 hook 重打（每次最多拖 8 秒）
            got = None
        if got is None:
            s["fetched_at"] = now  # 失敗也記時間：下次要等 checkTtl 才再試（退避）
            s["fetch_failed_at"] = now
            save_state(s)
            if printing:
                print("讀不到用量（沒有登入憑證、離線或端點改版）；下次 hook 會在 TTL 後再試")
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
    if event == "UserPromptSubmit":  # 專案自動化：每則提示都判定，但同一場對話同一資料夾只注入一次
        pa = project_auto_msg(hook_cwd, payload.get("session_id"))
        if pa:
            msgs.append(pa)
        hm = health_msg(hook_cwd)  # 盤點過期、CLAUDE.md／交接紀錄過大：同資料夾每天一次
        if hm:
            msgs.append(hm)
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
