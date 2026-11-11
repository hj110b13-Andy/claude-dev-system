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


PA_INT_KEYS = ("minSourceFiles", "staleFiles", "claudeMdMaxLines", "claudeMdMaxKB", "progressMaxLines", "progressMaxKB", "newSessionAfterCompactions")


def _pa_config(cwd):
    """projectAutomation：專案 .claude/dispatch-config.json 優先，再全域，再預設。"""
    cfg = {"autoInit": True, "autoAudit": True, "autoRefactor": False, "alignOnUpdate": True, "verifySkill": True, "minSourceFiles": 10,
           # 0.12.0 專案健康檢查（doc-governance 的門檻：CLAUDE.md 180 行、交接紀錄 600 行；盤點改過 >20 檔要重跑）
           # 0.13.0 交接紀錄加 KB 上限（Stock-web PROGRESS.md 510 行卻 355 KB）
           "staleFiles": 20, "claudeMdMaxLines": 180, "claudeMdMaxKB": 20, "progressMaxLines": 600, "progressMaxKB": 100,
           "newSessionAfterCompactions": 3}
    for path in (CONFIG, os.path.join(cwd, ".claude", "dispatch-config.json")):
        try:
            with open(path, encoding="utf-8") as f:
                t = (json.load(f) or {}).get("projectAutomation") or {}
        except Exception:
            continue
        for k in ("autoInit", "autoAudit", "autoRefactor", "alignOnUpdate", "verifySkill"):
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
    """家目錄、磁碟根目錄、claude-dev-system 本身不做。回正規化的專案資料夾（子資料夾會往上找 git 根目錄）或 None。"""
    if not cwd or not os.path.isdir(cwd):
        return None
    cwd = os.path.abspath(cwd)
    home = os.path.expanduser("~")
    # 0.22.0：工作目錄在專案的子資料夾時（沒有自己的 .git／CLAUDE.md），往上找到 git 根目錄當專案——2026-11-11 這個 repo 的對話
    # cd 到 installer/ 後被判成「沒有 CLAUDE.md、非 git 的新專案」要求初始化。只認 .git（上層的 CLAUDE.md 可能是工作區共用的，不代表專案根）。
    if not os.path.exists(os.path.join(cwd, ".git")) and not os.path.exists(os.path.join(cwd, "CLAUDE.md")):
        d = os.path.dirname(cwd)
        while d and d != os.path.dirname(d) and d != home:
            if os.path.exists(os.path.join(d, ".git")):
                cwd = d
                break
            d = os.path.dirname(d)
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


def _git_ignored(cwd):
    """.gitignore 排除的 (檔案, 資料夾) 相對路徑集合。唯一來源：同一份安裝裡 tools/project-scan.py 的 git_ignored
    （0.15.0：盤點 --check 已不算被排除的檔，這裡原本照算，Stock-web 436 個評測輸出會讓「盤點過期」提早觸發）。讀不到就回空集合＝照舊。"""
    try:
        import importlib.util
        from pathlib import Path
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "project-scan.py")
        spec = importlib.util.spec_from_file_location("cds_project_scan", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.git_ignored(Path(cwd))
    except Exception:
        return set(), set()


def _count_newer(cwd, since, limit=20000, budget=0.8):
    """比 since（時間戳）新的檔案數，排除 PA_EXCLUDE、點開頭的資料夾與 .gitignore 排除的檔。回 (數量, 是否被截斷)。"""
    n = seen = 0
    t0 = time.time()
    ign_files, ign_dirs = _git_ignored(cwd)
    for dp, dns, fns in os.walk(cwd):
        rel = os.path.relpath(dp, cwd).replace(os.sep, "/")
        prefix = "" if rel == "." else rel + "/"
        dns[:] = [d for d in dns if d not in PA_EXCLUDE and not d.startswith(".") and prefix + d not in ign_dirs]
        for fn in fns:
            if prefix + fn in ign_files:
                continue
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


def _needs_verify_skill(cwd):
    """0.14.0：可判定的「有畫面或可啟動服務」＋專案 .claude/skills/ 底下沒有名稱含 verify 的 skill。"""
    web = False
    try:
        with open(os.path.join(cwd, "package.json"), encoding="utf-8") as f:
            scripts = (json.load(f) or {}).get("scripts") or {}
        web = any(k in scripts for k in ("dev", "start", "serve", "preview"))
    except Exception:
        pass
    if not web:
        web = any(os.path.exists(os.path.join(cwd, n)) for n in ("manage.py", "index.html"))
    if not web:
        return False
    sk = os.path.join(cwd, ".claude", "skills")
    try:
        names = os.listdir(sk)
    except OSError:
        names = []
    return not any("verify" in n.lower() and os.path.exists(os.path.join(sk, n, "SKILL.md")) for n in names)


def big_file_exceptions(cwd):
    """行數上限例外清單（唯一來源）：專案 .claude/dispatch-config.json 的 projectAutomation.bigFileExceptions {"相對路徑": "原因"}。
    原因空白不算例外（cds-modularize：例外逐檔寫原因）。專案的行數閘門測試也應讀這一份。"""
    try:
        with open(os.path.join(cwd, ".claude", "dispatch-config.json"), encoding="utf-8") as f:
            ex = ((json.load(f) or {}).get("projectAutomation") or {}).get("bigFileExceptions") or {}
        return {k.replace(chr(92), "/"): v for k, v in ex.items() if isinstance(v, str) and v.strip()}
    except Exception:
        return {}


def _big_files(cwd, idx):
    """0.13.1：讀盤點索引的 big-file 問題，扣掉例外清單；舊版索引（version < 2，不算 scripts/、tools/）要求重跑盤點。
    Stock-web 重整後閘門只管 src/，scripts/backtest/exitStrategy.ts 6,588 行沒有任何機制提醒。"""
    if not os.path.exists(idx) or os.path.getsize(idx) > 50_000_000:
        return None
    try:
        with open(idx, encoding="utf-8") as f:
            d = json.load(f) or {}
    except Exception:
        return None
    if int(d.get("version") or 1) < 2:
        return ("盤點索引是舊版掃描（大檔檢查沒算 scripts/、tools/ 底下的研究／回測腳本）→ 重跑 "
                "`py -3 ~/.claude/claude-dev-system/tools/project-scan.py .` 更新索引與 docs/PROJECT-INVENTORY.md，再看有沒有超過行數上限的檔")
    ex = big_file_exceptions(cwd)
    lim = int(d.get("maxLines") or 800)
    big = []
    # 0.16.0：報之前比對實際行數——索引是舊的時候會一直報已拆掉的檔（Stock-web 11/8～11/9：exitStrategy.ts 已拆成 26 行，
    # 健康檢查仍報「6588 行 > 800」）。檔案不在或已不超標就不報；還超標的報現在的行數。最多看 20 個，不拖慢 hook。
    for p in [p for p in d.get("problems") or [] if p.get("kind") == "big-file" and p.get("file") not in ex][:20]:
        fp = os.path.join(cwd, p["file"])
        if not os.path.isfile(fp):
            continue
        n = _lines(fp)
        if n > lim:
            big.append(f"{p['file']}（現在 {n} 行 > {lim}{'（腳本）' if '腳本' in str(p.get('detail', '')) else ''}）")
    if not big:
        return None
    shown = "、".join(big[:5]) + (f" 等 {len(big)} 個" if len(big) > 5 else "")
    return (f"超過行數上限 {lim} 行、且不在例外清單的檔：{shown} → 照 skill `cds-modularize`（C 逐模組＋保護網）排進待辦拆檔，"
            "並把行數閘門測試的範圍擴到這些目錄；確定是一次性不再修改的才寫進 `.claude/dispatch-config.json` 的 "
            "`projectAutomation.bigFileExceptions`（檔案→原因）。這一項現在要做的是：列進交接紀錄待辦、告訴使用者並提出拆檔時程；"
            "拆檔本身屬大工程，使用者同意後才開拆")


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
    big = _big_files(cwd, idx)
    if big:
        out.append(big)
    if cfg["verifySkill"] and _needs_verify_skill(cwd):
        out.append("這是有畫面或可啟動服務的專案（package.json 有 dev／start／serve／preview，或有 manage.py、index.html），但 `.claude/skills/` 沒有驗證 skill"
                   " → 用 skill `cds-verify-app` 生成專案驗證 skill（怎麼啟動、功能↔檔案地圖），之後改動照地圖只驗相關功能")
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
        if os.path.exists(p) and (cfg["progressMaxLines"] or cfg["progressMaxKB"]):
            ln, kb = _lines(p), os.path.getsize(p) / 1024
            over = []
            # 行數或大小任一超過都算：Stock-web PROGRESS.md 510 行卻有 355 KB（每行很長），只看行數抓不到（2026-11-03）
            if cfg["progressMaxLines"] and ln > cfg["progressMaxLines"]:
                over.append(f"{ln} 行（上限 {cfg['progressMaxLines']} 行）")
            if cfg["progressMaxKB"] and kb > cfg["progressMaxKB"]:
                over.append(f"{kb:.0f} KB（上限 {cfg['progressMaxKB']} KB）")
            if over:
                out.append(f"{h} {'、'.join(over)} → 用 skill `cds-doc-governance` 把舊日誌搬到封存檔")
            break
    return out


def health_msg(cwd, force=False, session_id=None):
    """UserPromptSubmit：同一資料夾、同一場對話每天最多提醒一次；SessionStart（壓縮後）force=True 每次都看。
    0.13.0 加對話：原本只看資料夾＋日期，舊對話當天先用掉，同一天新開的對話就收不到（Stock-web 2026-11-03）。"""
    try:
        c = _pa_skip(cwd)
        if not c:
            return None
        st = _pa_load()
        key = "health|" + c.lower()
        mark = time.strftime("%Y-%m-%d") + ("|" + session_id if session_id else "")
        if not force and st.get(key) == mark:
            return None
        probs = project_health(c)
        st[key] = mark
        _pa_save(st)
        if not probs:
            return None
        return "【專案健康檢查（hook）】" + "；".join(f"{i}. {p}" for i, p in enumerate(probs, 1)) + "。在回答使用者這則之前或收尾時做，不要問要不要做。"
    except Exception:
        return None


# 0.23.0：agent 自己壓縮對話時，Claude Code 也會觸發 SessionStart(compact)，payload 不帶任何 agent 欄位（anthropics/claude-code#91910，
# 2.1.322 仍 open）。2026-11-11 在這台重現：一個探針 agent 壓縮 3 次，3 次【壓縮後重新開工】都被注入到 agent 裡，主對話的壓縮計數被加到 3。
# 分辨方式：壓縮完成時該對話紀錄會先寫一筆 compact_boundary（實測比 hook 注入早約 0.2 秒）。主對話紀錄沒有剛寫的 boundary、
# 而某個 agent 紀錄有 → 是 agent 的壓縮，不注入、不計數。讀不到或判不出來一律照舊注入（寧可多注入，不可讓主對話漏掉重新開工）。
COMPACT_FRESH_SEC = 15  # 自己定的：實測間隔 0.2 秒，留寫檔延遲的餘裕
COMPACT_TAIL = 2000000  # 只讀紀錄尾端這麼多位元組（agent 一次讀好幾段大檔時，最後一次請求之後可能加進數百 KB）


def _fresh_compact_boundary(path, now=None):
    """這份對話紀錄尾端有沒有 COMPACT_FRESH_SEC 秒內寫入的 compact_boundary。"""
    try:
        import datetime
        now = now or time.time()
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - COMPACT_TAIL))
            tail = f.read().decode("utf-8", errors="replace")
        for line in reversed(tail.splitlines()):
            if '"compact_boundary"' not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("subtype") != "compact_boundary":
                continue
            ts = datetime.datetime.fromisoformat(str(d.get("timestamp")).replace("Z", "+00:00")).timestamp()
            return 0 <= now - ts <= COMPACT_FRESH_SEC
        return False
    except Exception:
        return False


def _hook_debug(tag, payload):
    """診斷用：<CLAUDE_HOME>/state/hook-debug.on 存在時，把 hook 收到的 payload 與當下看到的檔案狀態附加到 hook-debug.jsonl。
    平常不存在這個檔，完全不做事。"""
    try:
        if not os.path.exists(os.path.join(STATE_DIR, "hook-debug.on")):
            return
        now = time.time()
        tp = payload.get("transcript_path") or ""
        sub = os.path.join(os.path.dirname(tp), str(payload.get("session_id") or ""), "subagents")
        files = []
        for base, names in ((os.path.dirname(tp), [os.path.basename(tp)]), (sub, os.listdir(sub) if os.path.isdir(sub) else [])):
            for n in names:
                fp = os.path.join(base, n)
                if n.endswith(".jsonl") and os.path.isfile(fp):
                    with open(fp, "rb") as f:
                        f.seek(0, 2)
                        size = f.tell()
                        f.seek(max(0, size - COMPACT_TAIL))
                        tail = f.read().decode("utf-8", errors="replace")
                    ts = [json.loads(x).get("timestamp") for x in tail.splitlines() if '"compact_boundary"' in x and x.lstrip().startswith("{")]
                    files.append({"file": n, "size": size, "mtime_age": round(now - os.path.getmtime(fp), 2), "boundaries": ts[-3:],
                                  "fresh": _fresh_compact_boundary(fp, now)})
        with open(os.path.join(STATE_DIR, "hook-debug.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"tag": tag, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "now": now,
                                "payload": {k: (v if not isinstance(v, str) or len(v) < 300 else v[:300]) for k, v in payload.items()},
                                "files": files}, ensure_ascii=False) + chr(10))
    except Exception:
        pass


def _last_model(path):
    """這份對話紀錄最後一則助理訊息用的模型（讀尾端）。讀不到回 None。"""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - COMPACT_TAIL))
            tail = f.read().decode("utf-8", errors="replace")
        for line in reversed(tail.splitlines()):
            if '"assistant"' not in line or '"model"' not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            m = (d.get("message") or {}).get("model") if d.get("type") == "assistant" else None
            if m and not str(m).startswith("<"):
                return str(m)
        return None
    except Exception:
        return None


COMPACT_ACTIVE_SEC = 180  # 自己定的：agent 紀錄這麼久內有寫入才算「正在跑」（壓縮本身實測 11～22 秒沒有寫入）
COMPACT_TOKEN_MARGIN = 1.1  # 自己定的：模型相同時，agent 最後一次請求的 context 要比主對話大一成以上才判定是它在壓縮


COMPACT_CHARS_PER_TOKEN = 4  # 自己定的粗估：最後一次請求之後才寫進紀錄的內容，每 4 個字元算 1 token


def _tail_lines(path):
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - COMPACT_TAIL))
        tail = f.read().decode("utf-8", errors="replace")
    lines = tail.splitlines()
    return lines[1:] if size > COMPACT_TAIL else lines


def _last_tokens(path):
    """這份對話紀錄目前大約有多少 context：最後一次請求的大小（input＋cache 讀寫）＋那之後才加進來的內容（工具結果等）的粗估。
    只看最後一次請求會低估——agent 一次呼叫好幾個工具時，結果要到下一次請求才算進去（2026-11-11 實跑第二次壓縮因此判錯）。"""
    try:
        lines = _tail_lines(path)
        for i in range(len(lines) - 1, -1, -1):
            if '"usage"' not in lines[i]:
                continue
            try:
                d = json.loads(lines[i])
            except Exception:
                continue
            u = (d.get("message") or {}).get("usage") if d.get("type") == "assistant" else None
            if u:
                n = int(u.get("input_tokens") or 0) + int(u.get("cache_read_input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0)
                if n:
                    return n + sum(len(x) for x in lines[i + 1:]) // COMPACT_CHARS_PER_TOKEN
        # 尾端整段都沒有請求紀錄（之後加進來的內容比讀取範圍還大）：至少有尾端這麼多
        return (sum(len(x) for x in lines) // COMPACT_CHARS_PER_TOKEN) or None
    except Exception:
        return None


def _waiting_on_tool(path):
    """主對話是不是正卡在等工具結果（最後一則助理訊息呼叫了工具，結果還沒回來）。這時它不會送請求，也就不可能是它在壓縮。"""
    try:
        pending = set()
        for line in _tail_lines(path):
            if '"tool_use"' not in line and '"tool_result"' not in line and '"assistant"' not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("isSidechain"):
                continue
            c = (d.get("message") or {}).get("content")
            if not isinstance(c, list):
                continue
            if d.get("type") == "assistant":
                ids = {x.get("id") for x in c if isinstance(x, dict) and x.get("type") == "tool_use"}
                pending = ids if ids else set()
            elif d.get("type") == "user":
                pending -= {x.get("tool_use_id") for x in c if isinstance(x, dict) and x.get("type") == "tool_result"}
        return bool(pending)
    except Exception:
        return False


def compact_from_subagent(payload, now=None, poll=None):
    """SessionStart(compact) 是不是某個 agent 自己壓縮觸發的（不是主對話）。有明確證據才回 True，判不出來回 False（照舊注入）。
    2026-11-11 實測（hook-debug）：hook 執行當下 compact_boundary 還沒寫進檔（非同步，等 2 秒也沒有），prompt_id 主對話與 agent 共用，
    都不能用。依序用這三個依據（前提都是有正在跑的 agent）：
    ①payload.model（正在壓縮那一方的模型）≠ 主對話最後一則助理訊息的模型，且＝某個正在跑的 agent 的模型 → agent。
    ②主對話正卡在等工具結果（例如前景 agent）→ 它不可能在壓縮 → agent。
    ③模型相同、主對話沒在等工具：比 context 大小，agent 的估計值 ≥ 主對話的 COMPACT_TOKEN_MARGIN 倍 → agent。
    poll 參數保留給舊呼叫相容，沒有作用。"""
    try:
        tp = payload.get("transcript_path") or ""
        sid = str(payload.get("session_id") or "")
        if not tp or not sid:
            return False
        now0 = now or time.time()
        sub = os.path.join(os.path.dirname(tp), sid, "subagents")
        try:
            active = [os.path.join(sub, n) for n in os.listdir(sub)
                      if n.endswith(".jsonl") and now0 - os.path.getmtime(os.path.join(sub, n)) <= COMPACT_ACTIVE_SEC]
        except OSError:
            active = []
        if not active:
            return False  # 沒有正在跑的 agent：一定是主對話
        if _fresh_compact_boundary(tp, now0):
            return False  # 主對話紀錄已經有剛寫的壓縮標記
        pm, mm = str(payload.get("model") or ""), _last_model(tp)
        if pm and mm and pm != mm:
            return any(_last_model(f) == pm for f in active)
        if any(_fresh_compact_boundary(f, now0) for f in active):
            return True
        if _waiting_on_tool(tp):
            return True
        mt = _last_tokens(tp)
        cands = [f for f in active if not pm or _last_model(f) == pm]
        at = max([_last_tokens(f) or 0 for f in cands] or [0])
        return bool(mt) and at >= mt * COMPACT_TOKEN_MARGIN
    except Exception:
        return False


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


# ---------- 全域系統對照（0.13.0）----------
# Stock-web 2026-11-03：已有 CLAUDE.md 與盤點索引的專案走「③已有索引」分支，hook 什麼都不注入；新對話只回答了使用者問的進度，
# 使用者要再問「看看全域規則有沒有這個專案要做的優化」才列出 7 項（規則矛盾、CLAUDE.md／PROGRESS 超標、盤點過期…）。
# 改成：全域系統主.次版號跟這個專案上次對照時不同（或從沒對照過）→ 注入一次，要它在回答末尾主動列出並做可逆的部分。
SYS_VERSION = os.path.join(HOME, "claude-dev-system", "config", "VERSION")


def _minor(v):
    """'0.12.3' → (0, 12)；讀不懂回 None。修訂號只是修正，不觸發對照。"""
    try:
        a, b = (v or "").strip().split(".")[:2]
        return int(a), int(b)
    except Exception:
        return None


# 0.16.0：全域規則改過、專案規則裡常寫死的舊條文——對照時直接點名檔案與行號，不靠 Claude 自己翻到。
# (正規式, 說明)；新增已知過時條文就加一列。
STALE_RULES = [
    (re.compile(r"git\s+pull\s+(?:--rebase(?!=merges)\b|-r\b)"),
     "寫死 `git pull --rebase`：本機有 merge commit（多 agent 合併）時會把 merge 拆成直線、卡衝突、分支 SHA 全變"
     "（Stock-web 2026-11-08）→ 改成「本機有 merge commit 用 `git pull --no-rebase`（或 `--rebase=merges`），沒有才 `--rebase`」（全域 workflow.md〈推送前同步〉）"),
]
STALE_RULE_FILES = ("CLAUDE.md", "AGENTS.md", os.path.join(".claude", "skills", "*", "SKILL.md"), os.path.join("docs", "claude-rules", "*.md"))


def stale_rule_hits(cwd, limit=8):
    """專案規則檔裡命中 STALE_RULES 的 (相對路徑:行號, 說明)；最多 limit 筆、每檔 1 MB 以內。"""
    import glob
    out = []
    for pat in STALE_RULE_FILES:
        for fp in sorted(glob.glob(os.path.join(cwd, pat)))[:60]:
            try:
                if os.path.getsize(fp) > 1_000_000:
                    continue
                with open(fp, encoding="utf-8", errors="replace") as f:
                    lines = f.read().splitlines()
            except OSError:
                continue
            for i, ln in enumerate(lines, 1):
                for rx, why in STALE_RULES:
                    if rx.search(ln):
                        out.append((os.path.relpath(fp, cwd).replace(os.sep, "/") + f":{i}", why))
                        if len(out) >= limit:
                            return out
    return out


def align_msg(cwd, session_id=None, mark_only=False, today=None):
    """回要注入的字串或 None。條件：算專案、有 CLAUDE.md、alignOnUpdate、已安裝版本的主.次版號 ≠ 這個資料夾上次記錄的。
    mark_only=True：只記錄版本不注入（同一則已經在跑 init／audit，那兩個本來就照最新規則做）。
    0.25.0：同一個專案一天最多對照一次——2026-11-11 這個 repo 一天升了 5 個次版號，Stock-web 當天被要求對照 4 次以上。
    當天已對照過又升版：不注入、也不更新記錄的版本，隔天第一則提示再一次對照「上次對照的版本之後的各版」。"""
    try:
        c = _pa_skip(cwd)
        if not c or not os.path.exists(os.path.join(c, "CLAUDE.md")):
            return None
        cfg = _pa_config(c)
        if not cfg["alignOnUpdate"]:
            return None
        try:
            with open(SYS_VERSION, encoding="utf-8") as f:
                ver = f.read().strip()
        except Exception:
            return None
        if _minor(ver) is None:
            return None
        st = _pa_load()
        key = "align|" + c.lower()
        old = st.get(key)
        if _minor(old) == _minor(ver):
            return None
        day = today or time.strftime("%Y-%m-%d")
        if old and not mark_only and st.get("alignday|" + c.lower()) == day:
            return None
        if not mark_only:
            is_git = os.path.exists(os.path.join(c, ".git"))
            if not is_git and _pa_count_sources(c)[0] < cfg["minSourceFiles"]:
                return None
        st[key] = ver
        if not mark_only:
            st["alignday|" + c.lower()] = day
        _pa_save(st)
        if mark_only:
            return None
        since = f"{old} 之後的各版" if old else "最近 3 個次版號"
        head = f"全域優化系統從 {old} 更新到 {ver}" if old else f"這個專案還沒對照過全域優化系統 {ver}"
        return ("【全域系統對照（hook）】" + head + "。先回答使用者這則，回答末尾主動附一段「全域規則對照」（使用者不必再問）："
                f"讀 `~/.claude/claude-dev-system/CHANGELOG.md` {since}與 `rules/core.md`，逐條對這個專案的 CLAUDE.md、`.claude/skills/`、"
                "交接紀錄、專案 hook／開工腳本，找出 ①專案規則和全域規則矛盾或已過時的條文（例如已停用功能還在叫你做）；"
                "②全域門檻本專案超標（CLAUDE.md、交接紀錄大小、盤點過期）；③全域新能力本專案還沒接上（verify skill、閘門、排程）。"
                "每項寫根據哪條規則、證據、要改的檔與預估成本。只改文件／設定且可逆的，答完原問題後直接做完再交代；"
                "動到程式行為或系統排程的，先上網查證最佳做法後直接做並附來源；只有不可逆、碰帳號或付款的先問一次。都不用改就一句話「已對照 " + ver + "，無須調整」。"
                "要改全域系統本身時改 claude-dev-system repo 再 update，不要直接改 `~/.claude/claude-dev-system/` 底下的安裝副本"
                "（改過的檔 update 會保留不覆蓋，之後新版都裝不上）。" + _stale_rules_text(c))
    except Exception:
        return None


def _stale_rules_text(c):
    hits = stale_rule_hits(c)
    if not hits:
        return ""
    whys = {}
    for loc, why in hits:
        whys.setdefault(why, []).append(loc)
    return "已偵測到要改的過時條文：" + "；".join(f"{'、'.join(locs)}：{why}" for why, locs in whys.items()) + "。"


# ---------- 工具後提醒（0.14.0，PostToolUse）----------
# 使用者 2026-11-04「這五項都做」：全域規則裡只靠 Claude 記得、實際漏過的四條，改成工具執行後由 hook 判定提醒。
# 同一場對話同一件事只提醒一次（狀態存 project-auto.json 的 remind，只留最近 30 場對話）。
REMIND_GIT = re.compile(r"\bgit\s+(?:add\s+(?:-A\b|--all\b|\.(?=\s|$|[;&|)]))|stash(?!\s+(?:list|show)\b)|reset\s+--hard\b"
                        r"|clean\s+-[a-zA-Z]*f|checkout\s+--\s+\.(?=\s|$|[;&|)]))")
REMIND_KEEP_SESSIONS = 30
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][\w-]*)\1")


def _command_segments(cmd):
    """把 shell 指令切成「真的會被執行的子指令」：引號內的 ; & | 不切，heredoc 內文整段丟掉，換行與 ; & | ( ) 為分隔。
    純字元掃描，不呼叫外部程式。"""
    segs, cur, tags = [], [], []
    i, n, q = 0, len(cmd), ""
    while i < n:
        c = cmd[i]
        if q:
            cur.append(c)
            if c == "\\" and q == '"' and i + 1 < n:
                cur.append(cmd[i + 1])
                i += 1
            elif c == q:
                q = ""
        elif c in "'\"":
            q = c
            cur.append(c)
        elif c == "\\" and i + 1 < n:
            cur.append(c + cmd[i + 1])
            i += 1
        elif c == "<" and cmd.startswith("<<", i) and not cmd.startswith("<<<", i) and _HEREDOC.match(cmd, i):
            hm = _HEREDOC.match(cmd, i)
            tags.append(hm.group(2))
            cur.append(hm.group(0))
            i = hm.end() - 1
        elif c in ";&|()\n":
            segs.append("".join(cur))
            cur = []
            if c == "\n" and tags:  # heredoc 內文：略過到結尾標記那一行
                i += 1
                while i < n and tags:
                    j = cmd.find("\n", i)
                    line = cmd[i:n if j < 0 else j]
                    if line.strip() == tags[0]:
                        tags.pop(0)
                    i = n if j < 0 else j + 1
                continue
        else:
            cur.append(c)
        i += 1
    segs.append("".join(cur))
    return [s.strip() for s in segs if s.strip()]


def _shared_dir_git_match(cmd):
    """REMIND_GIT 只認「在指令位置」的 git（子指令開頭），grep／echo／commit 訊息／heredoc 內文／-c 字串裡的字樣不算。"""
    for seg in _command_segments(cmd):
        m = REMIND_GIT.match(seg)
        if m:
            return m
    return None


def _task_check(cwd):
    """taskCheck（全域，專案優先）→ (enabled, minutes)。"""
    en, mins = True, 15
    for path in (CONFIG, find_project_config(cwd)):
        if not path:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                t = (json.load(f) or {}).get("taskCheck") or {}
        except Exception:
            continue
        if isinstance(t.get("enabled"), bool):
            en = t["enabled"]
        if isinstance(t.get("minutes"), (int, float)) and not isinstance(t.get("minutes"), bool) and t["minutes"] > 0:
            mins = int(t["minutes"])
    return en, mins


def _installed_copy(fp):
    """fp 是 claude-dev-system 的安裝副本（rules／tools／hooks／CHANGELOG、本工具裝的 skills）→ 回顯示用相對路徑，否則 None。
    config/ 不算：dispatch-config.json 本來就給使用者改，local.json 是金鑰。"""
    ap = os.path.normcase(os.path.abspath(fp))
    base = os.path.normcase(os.path.join(HOME, "claude-dev-system"))
    sk = os.path.normcase(os.path.join(HOME, "skills"))
    if ap.startswith(base + os.sep):
        r = os.path.relpath(ap, base).replace(os.sep, "/")
        if r.split("/")[0] in ("rules", "tools", "hooks") or r == "changelog.md":
            return "claude-dev-system/" + r
    elif ap.startswith(sk + os.sep):
        parts = os.path.relpath(ap, sk).split(os.sep)
        if len(parts) > 1 and os.path.exists(os.path.join(sk, parts[0], ".claude-dev-system")):
            return "skills/" + "/".join(parts)
    return None


def _hot_modules(cwd, st):
    """盤點索引的「被引用最多」{相對路徑: 引用數}；依索引修改時間快取在狀態檔，不每次解析大索引。"""
    idx = os.path.join(cwd, ".claude", "project-scan.json")
    try:
        mt = os.path.getmtime(idx)
    except OSError:
        return {}
    key = "hot|" + cwd.lower()
    c = st.get(key)
    if isinstance(c, dict) and c.get("mtime") == mt:
        return c.get("hot") or {}
    try:
        with open(idx, encoding="utf-8") as f:
            hot = {str(r): int(n) for r, n in (json.load(f) or {}).get("mostDepended") or []}
    except Exception:
        hot = {}
    st[key] = {"mtime": mt, "hot": hot}
    return hot


def _background_task_id(payload):
    """工具結果裡的背景任務 ID（0.14.1）：Bash／PowerShell 明確派的、或逾時被自動移到背景的（tool_input 沒有 run_in_background，只有結果看得出來）。沒有回空字串。"""
    r = payload.get("tool_response")
    if isinstance(r, dict):
        for k in ("backgroundTaskId", "agentId", "task_id"):
            if r.get(k):
                return str(r[k])
        r = r.get("stdout") or ""
    m = re.search(r"moved to the background \(ID: ([\w-]+)\)", r) if isinstance(r, str) else None
    return m.group(1) if m else ""


PATROL_MARK = "巡檢"  # core.md 固定的巡檢排程 prompt 以這兩個字開頭


def patrol_sync(payload):
    """Stop：用官方欄位 session_crons 對一次「這場對話現在有沒有巡檢排程」（最準；排程過期、被刪、對話壓縮後都會被校正）。"""
    try:
        crons = payload.get("session_crons")
        sid = str(payload.get("session_id") or "")
        if not isinstance(crons, list) or not sid:
            return
        ids = [str((c or {}).get("id") or "?") for c in crons if PATROL_MARK in str((c or {}).get("prompt") or "")[:40]]
        st = _pa_load()
        rem = st.get("remind") if isinstance(st.get("remind"), dict) else {}
        sess = rem.get(sid) if isinstance(rem.get(sid), dict) else {}
        if sess.get("patrol", []) != ids:
            sess["patrol"] = ids
            rem[sid] = sess
            st["remind"] = rem
            _pa_save(st)
    except Exception:
        pass


def tool_reminders(payload):
    """回要注入的提醒清單。四項：改安裝副本、派背景任務沒建巡檢、改被大量引用的模組、多人共用目錄的危險 git 指令。"""
    try:
        name = payload.get("tool_name") or ""
        ti = payload.get("tool_input") or {}
        if not isinstance(ti, dict):
            return []
        sid = str(payload.get("session_id") or "-")
        cwd = payload.get("cwd")
        st = _pa_load()
        rem = st.get("remind") if isinstance(st.get("remind"), dict) else {}
        sess = rem.pop(sid, {})  # pop 再放回＝移到最後，修剪時留最近的對話
        rem[sid] = sess
        out = []
        # 0.25.0：記住這場對話的巡檢排程。原本每派一個背景任務就提醒一次（0.14.1 為了「排程刪掉後再派要重建」），
        # 排程明明還在也照跳——2026-11-11 這個 repo 的對話十幾次、Stock-web 8 次。現在排程在就不提醒，刪掉後再派才提醒。
        if name == "CronCreate" and PATROL_MARK in str(ti.get("prompt") or "")[:40]:
            r = payload.get("tool_response")
            m = re.search(r"\b([0-9a-f]{6,12})\b", json.dumps(r, ensure_ascii=False) if not isinstance(r, str) else r)
            sess["patrol"] = list(sess.get("patrol") or []) + [m.group(1) if m else "?"]
        elif name == "CronDelete":
            left = [x for x in sess.get("patrol") or [] if x != str(ti.get("id") or "")]
            if left == sess.get("patrol") and "?" in left:
                left.remove("?")  # 建立時沒抓到編號的那一筆
            sess["patrol"] = left

        def once(k):
            if k in sess:
                return False
            sess[k] = 1
            return True

        fp = ti.get("file_path") or ti.get("notebook_path") or ""
        if name in ("Edit", "Write", "NotebookEdit") and fp:
            inst = _installed_copy(fp)
            if inst and once("inst|" + inst):
                out.append(f"【改到安裝副本（hook）】剛改的 `{fp}` 是 claude-dev-system 的安裝副本：update 會把改過的檔當使用者改動保留、新版只存 .new，"
                           "之後這個檔的更新全部裝不上（Stock-web 2026-11-03 就這樣卡住 usage_guard.py 與 doc-governance.md）。"
                           "→ 把同樣的改動做在 claude-dev-system repo（常見 ~/Documents/Claude/claude-dev-system，或 `~/.claude/claude-dev-system/app/`），"
                           "跑測試、`install.py update`、`verify`；安裝副本改回 repo 版。沒有 repo 可改就告訴使用者，不要只改副本。")
            c = _pa_skip(cwd)
            if c and not inst:
                try:
                    rel = os.path.relpath(os.path.abspath(fp), c).replace(os.sep, "/")
                except ValueError:
                    rel = ""
                n = _hot_modules(c, st).get(rel, 0) if rel and not rel.startswith("..") else 0
                if n >= 3 and once("blast|" + rel):
                    out.append(f"【波及範圍（hook）】剛改的 `{rel}` 被 {n} 個檔引用（盤點索引）→ 收尾前用 skill `cds-blast-radius` 列出 diff 之外會受影響的呼叫端，"
                               "逐條判定並實跑最關鍵的一條證明安全；這場對話已對它做過就忽略。")
        # 0.14.1：逾時被自動移到背景的也算；有任務 ID 就每個任務各提醒一次（巡檢排程全部結束會刪，之後再派要重建；Stock-web 2026-11-04 只提醒一次，
        # 排程刪掉後再派的任務沒有巡檢，指令卡 34 分鐘要使用者問才發現）。提醒句本來就是「先 CronList，沒有才建」，重複提醒不會重複建。
        tid = _background_task_id(payload)
        bg = name in ("Agent", "Task", "Workflow") or (name in ("Bash", "PowerShell") and (ti.get("run_in_background") is True or bool(tid)))
        if bg:
            en, mins = _task_check(cwd)
            if en and not sess.get("patrol") and once("taskcheck|" + tid if tid else "taskcheck"):
                out.append(f"【背景任務巡檢（hook）】剛派出背景任務，taskCheck.enabled=true → 先 `CronList`，這場對話還沒有巡檢排程就用 `CronCreate` 建每 {mins} 分鐘一次，"
                           "prompt 用 core.md「背景任務巡檢」那句固定文字；全部結束就 `CronDelete`。子 agent 忽略此則。" + _deferred_hint(cwd))
        if name in ("Bash", "PowerShell"):
            m = _shared_dir_git_match(str(ti.get("command") or ""))
            if m and once("git|" + m.group(0)):
                out.append(f"【共用工作目錄（hook）】剛執行 `{m.group(0)}`：多個 agent／對話共用這個工作目錄時不可用（會一起加入、藏起或丟掉別人的未提交變更）"
                           "→ 用 `git status` 確認沒動到別人的檔，之後改用 `git add <自己改的檔>`、`git commit -- <路徑>`。確定只有你在這個目錄工作就忽略。")
        while len(rem) > REMIND_KEEP_SESSIONS:
            rem.pop(next(iter(rem)))
        st["remind"] = rem
        _pa_save(st)
        return out
    except Exception:
        return []


# ---------- 0.16.0：殘留程序、延後工作、對話暫存（UserPromptSubmit／PostToolUse，全部節流）----------
_TOOL_CACHE = {}


def _tool_mod(name):
    """載入同一份安裝裡的 tools/<name>.py（唯一來源，不在 hook 複製一份）；只在真的要用時才載入。"""
    m = _TOOL_CACHE.get(name)
    if m is None:
        import importlib.util
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", name + ".py")
        spec = importlib.util.spec_from_file_location("cds_tool_" + name.replace("-", "_"), p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _TOOL_CACHE[name] = m
    return m


def _section(cwd, name, defaults):
    """dispatch-config.json 的某一段：全域，再專案（cwd 往上找）覆蓋；只收與預設同型別的值。"""
    out = dict(defaults)
    for path in (CONFIG, find_project_config(cwd)):
        if not path:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                t = (json.load(f) or {}).get(name) or {}
        except Exception:
            continue
        for k, v in defaults.items():
            x = t.get(k)
            if isinstance(v, bool):
                if isinstance(x, bool):
                    out[k] = x
            elif isinstance(x, (int, float)) and not isinstance(x, bool) and x >= 0:
                out[k] = x
    return out


DEFERRED = os.path.join(STATE_DIR, "deferred-jobs.json")


def _deferred_items():
    """延後清單（tools/resgate.py 寫的唯一一份）；讀不到回 []。"""
    try:
        with open(DEFERRED, encoding="utf-8") as f:
            items = (json.load(f) or {}).get("items") or []
        return [x for x in items if isinstance(x, dict)]
    except Exception:
        return []


def _deferred_mine(cwd):
    """(這個專案的延後工作, 其他專案的筆數)。清單是所有專案共用一份；同專案判定用 tools/resgate.py 的 same_project（唯一來源）。
    cwd 給 None、或載不到判定函式時不分專案（全部算這個專案的）。"""
    items = _deferred_items()
    if not items or not cwd:
        return items, 0
    try:
        sp = getattr(_tool_mod("resgate"), "same_project", None)
    except Exception:
        sp = None
    if not sp:
        return items, 0
    mine = [x for x in items if sp(x.get("project"), cwd)]
    return mine, len(items) - len(mine)


def _deferred_hint(cwd=None):
    items, _others = _deferred_mine(cwd)
    if not items:
        return ""
    first = items[0]
    return (f"另外延後清單有 {len(items)} 項「記憶體不足、沒有執行」的工作（最早：#{first.get('id')} {first.get('desc', '')}）"
            "：巡檢與每次有 agent／背景任務完成時先跑 `py -3 ~/.claude/claude-dev-system/tools/resgate.py next`，記憶體夠就依登記順序開跑，跑一個再查一次。")


def deferred_msg(cwd, session_id, st, now=None, every=600):
    """UserPromptSubmit（含 agent 完成通知那一輪）：延後清單有項目、而且現在記憶體夠 → 提醒依登記順序開跑。同一場對話最多每 10 分鐘一次。"""
    try:
        items, others = _deferred_mine(cwd)  # 0.26.1：只提這個專案登記的；別的專案的由那邊的對話處理
        if not items:
            return None
        now = now or time.time()
        key = "deferred|" + str(session_id or "-")
        if now - float(st.get(key, 0)) < every:
            return None
        rg = _tool_mod("resgate")
        ok, free, need = rg.enough(rg.load_cfg(cwd))
        if not ok:
            return None
        st[key] = now
        x = items[0]
        return (f"【延後工作（hook）】延後清單有 {len(items)} 項之前「記憶體不足、沒有執行」的工作，現在可用記憶體 "
                f"{'量不到' if free is None else f'{free:.1f} GB'} ≥ {need:g} GB → 依登記順序開跑第一項 #{x.get('id')}"
                f"（{x.get('project', '')}：{x.get('desc', '')}；重跑：{x.get('rerun') or '見原派工'}）：重派或 SendMessage 喚回原 agent，"
                f"開跑後 `resgate.py done {x.get('id')}`，跑一個再查一次記憶體。"
                + (f"（清單另有 {others} 項屬於其他專案，不用處理。）" if others else "") + "子 agent 忽略此則。")
    except Exception:
        return None


PROC_DEFAULTS = {"enabled": True, "minMinutes": 60, "everyMinutes": 10}


def proc_msg(cwd, session_id, st, now=None):
    """這場對話的工具指令開出、跑超過 minMinutes 分鐘的程序（Stock-web 2026-11-08 until／tail 迴圈空轉到隔天）。
    每場對話每 everyMinutes 分鐘最多查一次（查一次約 10～30 ms）；同一個 PID 只提醒一次；只提醒，不結束程序。"""
    try:
        cfg = _section(cwd, "procCheck", PROC_DEFAULTS)
        if not cfg["enabled"]:
            return None
        now = now or time.time()
        key = "procs|" + str(session_id or "-")
        rec = st.get(key) if isinstance(st.get(key), dict) else {}
        if now - float(rec.get("at", 0)) < float(cfg["everyMinutes"]) * 60:
            return None
        pr = _tool_mod("procs")
        groups = pr.session_leftovers(float(cfg["minMinutes"]), cwd)
        seen = set(rec.get("seen") or [])
        new = [g for g in groups if g["pid"] not in seen]
        st[key] = {"at": now, "seen": sorted(seen | {g["pid"] for g in groups})[-200:]}
        if not new:
            return None
        return (f"【殘留程序（hook）】這場對話的工具指令開出、已跑超過 {cfg['minMinutes']:g} 分鐘的程序：{pr.fmt(new)}。"
                "對照仍在跑的背景任務與 agent：屬於已結束的 agent、已交報告的任務（例如 until／while 等待迴圈、tail、沒人用的伺服器）就是殘留 → "
                "告訴使用者 PID 與命令、請使用者決定要不要結束（同意後只依 PID 結束），不要自動結束、不可整批結束 node／bash；仍在用的就忽略。"
                "子 agent：是你自己開的就在交報告前結束。")
    except Exception:
        return None


TEMP_DEFAULTS = {"claudeTempWarnGB": 2, "remindDays": 7}


def _dir_size_until(root, limit_bytes, budget=0.5):
    """不跟隨連結地加總大小；超過 limit 或時間用完就停。回 (位元組, 是否算完)。"""
    total, stack, t0 = 0, [root], time.time()
    is_link = None
    try:
        is_link = _tool_mod("project-scan").is_link_dir
    except Exception:
        is_link = lambda p: os.path.islink(p) or bool(getattr(os.path, "isjunction", lambda _p: False)(p))  # noqa: E731
    while stack:
        if time.time() - t0 > budget:
            return total, False
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if e.is_symlink() or is_link(e.path):
                        continue
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                    else:
                        total += e.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
                if total >= limit_bytes:
                    return total, True
    return total, True


def temp_msg(cwd, st, now=None, root=None):
    """Claude 對話暫存（<TEMP>/claude）超過 claudeTempWarnGB → 每 remindDays 天最多提醒一次可跑 cleanup.py；只提醒不刪。
    每天最多量一次（0.5 秒內），Stock-web 2026-11-08 累積到 3.8 GB。"""
    try:
        import tempfile
        cfg = _section(cwd, "cleanup", TEMP_DEFAULTS)
        if not cfg["claudeTempWarnGB"]:
            return None
        now = now or time.time()
        rec = st.get("tempwarn") if isinstance(st.get("tempwarn"), dict) else {}
        if now - float(rec.get("warnedAt", 0)) < float(cfg["remindDays"]) * 86400 or now - float(rec.get("checkedAt", 0)) < 86400:
            return None
        root = root or os.path.join(tempfile.gettempdir(), "claude")
        rec["checkedAt"] = now
        st["tempwarn"] = rec
        if not os.path.isdir(root):
            return None
        lim = float(cfg["claudeTempWarnGB"]) * 1024 ** 3
        size, _done = _dir_size_until(root, lim)
        if size < lim:
            return None
        rec["warnedAt"] = now
        return (f"【磁碟清理（hook）】Claude 對話暫存 `{root}` 已超過 {cfg['claudeTempWarnGB']:g} GB → 回答末尾用一句話告訴使用者可跑 "
                "`py -3 ~/.claude/claude-dev-system/tools/cleanup.py --only temp`（先列清單與可省空間；目前對話與 24 小時內動過的不刪，確認後加 --apply）。"
                f"只提醒，不要自己刪；{cfg['remindDays']:g} 天內不再提醒。")
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
# 0.16.0：數字來自本機資料（回測報告、快取、腳本輸出）也算有來源——Stock-web 11/8～11/9 回覆數字全來自本機回測報告，被退回 3 次要求附網址。
# 判定：回覆裡有本機路徑（docs/…、.cache/…、scripts/…、data/…、reports/…，或任何 xxx.md／.json／.csv／.log 檔名）或標「本站資料／本機報告」。
SG_LOCAL_MARK = ("本站資料", "本機報告", "本機資料", "本地資料", "本站回測")
SG_LOCAL_PATH = re.compile(r"(?<![\w/.:-])(?:\.?/)?(?:docs|\.cache|scripts|data|reports?|results?|out|logs?)[/\\][\w\-./\\]+"
                           r"|[\w\-./\\]*[\w\-]\.(?:md|json|jsonl|csv|tsv|log|txt|ipynb)\b")
# 0.16.2：工作文件與設定檔幾乎每次回覆都會提到，不能當數字的出處（只提「已更新 PROGRESS.md」就放行憑印象的數字＝漏洞）。
SG_LOCAL_GENERIC = {"claude.md", "agents.md", "progress.md", "progress-archive.md", "handoff.md", "todo.md", "readme.md",
                    "changelog.md", "skill.md", "memory.md", "package.json", "package-lock.json", "tsconfig.json",
                    "jsconfig.json", "settings.json", "settings.local.json", "dispatch-config.json", "local.json",
                    "project-scan.json", ".claude.json"}


def sg_local_source(answer):
    """回覆裡有沒有可當數字出處的本機資料路徑（排除工作文件與設定檔）。"""
    for m in SG_LOCAL_PATH.finditer(answer):
        name = re.split(r"[/\\]", m.group(0).rstrip("./\\"))[-1].lower()
        if name and name not in SG_LOCAL_GENERIC:
            return True
    return False


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


# 0.19.0：建議守門與跳過條件收緊（Stock-web 2026-11-10 使用者：「你要照著規則與長期記憶來辦事阿，不然那些規則是說假的是不是」——
# 同一天 main 列 6 種「沒測過的方法」全憑印象、沒標已查證／未查證；又在含研究結論的回覆末尾加「不含待查證事實」跳過守門）。
# ①回覆提出建議／方案（不論問句與否）卻沒有逐項標「已查證／未查證」→ 退回一次（core.md「先找現成做法」：每項建議標明已查證或未查證）。
# ②「〔不含待查證事實〕」只給純概念或自己算的數字用；回覆有年份、或引用研究／論文／報告結論時不算數，照樣要「來源」段。
# 0.24.0：「會誤建議你開新對話」「hook 會建議開新對話」「不建議改」這類敘述／否定句不是在提建議（2026-11-11 main 的收尾回覆被退回一次）。
# 前面緊接「誤、不、會、曾、已、才、沒、未、被、的」的「建議X」不算；真的在提建議的「我會建議」另外列。
SG_RECO = re.compile(r"我的建議|我建議|我會建議|(?<![誤不會曾已才沒未被的])建議(?:你|改|採|用|做|先|把)|(?<![誤不會曾已才沒未被的])建議方向"
                     r"|(?:方案|選項)\s*[1-9一二三四五]|要照這個做嗎|下一輪(?:就|改|只)")
SG_RECO_MARK = ("已查證", "未查證")
SG_SKIP_MARK = "不含待查證事實"
SG_CLAIM = re.compile(r"研究|論文|期刊|學者|文獻|報告指出|統計顯示|證實|實證")


def sg_reco_judge(answer):
    """提出建議卻沒標查證狀態：回原因字串；否則 None。"""
    if not answer or len(answer) < SG_MIN_ANSWER or "```" in answer:
        return None
    if SG_RECO.search(answer) and not any(m in answer for m in SG_RECO_MARK):
        return "提出了建議／方案"
    return None


def sg_judge(prompt, answer):
    """要不要退回。回 None（放行）或原因字串。"""
    if not prompt or not answer or len(answer) < SG_MIN_ANSWER:
        return None
    if "```" in answer:  # 程式工作：回覆裡的數字多半是行數、測試數，不是事實宣稱
        return None
    if not any(q in prompt for q in SG_QUESTION):
        return None
    has_source = any(m in answer for m in SG_SOURCE if m != "不含待查證事實")
    if has_source:
        return None
    if SG_SKIP_MARK in answer and not SG_YEAR.search(answer) and not SG_CLAIM.search(answer):
        return None
    if any(m in answer for m in SG_LOCAL_MARK) or sg_local_source(answer):
        return None
    years = SG_YEAR.findall(answer)
    nums = SG_NUM.findall(answer)
    if not years and not nums:
        return None
    return f"含 {len(years)} 個年份、{len(nums)} 個帶單位數字"


# 0.23.0：這一輪不一定是使用者打字觸發的——agent 交回的報告、背景任務完成通知、排程（CronCreate）都會以「使用者訊息」的形式進來。
# 2026-11-11 09:32 main 在等 3 個 agent 時回一句進度就被退回，紀錄裡的「問」是 agent 的報告（裡面剛好有問號）。
# 做法照官方 Stop 輸入欄位：background_tasks「let hooks distinguish "session is done" from "session is paused waiting for
# background work to wake it back up"」（code.claude.com/docs/en/hooks〈Stop input〉）。
SG_AUTO_MARK = ("Another Claude session sent a message", "<task-notification>", "[SYSTEM NOTIFICATION - NOT USER INPUT]",
                "<agent-message ", "Stop hook feedback:")
SG_WAIT_TYPES = {"subagent", "workflow", "teammate", "cloud session"}  # shell／monitor 可能是常駐的伺服器或監看，不算「還在等結果」


def sg_is_auto(prompt, crons=None):
    """這則「使用者訊息」是不是系統／agent／排程送進來的（不是使用者打的字）。"""
    if not prompt:
        return False
    head = prompt.lstrip()[:400]
    if any(m in head for m in SG_AUTO_MARK):
        return True
    for c in crons or []:
        cp = str((c or {}).get("prompt") or "").strip()
        if len(cp) >= 12 and head.startswith(cp[:200].rstrip(" …")[:60]):
            return True
    return False


def sg_last_human(transcript_path, crons=None):
    """最後一則真的由使用者打的提示（跳過 agent 訊息、完成通知、排程）。讀不到回 None。"""
    last = None
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"type":"user"' not in line and '"type": "user"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("type") != "user" or d.get("isSidechain"):
                    continue
                t = _sg_text((d.get("message") or {}).get("content"))
                if t is not None and t.strip() and not sg_is_auto(t, crons):
                    last = t
    except Exception:
        return None
    return last


def source_guard(payload):
    if payload.get("stop_hook_active") or not sg_enabled():
        return None
    prompt, answer = sg_last_turn(payload.get("transcript_path") or "")
    crons = payload.get("session_crons") if isinstance(payload.get("session_crons"), list) else []
    if sg_is_auto(prompt, crons):
        waiting = [t for t in payload.get("background_tasks") or [] if isinstance(t, dict) and t.get("type") in SG_WAIT_TYPES]
        if waiting:
            return None  # 還有 agent／workflow 在跑：這則是中途進度，不是答案
        prompt = sg_last_human(payload.get("transcript_path") or "", crons)  # 背景工作都結束了：這則就是答案，問題是使用者最後打的那句
    reco = sg_reco_judge(answer)
    if reco:
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            with open(os.path.join(STATE_DIR, "source-guard.log"), "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} block-reco｜問：{(prompt or '')[:60]!r}" + chr(10))
        except Exception:
            pass
        return {"decision": "block",
                "reason": "【建議守門（hook）】這則回覆" + reco + "，但沒有逐項標明「已查證（附來源）／未查證」（core.md「先找現成做法」）。"
                          "請把每一項建議、方法、方向標上：已查證＝附網址與原句短引；未查證＝標「未查證」並先上網補查，查不到就刪掉或明說查不到。"
                          "不可把憑印象的做法當成已確認。只補這一次，之後不會再退回。"}
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


# 0.21.0 派工補充（SubagentStart）。使用者 2026-11-11：「它派出去的agent常常都不會遵守該專案裡的規則與長期記憶等等，還有連全域優化系統的規則
# 它也不不遵守，不知道是不遵守還是不會看」。查 Stock-web 81 份 agent 對話紀錄＋官方文件（code.claude.com/docs/en/sub-agents、hooks）：
# agent 有載入 CLAUDE.md 與 MEMORY.md 索引，但①回覆語言設定不傳 ②記憶內文不載入（81 個裡只有 1 個用指令讀過一條）③UserPromptSubmit／Stop 的守門
# 不對 agent 觸發 ④工作目錄繼承主對話當下位置（11/10 有 agent 因此 commit 到部署分支）。官方做法：SubagentStart 的 additionalContext。
SUB_LIGHT_TYPES = {"Explore", "Plan", "claude-code-guide", "statusline-setup", "web-fetch"}  # 唯讀／單一用途，只補語言


def _settings_language():
    try:
        with open(os.path.join(HOME, "settings.json"), encoding="utf-8") as f:
            v = (json.load(f) or {}).get("language")
        return v.strip() if isinstance(v, str) and v.strip() else None
    except Exception:
        return None


def _git_branch(cwd):
    try:
        import subprocess
        r = subprocess.run(["git", "-C", cwd, "branch", "--show-current"], capture_output=True, text=True, timeout=1.5,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.stdout.strip() or None
    except Exception:
        return None


def _sub_cfg(cwd):
    """subagentBrief 設定：enabled＝開工補充、guard＝交報告守門。全域設定檔，再專案設定檔（優先），都沒有就預設開。"""
    cfg = {"enabled": True, "guard": True}
    for path in (CONFIG, os.path.join(cwd or os.getcwd(), PROJECT_CONFIG_REL)):
        try:
            with open(path, encoding="utf-8") as f:
                t = (json.load(f) or {}).get("subagentBrief") or {}
        except Exception:
            continue
        for k in cfg:
            if isinstance(t.get(k), bool):
                cfg[k] = t[k]
    return cfg


def subagent_brief(payload):
    """回要注入給剛派出的 agent 的字串或 None。設定：dispatch-config.json 的 subagentBrief.enabled（預設 true，專案優先）。"""
    cwd = payload.get("cwd") or os.getcwd()
    cfg = _sub_cfg(cwd)
    if not cfg["enabled"]:
        return None
    out = ["【派工補充（hook）】你是被派出的 agent。下面幾件事主對話有、但不會自動傳給你："]
    lang = _settings_language()
    if lang:
        out.append(f"- 語言：使用者的回覆語言設定是「{lang}」。中途文字與最終報告都用這個語言，寫法與全域 CLAUDE.md 相同（它是繁體中文就用繁體中文）。")
    if payload.get("agent_type") in SUB_LIGHT_TYPES:
        return chr(10).join(out) if len(out) > 1 else None
    br = _git_branch(cwd)
    out.append(f"- 工作目錄：開工時是 `{cwd}`" + (f"（git 分支 `{br}`）" if br else "") + "，這是繼承主對話當下的位置，不一定是這份工作該在的地方。"
               "派工單指定了目錄或分支就照派工單，commit 前先 `git branch --show-current`，不是指定的分支就不 commit、改存 patch 並在報告寫路徑；"
               "派工單叫你 commit 卻沒寫分支：照做，但報告開頭寫明 commit hash、所在分支與工作目錄，由 main 核對；派工單沒叫你 commit 就不 commit。")
    mem = os.path.normpath(os.path.join(os.path.dirname(payload.get("transcript_path") or ""), "memory"))
    if os.path.isfile(os.path.join(mem, "MEMORY.md")):
        out.append(f"- 長期記憶：你的 context 只有 MEMORY.md 索引（每行一條使用者給過的指示），內文沒有載入。開工前把索引裡與這份工作有關的每一條用 Read 讀內文"
                   f"（`{mem}` 底下同名檔），照內文做；一條都無關就在報告寫「記憶索引已看，無相關」。")
    out.append("- 規則：全域與專案 CLAUDE.md 對你同樣適用，派工單沒重寫不代表免除；兩者衝突時照派工單。主對話有 hook 會退回不合規的回覆，你沒有，交報告前自己逐項核對："
               "①上網查資料前先 Read `~/.claude/claude-dev-system/rules/web-quick.md` ②報告裡每個關鍵數字附出處（檔案路徑＋行或網址），推論另外標明 "
               "③回測、全套測試、build 用 `py -3 ~/.claude/claude-dev-system/tools/resgate.py run --desc \"<工作>\" -- <指令>` 開跑（記憶體不足它不會執行；不可在後面接管線） ④只 `git add <自己改的檔>`，不 `add -A`、不 stash／reset 別人的變更 "
               "⑤自己開的背景程序全部結束（依 PID 或埠號）。做不到的項目寫進報告，不可略過不提。"
               + ("交報告（SubagentHandback）時 hook 會核對語言、①、②、記憶與 commit 分支，不合格退回一次。" if cfg["guard"] else ""))
    return chr(10).join(out)


# 0.22.0 交報告守門（PreToolUse：SubagentHandback）。使用者 2026-11-11：「還沒解決的繼續全都做完。」
# 攔截點照官方文件與 issue：v2.1.271 起報告經 SubagentHandback 交出，SubagentStop 時報告已送達（code.claude.com/docs/en/hooks〈SubagentStop input〉）；
# SubagentStop 還會被內部分支（agent_type 空字串）觸發（anthropics/claude-code#87065、#91910），所以不用它。
SUB_WEB_TOOL = re.compile(r"^(?:WebSearch|WebFetch)$|^mcp__(?:exa|tavily|firecrawl|parallel|context7|deepwiki|mslearn)", re.I)
SUB_COMMIT = re.compile(r"\bgit\b[^\n|;&]*\bcommit\b")
SUB_CODE_PATH = re.compile(r"[\w\-./\\]*[\w\-]\.(?:py|ts|tsx|js|jsx|mjs|cjs|sql|sh|ps1|yml|yaml|toml|html|css)\b")
SUB_CJK_LANG = ("chinese", "中文", "繁體", "zh")
SUB_GUARD_STATE = os.path.join(STATE_DIR, "subagent-guard.json")
SUB_MEM_NONE = re.compile(r"記憶索引已看[，,、：:\s]*(?:都|全部|皆)?(?:無相關|沒有相關|與這份工作無關|都無關)")
SUB_LANG_MIN_RATIO = 0.3  # 中文字比例低於這個值＝不是中文（自己定的；tools/agent-audit.py 匯入同一個值）
SUB_MIN_NUMS = 3  # 自己定的：少於 3 個帶單位數字的報告不查出處（短回報、進度句）


def _sub_cjk_ratio(text):
    t = re.sub(r"```.*?```|`[^`]*`|https?://\S+|[\W\d_]", "", text or "", flags=re.S)
    return (sum(1 for ch in t if "\u4e00" <= ch <= "\u9fff") / len(t)) if t else 1.0


def _sub_scan(path):
    """讀 agent 自己的對話紀錄：第一則派工說明、用過的工具、Read 過的路徑、Bash 指令。讀不到回 None（不擋）。"""
    try:
        prompt, tools, reads, cmds = None, [], [], []
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                c = (r.get("message") or {}).get("content")
                if r.get("type") == "user" and prompt is None:
                    prompt = c if isinstance(c, str) else " ".join(x.get("text", "") for x in c or [] if isinstance(x, dict))
                if r.get("type") == "assistant" and isinstance(c, list):
                    for x in c:
                        if isinstance(x, dict) and x.get("type") == "tool_use":
                            i = x.get("input") or {}
                            tools.append(x.get("name") or "")
                            if x.get("name") == "Read":
                                reads.append(str(i.get("file_path") or ""))
                            if x.get("name") in ("Bash", "PowerShell"):
                                cmds.append(str(i.get("command") or ""))
        return {"prompt": prompt or "", "tools": tools, "reads": reads, "cmds": cmds}
    except Exception:
        return None


def _sub_transcript(payload):
    aid = str(payload.get("agent_id") or "")
    base = os.path.join(os.path.dirname(payload.get("transcript_path") or ""), str(payload.get("session_id") or ""), "subagents")
    for name in (f"agent-{aid}.jsonl", f"{aid}.jsonl"):
        p = os.path.join(base, name)
        if aid and os.path.isfile(p):
            return p
    return None


def sub_memory_read(blob, mem_dir):
    """blob（Read 過的路徑＋Bash／PowerShell 指令）裡有沒有讀過 mem_dir 底下任何一條記憶的內文（MEMORY.md 索引不算）。
    認「路徑含 <專案>/memory 且出現某個記憶檔名」，所以先 cd 進資料夾再用相對檔名讀也算。守門與 tools/agent-audit.py 共用。"""
    norm = (blob or "").replace(chr(92), "/")
    try:
        names = [n for n in os.listdir(mem_dir) if n.lower().endswith(".md") and n != "MEMORY.md"]
    except OSError:
        return False
    key = os.path.basename(os.path.dirname(mem_dir)) + "/memory"
    return key in norm and any(n in norm for n in names)


def subagent_report_judge(report, scan, lang, mem_dir):
    """回不合格項目清單（字串）。scan 為 None（讀不到紀錄）時只查報告本身。純函式，測試直接呼叫。"""
    bad = []
    if lang and any(k in lang.lower() for k in SUB_CJK_LANG) and len(report) >= 80 and _sub_cjk_ratio(report) < SUB_LANG_MIN_RATIO:
        bad.append(f"報告不是使用者設定的語言（{lang}）→ 整份改用該語言重寫。")
    nums = len(SG_NUM.findall(report)) + len(SG_YEAR.findall(report))
    if nums >= SUB_MIN_NUMS and not ("http://" in report or "https://" in report or "未附來源" in report
                                     or sg_local_source(report) or SUB_CODE_PATH.search(report)):
        bad.append(f"報告有 {nums} 個年份或帶單位數字，但沒有任何出處 → 每個關鍵數字旁寫檔案路徑（含行號）或網址；查不到的標〔未附來源〕。")
    if scan is None:
        return bad
    blob = chr(10).join(scan["reads"] + scan["cmds"])
    if any(SUB_WEB_TOOL.search(t) for t in scan["tools"]) and "web-quick" not in blob and "web-sources" not in blob:
        bad.append("上網查了資料卻沒有先讀 `~/.claude/claude-dev-system/rules/web-quick.md` → 現在 Read 它，照〈回覆格式〉核對報告裡查到的事實（來源網址、日期、原句短引），不足的補查。")
    # 0.23.0（Stock-web 2026-11-11 兩個實例）：①先 cd 到記憶資料夾再用相對檔名讀也算讀過（原本只認完整路徑，誤擋一個讀過 4 條的 agent）
    # ②報告寫「有關的三條沒有衝突」卻沒讀內文不算數——只有明寫「無相關」才可免讀（原本看到「記憶索引」四個字就放行）。
    if mem_dir and os.path.isfile(os.path.join(mem_dir, "MEMORY.md")) and not SUB_MEM_NONE.search(report):
        if not sub_memory_read(blob, mem_dir):
            bad.append(f"沒有讀任何一條長期記憶的內文 → 看 context 裡的 MEMORY.md 索引，與這份工作有關的用 Read 讀內文（`{mem_dir}`）並照做、必要時修正成果；"
                       "真的一條都無關才在報告加一行「記憶索引已看，無相關」（有關卻沒讀內文不算）。")
    if any(SUB_COMMIT.search(c) for c in scan["cmds"]) and not re.search(r"分支|branch", scan["prompt"], re.I) and not re.search(r"分支|branch", report, re.I):
        bad.append("派工說明沒有指定 commit 的分支，你卻 commit 了 → 不要自己 reset；在報告開頭寫明 commit hash、所在分支（`git branch --show-current`）與工作目錄，由 main 決定要不要搬。")
    return bad


SUB_LANG_STATE = os.path.join(STATE_DIR, "subagent-lang.json")
SUB_LANG_TAIL = 60000  # 只讀 agent 對話紀錄最後這麼多位元組
SUB_LANG_MAX = 5  # 自己定的：同一個 agent 最多提醒這麼多次（0.26.0 前只提醒 1 次——Stock-web 2026-11-11 三個 opus agent 收到一次提醒後
#                   只改一句又寫回英文，紀錄是「英、提醒、中、英、英」；探針用的 haiku 一次就改）


def subagent_lang_nudge(payload):
    """PostToolUse 在 agent 裡觸發時：它最近寫的說明文字不是使用者的語言就提醒；每出現一則新的就再提醒，同一則不重複，最多 SUB_LANG_MAX 次。
    2026-11-11 實派 3 個 agent：最終報告都是中文，但工具呼叫之間的說明文字 6 則裡 3 則英文
    （Stock-web 2026-09-14 使用者原話：「這個過程都還是英文，要用繁體中文」）。任何例外都不提醒。"""
    try:
        aid = str(payload.get("agent_id") or "")
        lang = _settings_language()
        if not aid or payload.get("agent_type") in SUB_LIGHT_TYPES or not lang or not any(k in lang.lower() for k in SUB_CJK_LANG):
            return None
        if not _sub_cfg(payload.get("cwd"))["enabled"]:
            return None
        tp = _sub_transcript(payload)
        if not tp:
            return None
        try:
            with open(SUB_LANG_STATE, encoding="utf-8") as f:
                seen = json.load(f) or {}
        except Exception:
            seen = {}
        rec = seen.get(aid)
        rec = rec if isinstance(rec, dict) else ({"n": 1, "last": "", "at": float(rec)} if rec else {"n": 0, "last": "", "at": 0})
        if rec["n"] >= SUB_LANG_MAX:
            return None
        with open(tp, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - SUB_LANG_TAIL))
            tail = f.read().decode("utf-8", errors="replace")
        hit = None
        for line in tail.splitlines()[1 if size > SUB_LANG_TAIL else 0:]:
            if '"assistant"' not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            for b in (d.get("message") or {}).get("content") or [] if d.get("type") == "assistant" else []:
                if isinstance(b, dict) and b.get("type") == "text":
                    t = (b.get("text") or "").strip()
                    if len(t) > 40 and _sub_cjk_ratio(t) < SUB_LANG_MIN_RATIO:
                        hit = t
        if not hit or hit[:80] == rec["last"]:
            return None  # 沒有不合語言的文字，或同一則已經提醒過
        now = time.time()
        seen = {k: v for k, v in seen.items() if now - float(v["at"] if isinstance(v, dict) else v) < 3 * 86400}
        n = rec["n"] + 1
        seen[aid] = {"n": n, "last": hit[:80], "at": now}
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(SUB_LANG_STATE, "w", encoding="utf-8") as f:
            json.dump(seen, f, ensure_ascii=False)
        again = "" if n == 1 else f"這是第 {n} 次提醒，前面提醒過你又寫回原來的語言。"
        return (f"【語言（hook）】{again}你剛才在工具呼叫之間寫的說明文字不是使用者設定的語言（{lang}）：「{hit[:50]}…」。"
                "使用者會看這些過程文字：從現在起，每一則說明文字與最終報告都用該語言（與全域 CLAUDE.md 同一種文字）；指令、程式碼、檔名照原樣。")
    except Exception:
        return None


def _sub_guard_reason(payload, report, scan, how):
    """兩個入口共用：回退回理由字串或 None，並記下「這個 agent 已退回過」。scan＝agent 對話紀錄掃描結果（可為 None）。"""
    aid = str(payload.get("agent_id") or "")
    if not aid or not report.strip() or payload.get("agent_type") in SUB_LIGHT_TYPES or not _sub_cfg(payload.get("cwd"))["guard"]:
        return None
    try:
        with open(SUB_GUARD_STATE, encoding="utf-8") as f:
            seen = json.load(f) or {}
    except Exception:
        seen = {}
    if aid in seen:
        return None
    mem = os.path.normpath(os.path.join(os.path.dirname(payload.get("transcript_path") or ""), "memory"))
    bad = subagent_report_judge(report, scan, _settings_language(), mem)
    if not bad:
        return None
    now = time.time()
    seen = {k: v for k, v in seen.items() if now - float(v) < 3 * 86400}
    seen[aid] = now
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(SUB_GUARD_STATE, "w", encoding="utf-8") as f:
        json.dump(seen, f)
    with open(os.path.join(STATE_DIR, "source-guard.log"), "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} block-agent {aid} {len(bad)} 項：{'｜'.join(b[:24] for b in bad)}" + chr(10))
    return ("【報告守門（hook）】這份報告還不能交，有 " + str(len(bad)) + " 項不合格：" + chr(10)
            + chr(10).join(f"{i}. {b}" for i, b in enumerate(bad, 1)) + chr(10) + how + "只退回這一次，之後不會再擋。")


def subagent_report_guard(payload):
    """PreToolUse(SubagentHandback)：不合格就擋下這次交報告並說明要補什麼；同一個 agent 只擋一次。任何例外都放行。"""
    try:
        tp = _sub_transcript(payload)
        reason = _sub_guard_reason(payload, str((payload.get("tool_input") or {}).get("message") or ""), _sub_scan(tp) if tp else None,
                                   "補完後再呼叫一次 SubagentHandback，交**完整報告**（不是只交補充的部分）。")
        if not reason:
            return None
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}
    except Exception:
        return None


def subagent_stop_guard(payload):
    """SubagentStop 後備：agent 沒有用 SubagentHandback 交報告時（不是 auto mode、fork、2.1.271 之前——tools-reference.md 寫該工具
    「Provided only in auto mode, to subagents that the Agent tool runs locally other than forks」）才在這裡核對最後一則訊息。
    內部分支（agent_type 空字串、紀錄檔或 .meta.json 不存在；anthropics/claude-code#87065、#91910）一律放行。"""
    try:
        if payload.get("stop_hook_active") or not payload.get("agent_type"):
            return None
        tp = str(payload.get("agent_transcript_path") or "")
        tp = os.path.expanduser(tp) if tp else (_sub_transcript(payload) or "")
        if not tp or not os.path.isfile(tp) or not os.path.isfile(tp[:-6] + ".meta.json"):
            return None
        scan = _sub_scan(tp)
        if scan is None or "SubagentHandback" in scan["tools"]:
            return None  # 報告已經由 SubagentHandback 交出並在那裡核對過
        reason = _sub_guard_reason(payload, str(payload.get("last_assistant_message") or ""), scan,
                                   "補完後重新寫出**完整報告**當作你的最後一則訊息（main 只會收到最後一則，不是只寫補充的部分）。")
        return {"decision": "block", "reason": reason} if reason else None
    except Exception:
        return None


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
        patrol_sync(payload)
        out = source_guard(payload)
        if out:
            print(json.dumps(out, ensure_ascii=True))
        return
    if event == "PreToolUse":  # 0.22.0：只註冊在 SubagentHandback（agent 交報告）
        if payload.get("tool_name") == "SubagentHandback":
            out = subagent_report_guard(payload)
            if out:
                print(json.dumps(out, ensure_ascii=True))
        return
    if event == "SubagentStop":  # 0.22.0 後備：沒走 SubagentHandback 的 agent
        out = subagent_stop_guard(payload)
        if out:
            print(json.dumps(out, ensure_ascii=True))
        return
    if event == "SubagentStart":  # 0.21.0：把不會自動傳給 agent 的東西補進去
        msg = subagent_brief(payload)
        if msg:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": msg}}, ensure_ascii=True))
        return
    if event == "SessionStart":  # 0.12.0：壓縮或接續後重新開工；新對話（startup）由 UserPromptSubmit 的專案自動化處理
        if payload.get("source") == "compact":
            t0 = time.time()
            from_sub = compact_from_subagent(payload)
            _hook_debug("SessionStart", dict(payload, _from_subagent=from_sub, _decide_sec=round(time.time() - t0, 2)))
            if from_sub:
                return  # agent 自己的壓縮：不把主對話的開工清單塞給它，也不算進主對話的壓縮次數
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
            # 0.14.0：不再 return——原本讀不到用量就整個結束，專案自動化、健康檢查、全域對照、工具後提醒全被跳過；改用上次的用量數字繼續
        else:
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
        am = align_msg(hook_cwd, payload.get("session_id"), mark_only=bool(pa))  # 全域系統升次版號：每資料夾每版一次
        if am:
            msgs.append(am)
        hm = health_msg(hook_cwd, session_id=payload.get("session_id"))  # 盤點過期、CLAUDE.md／交接紀錄過大：同資料夾同對話每天一次
        if hm:
            msgs.append(hm)
    if event in ("UserPromptSubmit", "PostToolUse"):  # 0.16.0：殘留程序、延後工作、對話暫存（全部節流，平常只讀狀態檔）
        st = _pa_load()
        before = json.dumps(st, sort_keys=True)
        sid = payload.get("session_id")
        extra = [proc_msg(hook_cwd, sid, st, now)]
        if event == "UserPromptSubmit":
            extra += [deferred_msg(hook_cwd, sid, st, now), temp_msg(hook_cwd, st, now)]
        if json.dumps(st, sort_keys=True) != before:  # 沒變就不寫檔
            _pa_save(st)
        msgs.extend(m for m in extra if m)
    if event == "PostToolUse":  # 0.14.0：改安裝副本、背景任務巡檢、波及範圍、共用目錄 git
        msgs.extend(tool_reminders(payload))
        nudge = subagent_lang_nudge(payload)  # 0.23.0：只在 agent 裡、只一次
        if nudge:
            msgs.append(nudge)
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
