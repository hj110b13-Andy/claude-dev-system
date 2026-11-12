# 架構與資料流（2026-11-12 全方位健檢時依實際程式整理；改到資料流或介面時同步更新）

這個 repo 做一件事：把一套「Claude Code 全域工作規則＋hook＋工具」裝進使用者的 `~/.claude`，並讓它能更新、驗證、解除安裝。
執行期沒有常駐服務——所有程式都是「被叫起來跑一次就結束」的 Python 腳本（只用標準庫，Python ≥ 3.10）。

## 一、四個部分與它們的關係

```
repo（來源）                          使用者的 ~/.claude（安裝結果）
├─ rules/core.md ───────────────────▶ CLAUDE.md 的標記區塊（每次請求都載入）
├─ rules/*.md、tools/、config/ ─────▶ claude-dev-system/{rules,tools,config}/
├─ hooks/usage_guard.py ────────────▶ claude-dev-system/hooks/ ＋ settings.json 的 7 個 hook 條目
├─ skills/cds-*/ ───────────────────▶ skills/cds-*/（Claude Code 原生 skill 位置）
└─ installer/（安裝器＋設定視窗）      claude-dev-system/manifest.json（安裝紀錄）、config/local.json（本機偏好與金鑰）
                                       state/（hook 與工具的執行期狀態）、backups/（settings.json 與 CLAUDE.md 的備份）
```

| 部分 | 檔案 | 誰來執行 | 職責 |
|---|---|---|---|
| 安裝器 | `installer/install.py`、`installer/cds/*.py` | 使用者或 Claude 在終端機 | install／update／uninstall／verify／status／web／video／selftest |
| 設定視窗 | `installer/gui.py`（tkinter 視窗層）、`installer/cds/gui_model.py`（可測的邏輯）、`installer/cds/appdir.py`（下載更新、換 exe） | 使用者；可打包成 exe（`installer/build_exe.py`，GitHub Actions 在推 tag 時建） | 同一批安裝器命令的圖形介面＋自我更新 |
| hook | `hooks/usage_guard.py` | Claude Code 在 7 個事件自動呼叫 | 用量守門、查證／建議守門、專案自動化、壓縮後重新開工、agent 開工補充與交報告守門、工具後提醒 |
| 工具 | `tools/*.py` | Claude 依規則呼叫；hook 也會載入其中三支 | 記憶體閘門、殘留程序、磁碟清理、專案盤點、依賴圖、文件比對、agent 稽核、影片 |

規則與 skill 是「給模型看的文字」，本身不執行；真正自動執行的只有 hook。

## 二、安裝器（`installer/cds/`）

模組依賴方向（沒有循環；`project-scan` 盤點結果循環 0 組）：

```
install.py ─▶ commands ─▶ payload（要裝哪些檔）  manifest（安裝紀錄與遷移）  settings_ops（hook 條目）
                       ├▶ claudemd（CLAUDE.md 標記區塊）  web（MCP 與 env、local.json）  video（pip 套件）
                       └▶ checks（環境與版本）  fsio（原子寫入、雜湊、JSON）  paths（路徑解析、Layout）
gui.py ─▶ gui_model ─▶ commands、web、video、manifest、appdir
selfupdate_exe.py ─▶ appdir
```

- **唯一真相**：`<CLAUDE_HOME>/claude-dev-system/manifest.json`。記版本、每個已裝檔的 sha256、加過哪些 hook 條目與 `env` 鍵、註冊過哪些 MCP、備份清單。安裝器只動「紀錄裡是自己加的」東西；使用者自己的設定不碰。
- **同時只跑一個**：apply／web_config／video_config／uninstall 進入時拿 `claude-dev-system/.install.lock` 的作業系統層級檔案鎖（程序結束自動釋放）；拿不到就回結束碼 2。
- **備份**：每次寫入前備份 settings.json 與 CLAUDE.md；安裝那一次的備份在紀錄裡標 `preInstall`，修剪時永遠保留，`uninstall --restore-backup` 只認它。
- **`commands.apply`（install 與 update 共用）** 的順序：預檢（settings.json 與 CLAUDE.md 讀得懂才往下）→ 備份 → 同步檔案（雜湊相同不寫；使用者改過的保留、新版另存 `.new`；`dispatch-config.json` 例外，只補新鍵）→ 同步 settings.json 的 hook 條目（先清掉帶 `# claude-dev-system` 標記的再加）→ 同步 CLAUDE.md 標記區塊 → 聯網來源（選用）→ 影片來源（選用）→ **最後**才存 manifest。
- **CLAUDE.md**：只動 `<!-- claude-dev-system:begin … -->`～`<!-- claude-dev-system:end -->` 之間；區塊外一字不動；區塊被使用者改過就不覆蓋。
- **settings.json**：只新增／移除指令結尾帶 `# claude-dev-system` 的 hook；`permissions`、`model` 等其他鍵不碰。事件清單的唯一來源是 `settings_ops.HOOK_SPECS`。
- **聯網來源**（`web.py`）：定義在 `config/web-sources.json`；用官方 `claude mcp add／remove --scope user` 註冊（`~/.claude.json` 只讀不寫）；金鑰與開關偏好在 `config/local.json`（不進 repo、不進 manifest 的檔案清單、update／uninstall 不動），所有輸出經 `web.mask` 遮掉金鑰。
- **verify** 是唯讀檢查：版本、每個檔的雜湊（與紀錄、與 repo）、hook 條目、hook 用的 Python、CLAUDE.md 區塊、skills、Claude Code 版本是否在 `config/compat.json` 的範圍。
- **manifest 結構版本**：`MANIFEST_SCHEMA`＝3，`manifest.MIGRATIONS` 逐版遷移（0→1→2→3）；讀到比自己新的版本就停。

## 三、設定視窗與自我更新

- 視窗層 `gui.py` 只負責畫面與執行緒：工作一律丟到背景執行緒、結果經 queue 回主執行緒更新畫面；一次只跑一個工作。能測的判斷都放在 `gui_model.py`（`read_state` 是畫面的唯一真相來源；`apply_form` 把表單變成安裝器命令與 `dispatch-config.json`／`local.json` 的寫入）。
- **兩層更新**：①規則與工具——比對 GitHub `master` 的 `config/VERSION`，下載整包到 `claude-dev-system/app/`（只解需要的資料夾、擋 `..`、原子替換），之後以 `app/` 當來源套用；②exe 本身——GitHub 最新 Release 的 tag 比 exe 內建版本新就下載、比對大小與 `.sha256`、改名換檔、重開。exe 自己的更新步驟失敗時，改跑 `app/installer/selfupdate_exe.py`（永遠是最新程式碼）當備援。
- `.sha256` 與 exe 來自同一個 Release，只能防下載截斷或損毀；沒有程式碼簽章。
- **發布**（`.github/workflows/release.yml`）：推 `v主.次.修` 的 tag → 比對 tag 與 `config/VERSION` → 單元測試 → PyInstaller 打包 → 不開視窗的 selfcheck → 產生 `.sha256` → 附到 Release。任一步失敗就不發。平常 push 另有 `tests.yml` 在 Python 3.10／3.12／3.14 跑測試。

## 四、hook（`hooks/usage_guard.py`）

一支腳本、七個事件；從 stdin 讀 Claude Code 給的 JSON，依 `hook_event_name` 分流，最後把提醒寫到 stdout。**任何例外都吞掉、結束碼恆為 0**——hook 壞了不可擋住 Claude Code。

| 事件 | 做什麼 | 輸出形式 |
|---|---|---|
| UserPromptSubmit | 用量守門、專案自動化判定、全域系統對照、專案健康檢查、延後工作、磁碟清理、殘留程序 | `additionalContext` |
| PostToolUse（只掛會推進工作的工具） | 用量守門（節流）、改到安裝副本／波及範圍／共用工作目錄／背景任務巡檢提醒、殘留程序、agent 的語言提醒 | `additionalContext` |
| Stop | 巡檢排程狀態校正；查證守門與建議守門（讀主對話紀錄最後一輪） | `decision: block`（一場只擋一次） |
| SessionStart | 壓縮或接續後重新注入開工清單、健康檢查；壓縮滿 3 次建議開新對話 | `additionalContext` |
| SubagentStart | agent 開工補充：語言、工作目錄與分支、記憶路徑、自我核對清單 | `additionalContext` |
| PreToolUse（`SubagentHandback`） | 交報告守門：語言、數字出處、上網前讀速查、讀記憶、commit 分支 | `permissionDecision: deny`（每個 agent 一次） |
| SubagentStop | 交報告守門的後備（agent 沒走 `SubagentHandback` 時） | `decision: block` |

- **設定讀法**：專案 `.claude/dispatch-config.json`（從 cwd 往上找）優先，其次全域 `claude-dev-system/config/dispatch-config.json`，最後內建預設。
- **用量**：讀本機登入憑證的權杖打 Anthropic 用量端點（8 秒逾時、5 分鐘快取、接近門檻時 1 分鐘），結果只存百分比與重置時間到 `state/usage.json`；權杖不寫進任何檔或輸出。
- **狀態檔**（`<CLAUDE_HOME>/state/`）：`usage.json`、`project-auto.json`（各種「提醒過了沒」的去重與計數）、`subagent-guard.json`、`subagent-lang.json`、`source-guard.log`、`deferred-jobs.json`（延後清單，`tools/resgate.py` 寫、hook 讀）。多場對話會同時讀寫，所以寫入一律原子替換。
- **與工具的關係**：hook 用「同一份安裝裡的相對路徑」動態載入 `tools/resgate.py`（延後清單與同專案判定）、`tools/procs.py`（殘留程序）、`tools/project-scan.py`（連結判定、原始碼計數）；`tools/agent-audit.py` 反過來載入 hook 的判定函式。這些跨檔引用的名稱是介面，改名前要查兩邊。
- 會輸出的標籤與對應規則：`rules/workflow.md`〈hook 標籤對照〉。

## 五、工具（`tools/`，都是獨立腳本）

| 工具 | 用途 | 讀寫 |
|---|---|---|
| `resgate.py` | 重型工作的記憶體閘門（`check`／`wait`／`run`）與延後清單（`defer`／`list`／`next`／`done`） | 讀 `dispatch-config.json` 的 `resourceGate`；寫 `state/deferred-jobs.json` |
| `procs.py` | 列出這場對話的工具指令開出、跑太久的程序（只列不殺） | 只讀程序表 |
| `cleanup.py` | 列出可清的 worktree、對話暫存、npm cache、建置快取；`--apply` 才刪，不跟隨連結 | 預設零寫入 |
| `project-scan.py` | 專案盤點：檔案分類、依賴圖、循環、大檔、入口；`--check` 比對上次盤點、`--summary` 判定算不算專案 | 寫目標專案的 `.claude/project-scan.json` 與 `docs/PROJECT-INVENTORY.md` |
| `depgraph.py`、`moduleInventory.py` | 依賴圖與循環閘門（`--max-cycle-files`、`--forbid`）；模組清單 | 只讀專案；輸出到指定檔 |
| `progress-diff.py` | 精簡或搬移文件後逐句比對，列出新版找不到的句子 | 只讀 |
| `agent-audit.py` | 從對話紀錄統計派出的 agent 有沒有照規則做 | 只讀 `~/.claude/projects/` |
| `video.py` | 影片：搜尋、逐字稿、截圖、數據、Gemini 問答、下載（選用，需 `--with-video`） | 快取在 `claude-dev-system/cache/video/`；金鑰讀 `local.json` |

## 六、資料與設定在哪裡

| 資料 | 位置 | 進 repo？ | 誰寫 |
|---|---|---|---|
| 版本 | `config/VERSION` | 是 | 人（每次發布往上加） |
| 相容範圍 | `config/compat.json` | 是 | 人（實測後） |
| 門檻與開關（用量、記憶體、巡檢、專案自動化、模型表…） | `config/dispatch-config.json`；安裝後的那份使用者可改，update 保留 | 範本是 | 使用者／設定視窗 |
| 聯網來源定義、影片預設值、自測題目 | `config/web-sources.json`、`video.json`、`selftest.json` | 是 | 人 |
| 金鑰、開關偏好 | `<CLAUDE_HOME>/claude-dev-system/config/local.json` | **否** | `install.py web`／設定視窗 |
| 安裝紀錄 | `<CLAUDE_HOME>/claude-dev-system/manifest.json` | 否 | 安裝器 |
| 執行期狀態 | `<CLAUDE_HOME>/state/` | 否 | hook、`resgate.py` |

## 七、錯誤怎麼傳

- 安裝器：每個子命令回 `(結束碼, 訊息列)`；0 成功、1 有 ❌、2 用法或狀態錯誤（含「另一個安裝程序正在執行」與預檢不過）。使用者看得懂的錯誤用 `ValueError` 丟、`install.py` 印成一行 ❌；不該出現 traceback。
- hook：永不失敗（結束碼 0）；讀不到用量、狀態檔壞掉都安靜略過那一項，其他提醒照常。
- 工具：參數錯誤結束碼 2；`resgate.py run` 透傳被執行指令的結束碼，記憶體不足是 1。

## 八、已知的結構性取捨（不是待修問題）

- **四個大檔**（>800 行）：`hooks/usage_guard.py`、`installer/cds/gui_model.py`、`tools/video.py`、`installer/gui.py`。hook 與工具各自要能「單檔被複製到別處就能跑」，所以沒有拆成套件；2026-11-12 健檢決定不做大規模拆檔（見 `PROJECT-AUDIT-REPORT.md`）。
- **hook 與工具之間用動態載入共用程式**，而不是共用套件——同樣為了單檔可獨立執行。代價是跨檔介面只能靠測試守住。
- **平台**：只在 Windows 11 實機驗證；macOS／Linux 的路徑邏輯有寫但沒有實機跑過（`config/compat.json`）。
