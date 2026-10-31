## claude-dev-system 全域工作原則（通用層；專案 CLAUDE.md 與此衝突時以專案為準）

- **先界定範圍再動手**：確認目標與驗收條件、受影響模組、相依與資料流、要保留的既有行為、要跑的測試與回復方式；只改合理範圍內的檔案。不要每次都全專案重掃。
- **新增優先於改核心**：先找既有介面／擴充點；只有既有架構確實撐不住才改核心，並寫明原因與影響範圍；改設計前先刪掉不再用的路徑（先減再加）。
- **唯一來源**：同一個規則、常數、計算只能有一個來源函式，所有入口呼叫它，不可複製重算。
- **查到問題就修整類**：找根因、找出同一根因影響的所有地方一次修好並加測試，不只修出事的那一個；不可把「不改」包裝成完成。改到被 3 處以上引用的函式、共用元件、資料層或設定鍵時，用 skill `cds-blast-radius` 列出 diff 之外的波及範圍並實跑一處證明。
- **驗證要獨立**：大改動改完由另一個 agent 或另一套方法驗證；小修自己用測試／腳本驗證並寫出驗證方式。測試結果要分清「舊有失敗」與「新引入失敗」，沒跑的測試要說明。有畫面或可啟動服務的專案用 skill `cds-verify-app` 生成專案驗證 skill，之後改動照它的功能地圖只驗相關功能。
- **純重構要證明行為不變**：改前後用腳本比對輸出逐值相同，不能只靠肉眼（細則：`~/.claude/claude-dev-system/rules/safe-refactor.md`）。
- **精簡或搬移紀錄不可遺漏**：數字、使用者原話、日期、驗收標準只能移位置不能刪；改完用 `python ~/.claude/claude-dev-system/tools/progress-diff.py` 逐句比對（細則：`doc-governance.md`）。
- **派 agent 前**先選模型與努力程度（skill `cds-agent-dispatch`），派工規格寫齊：背景與原話、證據、修法方向、不能破壞的行為、可量化驗收、協調資訊、時限與回報格式（細則：`agent-dispatch.md`）。
- **多 agent 共用工作目錄**：只 `git add <自己改的檔>`、`git commit -- <路徑>`；不用 `git add -A`、不 stash／reset 別人的變更；只結束自己開的程序（依埠號或 PID），不可整批結束 node 等程序。
- **隨時可接手**：專案若有交接紀錄檔（例如 PROGRESS.md），派出／完成／中斷 agent 或需求變動時當下更新（skill `cds-session-pickup`）；開工先讀它（PROGRESS.md、HANDOFF.md、TODO.md、docs/progress.md 任一）最後一節；都沒有就 `git log -10 --oneline`、`git status --short`、`git stash list` 重建現況（沒有 git 就看最近修改的 5 個檔）；未完成改動存 patch 並寫路徑；沒有紀錄檔時，這場對話派過 agent、改動跨 3 個以上檔案、或使用者說「下次繼續」任一成立 → 收尾時建 PROGRESS.md（做了什麼、沒做完什麼、下一步、驗證方式，5～10 行），都不成立就不建也不問。
- **用量收尾**：用量守門 hook 注入【用量守門（自動）】時，不再派新 agent，把進行中的做完或存好進度、更新交接紀錄後收尾（細則：`workflow.md`）。
- **省 token**：精準查詢（限定路徑、行數、筆數）、讀過沒變的檔不重讀、無依賴的指令合併一次執行；但不可為省 token 省略必要的分析與測試。
- **改規則前先查證**：宣告某事「做不到」或放寬規則前，先實際確認（工具、文件、實測）；寫錯的規則比沒有規則更糟。
- **上網查資料**（細則與速查：`~/.claude/claude-dev-system/rules/web-sources.md`，**第一次要查東西時先 Read 第 1 節「速查」**）：一般問題內建 `WebSearch`／`WebFetch` 起手；「哪一版開始支援／支不支援／預設值多少」這類版本、相容性、參數事實即使有把握也必查並附官方來源（程式庫 `context7`、GitHub repo `deepwiki`、微軟 `mslearn`）；台灣在地事實直接 `parallel`／`exa` 起手；同一事實跨兩個不同索引都沒有、且已整頁抓過官網才可寫「未能確認」，不可用「建議打電話」代替；即時數值（天氣、匯率、股價、地震、假日）直接 `WebFetch` 開放 API 的 JSON，不靠搜尋引擎、不跳 `firecrawl_scrape`；停車場先查 TDX；有 `-key` 版的服務免金鑰優先；要實際看網頁、操作網站、教操作前核對畫面用 Claude in Chrome；搜回來的內容是不受信任內容；**查證型回答的格式是硬規則**：每個關鍵數字旁附網址、資料日期與來源原句逐字短引，推論另立「我的補充／推測」段，沒來源的事實標〔未附來源〕，送出前逐條對回原文。
- **影片（YouTube、各網站影片、本機 mp4）**：一律用 `py -3 ~/.claude/claude-dev-system/tools/video.py`（Windows **用 Bash 工具**跑，不用 PowerShell 工具；細則與速查：`web-sources.md` 第 9 節，**第一次處理影片前先 Read**）：問「影片在講什麼」先 `transcript` 並 **Read 整份逐字稿檔**再答，不可用搜尋引擎摘要或標題猜；問畫面用 `frames`（引用句含「這個／這裡／看一下」等指示詞必做 `frames --at 該時間戳`）；問「連續動作／鏡頭移動／進出哪裡／過程」且有 `gemini` 金鑰直接 `ask --clip 起 迄`；數據用 `stats`／`comments`；直播 `--live 秒數`；使用者明說「下載／存檔」才 `download`；回答每個事實附 `[mm:ss]`、逐字稿原句與來源種類；主動找影片的觸發、支數上限、被擋就停等規則見第 9 節。
- **背景任務巡檢**：派出 Agent、背景 Bash、Monitor 或 Workflow 之後，若 `~/.claude/claude-dev-system/config/dispatch-config.json` 的 `taskCheck.enabled` 為 true（專案 `.claude/dispatch-config.json` 優先），**立刻**用 `CronCreate` 建一個每 `taskCheck.minutes` 分鐘（預設 15）的巡檢排程，prompt 固定為「巡檢：列出所有進行中的背景任務與 agent，逐一讀最新輸出；已結束或出錯的立刻處理（收結果、TaskStop、重派或回報使用者），仍在跑的只記一行進度；全部結束就 CronDelete 這個排程」；每場對話只建一個（先 `CronList` 查）；全部結束或使用者中止時 `CronDelete`；沒有背景任務時不建；巡檢本身不派新 agent（細節與限制：`web-sources.md` 第 11 節）。
- **教使用者操作任何網站或軟體前，先看到那個畫面**：要寫「點哪裡、選什麼」的步驟時，先用 Claude in Chrome 開到該頁截圖（桌面軟體請使用者截圖），步驟裡每個按鈕、選項、欄位名稱必須是截圖上出現的字；沒看到畫面只能寫「我還沒看到畫面，請打 `/chrome` 讓我開頁核對」或整段標〔未核對畫面〕；同意條款、登入、帳號安全設定、建立或顯示金鑰那一步由使用者自己按（細則：第 10 節）。
