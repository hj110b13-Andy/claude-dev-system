# 變更紀錄

格式：語意化版本（主.次.修）。主版號變動＝manifest 或設定結構不相容；次版號＝新增規則／skill／工具；修訂號＝修正。

## 0.18.1（2026-11-09，視窗會自動換 exe）

- **修正 0.18.0**：CHANGELOG 寫了「全域對照 hook 提示同步」，但 `hooks/usage_guard.py` 那次實際沒改到（編輯失敗未察覺）。這版真的改：原「動到程式行為、系統排程或要花大額度的先問一次」→「動到程式行為或系統排程的，先上網查證最佳做法後直接做並附來源；只有不可逆、碰帳號或付款的先問一次」。
- 驗證：unittest 全過；本機 update 後 verify 全 ✅；安裝副本 hook 內出現新字樣。

## 0.18.0（2026-11-09，視窗會自動換 exe）

使用者（同日 Stock-web）：「之後遇到不確定需決定的事，都上網查詢與查證，你不要自己在那邊瞎定，有最佳解法就以你查證的最佳方法來做，不用問我。我要的是你之後都把網路上各方強者做出來的融入成我們自己的，所以不要動不動就問我，也不要你自己盲目過度自信決定，以網路上多方詳細查證後的最佳解來做決定。這部分也要加入規則、長期記憶、全域優化系統。」

- **hooks/usage_guard.py 全域對照提示同步**：原「動到程式行為、系統排程或要花大額度的先問一次」改成「先上網查證最佳做法後直接做並附來源；只有不可逆、碰帳號或付款的先問」。
- **core.md「什麼時候問使用者」改成三種**：不可逆、碰帳號或付款（含會產生費用的外部呼叫）、需求本身有兩種讀法；拿掉「會花大額度」。**不確定的技術決定（方法、架構、門檻、參數、工具、取捨）不問使用者、也不自己憑感覺定：上網與 GitHub 多方查證，照最佳解做，回報附來源。**
- 驗證：unittest 全過；本機 update 後 verify 全 ✅。

## 0.17.2（2026-11-09，視窗會自動換 exe）

使用者（同日 Stock-web）：「你剛剛說的所有方案有沒有你自己在那邊亂加的限制?我發現你也很愛在那邊亂加沒必要的限制，你建議的方法及方向確定全都上網查證過了嗎? 這兩件事也要加到規則與長期記憶，還有全域優化系統」。

- **core.md「先找現成做法」再補**：提出任何建議、方法或方向時逐項標明「已查證（附來源）／未查證」，未查證的列在回覆並先補查，不可把沒核對的摘要或推測當成已確認（起因：把 DeepWiki 的 AI 摘要當事實，讀原始碼才發現不同）。「限制要標來源、沒實證就拿掉」0.17.1 已加。
- 驗證：unittest 全過；本機 update 後 verify 全 ✅。

## 0.17.1（2026-11-09，視窗會自動換 exe）

使用者（同日 Stock-web）：「你再更多次多方詳細上網查詢及github下更多英文關鍵字搜尋……不如先多花時間查證確定好，再一次做完。」「我發現你也很愛在那邊亂加沒必要的限制」。

- **core.md「先找現成做法」補兩點**：大改動前多輪查證（含讀開源專案原始碼本身，不只看 AI 摘要，起因：DeepWiki 摘要說 daily_stock_analysis 的追問判斷是另一套機制，讀原始碼才發現它也是正規表示式＋明確狀態），確定後一次做完；方案裡每個限制與數字標明有來源或自己加的，沒實證的拿掉或交給驗收數據決定。
- 驗證：unittest 全過；本機 update 後 verify 全 ✅。

## 0.17.0（2026-11-09，視窗會自動換 exe）

使用者（2026-11-09 Stock-web，AI 問答修了幾週仍一直出錯後）：「我覺得你從以前到現在為止，根本都沒有真正修好過，只是在應付，把表面做好而已……你去多上網查詢，還有github上多用多個英文關鍵字搜尋，看看別人是怎麼做的……不會就去上網及github上去看看別的大神都是怎麼做的並學習過來使用，你不要再自己瞎忙搞一堆你自以為是對的方面的事，直接去看別人怎麼做的，現成採用過來不是又快成效又好嗎?」並要求「之後不論做哪種類型，都用這種方式……也把這點加入到全域優化系統」。

- **core.md 新規則「先找現成做法，不憑自己硬做」**：任何類型工作動手設計前先上網與 GitHub 用多組英文關鍵字查成熟做法，能採用就採用（守零花費、授權限制），自己設計只在找不到現成做法時；同一問題修 2 次仍不好＝方法錯，停下改查現成做法；回報寫明參考來源與採用內容。起因：Stock-web AI 問答一直用自寫的關鍵字規則猜題型、逐題補洞，查了才發現業界（LangChain／LlamaIndex 追問改寫、FinAI Data Assistant 函式呼叫路由、CIFQA 計算與理解分離、Bloomberg EvidenT 只用驗證過的資料回答）早有成熟做法。
- 驗證：`python -m unittest discover -s tests` 全過；本機 `update` 後 `verify` 全 ✅，全域 CLAUDE.md 標記區塊出現新條文。

## 0.16.2（2026-11-09，視窗會自動換 exe）

使用者看過 0.16.0 G 項的檢查（「只要回覆裡出現任何 .md、.json 檔名就算有來源」是漏洞）後同意收緊：「改」。

- **查證守門：工作文件與設定檔不算數字的出處**：0.16.0 起回覆裡只要有任一 `xxx.md`／`.json` 檔名就放行，順口一句「已更新 PROGRESS.md」就能讓憑印象的數字溜過。改成 CLAUDE.md、AGENTS.md、PROGRESS.md、PROGRESS-ARCHIVE.md、HANDOFF.md、TODO.md、README.md、CHANGELOG.md、SKILL.md、MEMORY.md、package.json、tsconfig.json、settings.json、dispatch-config.json、project-scan.json 等不算（`SG_LOCAL_GENERIC`）；回測報告、快取、腳本輸出等其他本機路徑照舊放行，Stock-web 引用 `docs/backtest/…md` 不受影響。原本提議的「檔名要在『來源』段附近」沒做：回覆有「來源」二字本來就直接放行，這條加了反而會擋掉 Stock-web 沒寫「來源」二字的正常引用。
- 驗證：舊程式對「已更新 PROGRESS.md」「見 docs/progress.md」「改了 package.json」都放行、新程式退回；「數字見 docs/backtest/a.md」新舊都放行。test_hooks 加這幾個正反例。

## 0.16.1（2026-11-09，視窗會自動換 exe）

- **v0.16.0 的 Release 沒建出來**：GitHub Actions 單元測試 1 項失敗（Cleanup：已合併的 worktree 被判成「沒登記成 git worktree 的資料夾」，Release 因此沒有 exe）。根因：`cleanup.py` 用字串比對 git 回的路徑（長檔名 `C:/Users/runneradmin/…`）和走訪到的路徑（runner 的暫存是 8.3 短檔名 `RUNNER~1`），同一個資料夾比不起來。改用 realpath 後再比對；測試改成故意用短檔名的暫存資料夾，這台用舊程式重現同一個失敗、新程式通過。0.16.0 的功能內容不變（見下一段），請以 0.16.1 為準。

## 0.16.0（2026-11-09，視窗會自動換 exe）

使用者（2026-11-09 Stock-web 對話）看過改進清單後：「二、適合改進到全域系統 claude-dev-system 的 A~I全都做，其中E的部分你先具體跟我談你的上限與門檻要怎麼設，我再決定。」E 談完後：「等 10 分鐘還不夠就不跑：直接回報「記憶體不足、沒有執行」，由我決定之後再跑。不會卡住，也不會硬跑出問題，只是那個工作會延後。我選這個，但要寫清楚規則當有其他agent完成時，要確認記憶體是否足夠了，並開始跑「記憶體不足、沒有執行」的任務。然後先設固定 3GB就好，提醒就不用了，記憶體門檻要用成視窗可更改的。」

- **A. project-scan 把 worktree 算進盤點**（11/8 Stock-web「被引用最多」出現 `.claude/worktrees/agent-xxx/scripts/eval/types.ts：被 104 個檔引用`，跑了約 5 分鐘）。根因三個：①`ts_graph` 呼叫 `depgraph.build_graph` 時 depgraph 自己 `os.walk` 整個 root，只排除 `__tests__`、`node_modules`，project-scan 的 EXCLUDE_DIRS／.gitignore 判斷完全沒用到——worktree 1,834 檔、`.next` 837 檔都算進依賴圖；②Windows 的 `os.walk` 會走進 junction（`os.path.islink` 對 junction 回 False，Python 3.14 實測），名字不在排除清單的連結都會被跟隨；③別名寫死 `@/`→root，Next.js 的 `"@/*": ["./src/*"]` 解析不到，Stock-web src/ 底下所有 `@/` 引用都沒算。改法：depgraph 收呼叫端給的檔案清單與內容（不再自己遍歷），走訪跳過目錄連結與巢狀 checkout（子資料夾有 `.git` 檔或資料夾），別名讀 tsconfig／jsconfig 的 `paths`（JSONC）。慢的原因：防毒即時掃描讓每次 `open()` 約 3 ms，原本每個檔雜湊、數行、depgraph 各開一次（冷啟動 12,156 次 open 佔 48 秒裡的 36 秒），每條邊再兩次 `Path.resolve`；改成每檔只讀一次、路徑用字串處理，`--check` 大小與修改時間相同就不重算雜湊。Stock-web 實測：舊版 9.2 秒（熱）／48 秒（冷）→ 新版 1.8 秒；`--check` 0.6 秒。結果：被引用最多變成 `src/lib/data/types.ts` 266、`src/lib/ai/siteRating.ts` 247（原本前三名都是 worktree 副本），依賴邊 8,768→10,027。
- **B. 健康檢查讀到過期盤點**（11/8～11/9 一直報「scripts/backtest/exitStrategy.ts（6588 行 > 800）」，實際已拆成 26 行）：報大檔前比對實際行數，檔案不在或已不超標就不報，還超標的報「現在 N 行」。
- **C. 巡檢看不到 agent 留下的系統程序**（11/8 `until [ $(grep -c "FULL" …run-s1.log) -ge 13 ] … do sleep 10; done` 與 tail.exe 從 21:02 空轉到隔天）：新工具 `tools/procs.py`（Windows 用 Toolhelp32／NtQueryInformationProcess，一次約 20 ms；其他系統用 ps）列出這場對話（CLAUDE_PID）底下工具殼開出、跑超過 `procCheck.minMinutes`（60）分鐘的程序與子程序，只留真正的指令；上層已不在的工具殼也列。hook 每 `procCheck.everyMinutes`（10）分鐘最多查一次，新 PID 才注入【殘留程序（hook）】，只提醒、不自動結束。巡檢固定 prompt 加「跑 procs.py」。
- **D. 派工範本三條固定條款**（rules/agent-dispatch.md、skill cds-agent-dispatch）：①交報告前結束自己開的背景程序（含 until／tail 迴圈、回測、伺服器）②重型程序開跑前過記憶體閘門（門檻只讀 config）③暫存檔用自己的子資料夾（11/8 共用 scratchpad 被別的 agent 覆蓋 head.md／tail.md；這次改 repo 時也在共用 scratchpad 撞到別人的 re.py，`import re` 直接失敗）。
- **E. 重型工作記憶體閘門＋延後清單**：設定唯一來源 `dispatch-config.json` 的 `resourceGate`（`minFreeMemGB` 3、`waitMinutes` 10、`pollSeconds` 60）；新工具 `tools/resgate.py`：`wait` 不足每 60 秒看一次、最多 10 分鐘（最後一次檢查留 15 秒，不被 Bash 10 分鐘上限砍掉），仍不足不跑、印「記憶體不足、沒有執行」並登記延後清單 `<CLAUDE_HOME>/state/deferred-jobs.json`（專案、工作、怎麼重跑、登記時間）；`next`／`done`／`list`。主對話規則：有 agent／背景任務完成先 `resgate.py next`，夠就依登記順序開跑、跑一個再查一次（core.md 一句、agent-dispatch.md 細則、巡檢 prompt 加「檢查延後清單」）；hook 在清單有項目且記憶體夠時注入【延後工作（hook）】，派背景任務的巡檢提醒也帶清單項數。沒有「同時 N 個重型」的提醒。設定視窗「核心」區加「重型工作記憶體門檻（GB）」（1～32，存回 config，匯出／匯入同一個檢查）。
- **F. 安全清理工具 `tools/cleanup.py`**（11/8 Stock-web 一次清出約 14 GB；刪 worktree 前有 12 個 .cache 子目錄 junction 指向主目錄資料）：預設只列清單與可省空間，`--apply` 才刪。worktree 只刪沒有未提交變更、分支內容已在主分支的（SHA 祖先 → `git merge-tree` 內容比對，`git pull --rebase` 改寫 SHA 也認得 → 舊 git 才用 `git cherry`；判不出保留），先只拆目錄連結再 `git worktree remove`（不加 --force），分支預設保留；對話暫存保留目前對話與 24 小時內動過的；npm cache 用 `npm cache clean --force`；專案 `.next` 等可重建快取（不含 `.cache`）。刪除一律不跟隨連結，鎖住的檔照實列出不重試。workflow.md〈磁碟清理〉寫明何時用。
- **G. 查證守門誤擋本機資料數字**（11/8～11/9 Stock-web 數字全來自本機回測報告仍被退回 3 次）：回覆有本機路徑（docs/、.cache/、scripts/、data/、reports/… 或 .md／.json／.csv／.log 檔名）或標「本站資料／本機報告」就算有來源；只提資料夾名、網域、版本號仍退回。
- **H. 全域 git 規則：有 merge commit 不 rebase**（11/8 Stock-web：rebase 把多個 merge 拆成直線、卡衝突、分支 SHA 全變，看起來像沒合併）：core.md 一句、workflow.md〈推送前同步〉（判定 `git log --merges @{u}..HEAD`）、agent-dispatch.md。【全域系統對照】會點名專案 CLAUDE.md、AGENTS.md、`.claude/skills/*/SKILL.md`、`docs/claude-rules/*.md` 裡寫死 `git pull --rebase` 的檔案與行號（Stock-web 實測抓到 progress-handoff、push-gate-deploy 兩個 skill）。
- **I. Claude 對話暫存自動提醒**（11/8 `%LOCALAPPDATA%\Temp\claude` 3.8 GB）：開工 hook 每天最多量一次（0.5 秒內、超過門檻就停），超過 `cleanup.claudeTempWarnGB`（2 GB）每 `remindDays`（7）天最多提醒一次可跑 `cleanup.py --only temp`；只提醒不刪。
- **hook 效能**（同一台、同條件各跑 11 次）：PostToolUse 中位數 129→133 ms（+4 ms；每 10 分鐘那一次要查程序 +約 40 ms）；UserPromptSubmit 中位數 147→152 ms（+5 ms；每天第一次要量對話暫存，那一次 319→687 ms）。狀態沒變不寫檔。
- 測試：test_tools 加 ProjectScanWorktrees（巢狀 worktree、目錄 junction、tsconfig 別名、mtime 捷徑、JSONC）、Cleanup（已合併／rebase 後 SHA 不同／未合併／有未提交／junction 不被跟隨主資料不受影響／對話暫存）、ResGate、Procs；test_hooks 加本機資料來源（含反例）、過期大檔、pull --rebase 點名、SessionUpkeep（殘留程序、延後工作、對話暫存）；test_gui_model 加記憶體門檻。

## 0.15.1（2026-11-07）

使用者貼另一台 11/5 的自我測試結果「❌ 自我測試 9/11 題通過」：pwsh「預期 ^mcp__mslearn__ 沒有出現」、docs「預期 ^mcp__context7__／^mcp__deepwiki__ 沒有出現」，三題的回答都含來源與查證過程。

- **自我測試改判「有沒有查一手來源」，不寫死工具**：這台重現 docs 失敗，看報告是模型直接整頁抓 requests 官方文件（parallel web_fetch）、用 GitHub API 與 raw 檔確認 `yt_dlp/extractor/bilibili.py`，答案正確且逐字引用——判失敗的是測試本身。pwsh 這台重跑通過、另一台失敗，同樣是時好時壞。pwsh 改為 mslearn 或 learn.microsoft.com；docs 改為 context7 或 requests 官方文件頁、deepwiki 或 GitHub API／raw。只搜尋、沒抓一手來源仍判失敗（測試涵蓋）。改完兩題實際重跑都通過。
- **規則同步**（web-quick、web-sources）：context7／mslearn 也可直接整頁抓該官方文件頁；repo 裡「哪個檔案、哪一行、目前內容」以 GitHub 本身為準（API／raw），deepwiki 是 AI 生成摘要，適合問架構。
- **`selftest --only` 收逗號**：使用者用 `--only pwsh,docs` 被回「沒有這些題目」；原本只能 `--only pwsh --only docs`。
- 測試：test_selftest 加逗號與一手來源判定。

## 0.15.0（2026-11-07，視窗會自動換 exe）

使用者 11/4：「所有環境安裝的部分可不可以都用成點按鈕就直接安裝，不用再去網頁自己載、自己裝，裝的版本就挑穩定又最新的版本」「我覺得Deno與Node兩個都裝可以嗎?」→「你說的都可以」。11/7：「週用量更新了，可以繼續做了…把待辦與問題都修好。」

- **環境區全部一鍵安裝**：新增 Python（winget `Python.Python.3.14`：winget 上最新正式版 3.14.10，新裝置實測 faster-whisper 1.2.1 可用，ctranslate2 4.8.5 有 Windows cp314 套件）、Git（`Git.Git`）、Node.js（`OpenJS.NodeJS.LTS`，LTS 線不用 Current）、Claude Code（官方原生安裝 stable 通道，不用 winget：官方「WinGet installations do not auto-update」；stable＝「typically about one week old, skipping releases with major regressions」）。按鈕文字、安裝指令、確認訊息各集中一張表（`INSTALL_ACTIONS`／`INSTALL_LABELS`／`INSTALL_CONFIRM`），`install_button` 決定放什麼按鈕；需要 winget 卻沒有時退回開下載頁。
- **Deno、Node 分兩列各有按鈕**：原本找到 Deno 就算通過，Node 不會出現按鈕。最低版本只放 `config/video.json` 的 `jsRuntimeMin`（Deno 2.3.0、Node 22.0.0，yt-dlp wiki/EJS），安裝器與 `tools/video.py` 都讀它；`tools/video.py` 沒有 Deno 時只在 node 版本夠才指定 node（原本只看有沒有 node）。
- **hook 的「盤點過期」計數與 project-scan 同一套 .gitignore 判斷**：`_count_newer` 直接載入同一份安裝裡 tools/project-scan.py 的 `git_ignored`（唯一來源）。原本被排除的檔照算，Stock-web 436 個評測輸出會讓「改過 >20 檔」提早觸發。Stock-web 實測 0.1 秒。
- **發版衛生**：repo CLAUDE.md 加「多場對話會同時改這個 repo，VERSION 已打過 tag 就要往上加」；新測試 `tests/test_release_hygiene.py`：已發布版本之後又有改到發布內容的 commit 就失敗（加入時當場抓到下面這筆）。
- **併入：11/4 18:32 誤標 0.14.2、沒進任何 Release 的修正**（AI-Search&Fetch 提交 `95c184c`，比 v0.14.2 tag 晚 5 分鐘，其他裝置看版本相同就拿不到）：
  - **project-scan 把 .gitignore 排除的檔案也算進去**（AI-Search&Fetch 實測：`--check` 32 筆裡 7 筆是 `.wrangler/` 與 `.dev.vars`，本機跑過服務就變動，「改過 >20 檔要重跑盤點」提早觸發）。git 專案改用 `git ls-files --others --ignored --exclude-standard --directory` 判斷（巢狀 .gitignore、全域排除、否定規則都算）；不是 git 專案或 git 不能用就照舊。索引裡已有的這類檔案下次 `--check` 會列為刪除，重跑盤點後消失。
  - 測試：test_tools 的 ProjectScanGitignore：被忽略的檔與資料夾不列入、已追蹤檔照列、否定規則照算、非 git 專案照舊。

## 0.14.2（2026-11-04，視窗會自動換 exe）

使用者在全新裝置實測：「node沒有給下載按鈕，claude in chrome要我自己在/chrome開啟才能勾選，faster-whisper第一次安裝失敗，後面關掉重開才成功。」

- **faster-whisper 第一次失敗（expected str, bytes or os.PathLike object, not NoneType）**：系統 Python 路徑 `PY` 只在開窗時找一次，程序的 PATH 也是啟動時那份；視窗開著才裝的 Python 在關掉重開前都是 None，直接傳給 subprocess（`install_action('faster_whisper', None)` 重現同一句錯誤）。同一根因也影響視窗開著才裝的 Claude Code、ffmpeg。改成重新整理、安裝、套用、更新前都從登錄檔補回 PATH（`refresh_path`，原有順序不動）並重找 Python（`_ensure_python`）；真的沒有 Python 時顯示白話說明。
- **Claude in Chrome 要先 /chrome 才能勾**：`chrome_default_enabled` 在 ~/.claude.json 存在但還沒有 `claudeInChromeDefaultEnabled` 時也回 None，勾選框被鎖住，還顯示「找不到 ~/.claude.json」。改成沒有鍵或還沒有檔都算「還沒開」可以勾；只有檔案壞掉才鎖。只含這個鍵的新檔，Claude Code 啟動後會保留（CLAUDE_CONFIG_DIR 暫存目錄實測）。原本的測試把這個行為寫成預期，一併更正。
- **② native host 查錯機碼（從 0.8.0 就錯）**：查的是 Claude Desktop 的 `com.anthropic.claude_browser_extension`，官方文件寫 Claude Code 是 `com.anthropic.claude_code_browser_extension`；裝了 Desktop 的機器會誤判通過，只裝 Claude Code 的永遠 ❌。改查正確機碼並確認設定檔存在。❌ 時視窗說明不用手動處理：官方「The first time you enable Chrome integration, Claude Code installs a native messaging host configuration file」，登記後重開 Chrome。
- **JS runtime 沒有安裝按鈕、也認不得 Deno**：環境列文字寫「node／deno」但只檢查 node。加 `video.js_runtime`（唯一來源，檢查 yt-dlp 最低版本 Deno ≥2.3、node ≥22），環境列與 verify 共用；按鈕裝 Deno 不裝 Node：yt-dlp wiki/EJS「Deno (recommended) | Enabled by default」，Node 要另外啟用。
- README 第 6、8 步同步。測試：test_gui_model NewDeviceFlow 6 個。尚未在全新裝置端對端驗證（要等使用者下一次新裝置測試）。

## 0.14.1（2026-11-04）

- **背景任務巡檢提醒漏兩種情況**（使用者：「全域15分鐘的巡查呢？」——Stock-web 指令裡多餘的 `cat` 卡 34 分鐘，要使用者問「還在跑嗎？」才發現）。根因兩個：①指令逾時被自動移到背景時 tool_input 沒有 run_in_background，只看輸入抓不到，改連工具結果的 backgroundTaskId／「moved to the background (ID: …)」一起看；②提醒一場對話只一次，巡檢排程全部結束刪掉後再派任務就沒提醒，改成有任務 ID 就每個任務各一次（提醒句是「先 CronList，沒有才建」，不會重複建）。測試：ToolReminders 加 test_background_task_auto_moved_and_each_task。

## 0.14.0（2026-11-04）

使用者：「還有沒有甚麼可能會遺漏的要改進程自動化?」→ 逐條對照全域規則，列出五條只靠 Claude 記得的 → 「這五項都做」。全部做在既有的 usage_guard hook（PostToolUse 本來就掛在 Bash／PowerShell／Agent／Task／Edit／Write／NotebookEdit／Workflow），不改 settings.json；同一場對話同一件事只提醒一次。

- **改到安裝副本**（Edit／Write／NotebookEdit 的路徑在 `~/.claude/claude-dev-system/` 的 rules、tools、hooks、CHANGELOG，或本工具裝的 skills）：提醒改 repo 再 update、副本改回。起因：Stock-web 11/3 直接改副本，update 之後都裝不上。config/ 不算（dispatch-config.json 本來就給使用者改）。
- **背景任務巡檢**（派 Agent／Task／Workflow，或 Bash／PowerShell run_in_background）：taskCheck.enabled 時提醒先 CronList、沒有就 CronCreate。起因：這場對話（claude-dev-system 0.13.0 發布時）我自己派了背景指令也沒建。
- **波及範圍**（改到盤點索引 mostDepended 裡被 ≥3 個檔引用的檔）：提醒 cds-blast-radius。索引依修改時間快取，不每次解析大檔。
- **共用工作目錄 git**（git add -A／--all／.、git stash（list／show 除外）、reset --hard、clean -f、checkout -- .）：提醒改用 `git add <自己的檔>`、`git commit -- <路徑>`。
- **驗證 skill**（健康檢查）：有畫面或可啟動服務、但 `.claude/skills/` 沒有 *verify* skill → 提醒 cds-verify-app。`projectAutomation.verifySkill` 可關。
- **讀不到用量時其他提醒全被跳過**（端對端測試發現）：usage_guard 讀用量失敗（離線、憑證過期）原本直接 return，同一次的專案自動化、健康檢查、全域對照、工具後提醒全部沒注入；改成沿用上次用量繼續。
- core.md 加一條：看到這些 hook 提醒照做。測試：test_hooks ToolReminders 5 個（觸發、不觸發、只一次、可關）。

## 0.13.1（2026-11-04）

- **project-scan 大檔檢查漏掉腳本**（使用者：「Stock-web 跑重整時，有把 exitStrategy.ts 這類大檔照重整流程拆開了嗎?」）。查證：沒有拆，scripts/backtest/exitStrategy.ts 仍 6,588 行；但 Stock-web 盤點寫「超過 800 行的原始碼 0 個」。根因：project-scan 把 scripts/、tools/ 底下歸成「腳本」，「最大的檔」與 big-file 問題只算「原始碼」，0.12.0 在 cds-modularize 寫的「行數閘門預設涵蓋研究／回測腳本」因此從盤點端就看不到。改成腳本也算（標「（腳本）」），測試檔仍不算。用新版掃 Stock-web：5 個超過 800 行，全是腳本（exitStrategy.ts 6,588、register.tsx 866、weeklyGoliveCore.ts 839、histRetest.ts 832、simRulesSnapshot.ts 812）。既有專案下次重跑盤點才會出現。
- **行數上限自動提醒**（使用者：「行數閘門範圍…這個功能現在有了嗎?開新對話或壓縮對話會自動跑嗎?」——查證：沒有，0.12.0 只是 cds-modularize 裡的文字，只有跑重整時才讀到）：健康檢查 hook（新對話每天一次、壓縮後每次）讀盤點索引，超過上限又不在例外清單的檔提醒排進待辦拆檔（拆檔本身要使用者同意）；索引是舊版（version < 2，沒算腳本）就要求重跑盤點。例外清單唯一來源：專案 `.claude/dispatch-config.json` 的 `projectAutomation.bigFileExceptions`（檔案→原因，原因空白不算）；cds-modularize 同步寫明。project-scan 索引 version 1→2。
- 測試：test_tools 的 ProjectScan 加 scripts/backtest/exitStrategy.ts 1,000 行必須列為 big-file。；test_hooks 加舊版索引／例外清單情境。

## 0.13.0（2026-11-04）

使用者：「我在 Stock-web 開新對話並叫他根據全域規則去做優化，只是第一次對話時他沒有像你說的會主動提出，要我詢問後才會，為什麼?」。查證（Stock-web 對話 e29ffd20）：新對話 2026-11-03 23:30 開始，0.12.0 hook 23:47 才裝上，當時健康檢查還不存在；而且 Stock-web 已有 CLAUDE.md 與盤點索引，走「③已有索引」分支，hook 本來就什麼都不注入，只靠 Claude 記得規則——它只回答了使用者問的進度，使用者再問「你看看全域規則與設定，有沒有這個專案要做的優化?」才列出 7 項。

- **全域系統對照（UserPromptSubmit，新）**：已有 CLAUDE.md 的專案，全域系統主.次版號跟這個資料夾上次對照不同（或從沒對照過）→ 第一則提示注入【全域系統對照（hook）】，要 Claude 答完原問題後主動列出專案要配合的優化（規則矛盾、門檻超標、新能力未接），只改文件／設定的直接做。修訂號不觸發；同一則已在跑 init／audit 就只記錄。`projectAutomation.alignOnUpdate` 可關。CHANGELOG 改為安裝到 `~/.claude/claude-dev-system/CHANGELOG.md` 供對照。
- **交接紀錄加 KB 上限 `progressMaxKB`（預設 100）**：Stock-web PROGRESS.md 510 行卻 355 KB，只看 600 行抓不到。這條是 Stock-web 那場直接改在安裝副本 `~/.claude/claude-dev-system/hooks/usage_guard.py`，沒進 repo——update 會把改過的檔當使用者改動保留、新版只存 .new，之後 hook 更新全部裝不上；本版移進 repo 並加測試。
- **core.md**：要改全域系統本身改 repo 再 update，不直接改安裝副本（同上原因）。
- **健康檢查改成每場對話每天一次**（原本每資料夾每天一次）：舊的長對話當天先用掉，同一天新開的對話就收不到。
- **跨對話的定期工作不放 CronCreate**（core.md 巡檢條＋web-sources 第 11 節）：Stock-web 換新對話後上一場排的 11/4 檢查與評測全部消失；CronCreate 工具說明「Jobs live only in this Claude session」「Recurring tasks auto-expire after 7 days」。不需 AI 判斷的改用作業系統排程器跑腳本、結果寫檔、開工讀檔（Stock-web scripts/scheduled/daily-verify.ps1 的做法）。
- 測試：test_hooks 新增 progress KB／分對話、全域對照 7 個情境；test_installer 的 CRLF 模擬 checkout 補 CHANGELOG。

## 0.12.0（2026-11-03）

使用者：「在 Stock-web 專案執行時，發現好像會有遺漏一些全域優化設定的規則」。查證：Stock-web 同一場對話從 2026-10-15 開到 11-03（紀錄 157 MB、壓縮 20 次）；開工檢查只在新對話做，之後 11/1 盤點後改過 205 檔、新增 193 檔沒重跑盤點，CLAUDE.md 25 KB 超過專案自訂 20 KB 上限，當天全域 skill 0 次、上網 6 次沒讀速查檔。使用者：「1~7 項全部都照你建議的改」。

- **壓縮後重新開工（SessionStart hook，compact／resume）**：官方 hooks 文件「Use a SessionStart hook with a compact matcher to re-inject critical context after every compaction」。注入開工清單（讀交接紀錄最後一節與專案關鍵規則、`--check`、上網先重讀 web-quick、波及範圍與派工 skill）＋健康檢查＋專案自動化。
- **專案健康檢查（UserPromptSubmit 每資料夾每天一次；壓縮後每次）**：盤點索引之後改過 > 20 檔 → 重跑盤點；CLAUDE.md > 180 行或 > 20 KB（任一；Stock-web 不到 180 行但 25 KB）、交接紀錄 > 600 行 → `cds-doc-governance` 瘦身。門檻在 dispatch-config `projectAutomation`，專案可覆寫、設 0 關閉。
- **壓縮滿 3 次（及倍數）建議開新對話**：先更新交接紀錄再換；只建議不停工。
- **core.md 新增兩條（Stock-web 11/3 核心決策原則 9、10 升全域）**：對話是討論不是命令；不確定就查證。另加「長對話」一條說明上面兩個 hook。
- **cds-modularize**：行數閘門範圍要明確決定，預設涵蓋研究／回測腳本，例外逐檔寫原因（Stock-web scripts/backtest/exitStrategy.ts 6,588 行）。
- **測試不再寫入真實 `~/.claude/state`**：0.11.8 起 test_hooks 把測試問句寫進使用者的 source-guard.log（8 筆「AI 幻覺的原因是什麼？」），改指到暫存資料夾。

## 0.11.16（2026-11-03，最後一次可能需要手動換 exe）

- **exe 更新備援**（使用者：「為什麼這次不能直接從 exe 更新?」→「要」）：exe 正在執行的更新程式碼是打包時固定的，它本身有 bug（0.11.14 在另一台遇到 GitHub 憑證錯誤）就換不掉自己。新增 `installer/selfupdate_exe.py`：「檢查更新」下載到 app/ 的這一份永遠是最新程式碼；exe 自己查 Release 或下載／換檔失敗時，改用系統 Python 執行它來查與換，成功就照常重開視窗。之後更新程式本身的 bug 修好後，舊 exe 也能自己換成新版。
- 限制：備援要有 app/（按過「檢查更新」）與系統 Python；這個機制要先在 exe 裡才會生效，所以 0.11.14 以前的 exe 還要手動換這一次。

## 0.11.15（2026-11-03，視窗會自動換 exe）

- **PowerShell 裝在 D 槽被誤判、重裝失敗 MSI 1603**（另一台截圖；使用者：「有可能是因為我那台電腦安裝在 D 槽」）。根因：環境偵測只認 `C:\Program Files\PowerShell\7\pwsh.exe`，其他位置一律標「非 MSI」並引導重裝；重裝同一版 7.6.9 時 MSI 回 1603。微軟官方列的 1603 第一個原因就是「Windows Installer is attempting to install an app that is already installed」。修法：改看登錄檔解除安裝清單（任何磁碟）＋路徑是否在 WindowsApps（Claude Code 偵測不到的只有 Store／MSIX 版）；非 Store 路徑一律 ✅ 並顯示所在資料夾。
- 安裝失敗時紀錄多一行白話說明（1603、1602、1618、1638、找不到可用的升級）。
- **檢查更新「查不到 Releases：CERTIFICATE_VERIFY_FAILED unable to get issuer certificate」**（另一台截圖；同一台 raw.githubusercontent.com 正常）：Python 不會自己補抓中繼憑證，Windows 的 Schannel 會。憑證錯誤時改用 Windows 內建 curl.exe 重試（仍驗證憑證，只是改用系統的驗證方式），下載 exe 與 sha256 也走同一條。

## 0.11.14（2026-11-02，視窗會自動換 exe）

- 舊 .old.exe 的刪除進度印在紀錄（使用者：「可以顯示說刪完了沒嗎?」）：開窗印「等它完全關閉後自動刪除」、刪掉印「✅ 已刪除舊的視窗程式 …」、90 秒刪不掉印 ⚠️。
- 還沒刪完就關閉視窗會先問（使用者：「還沒刪完時關掉 exe 會跳視窗說明並問是否」）：是＝等刪完自動關（最多 90 秒，刪不掉就提示後關）；否＝直接關（下次開啟再刪）；取消＝回視窗。所有關閉路徑（右上角、套用後關閉、讀取中關閉）都走這個檢查。重試執行緒隨視窗結束，不會留在背景。

## 0.11.13（2026-11-02，視窗會自動換 exe）

- 更新重開後舊的 .old.exe 還留著、要再手動重開一次才消失（使用者實測）。原因：新視窗啟動時只重試 3 秒就放棄，而舊程序關閉要幾秒（Tk 收尾＋PyInstaller 刪自己的暫存夾），檔案還鎖著。改成背景執行緒每秒重試、最多 90 秒，不擋開窗；重開後的提示文字改成「會自動刪掉」。

## 0.11.12（2026-11-02，視窗會自動換 exe）

- 開啟瞬間仍閃一個黑窗（使用者實測 0.11.11）：找系統 Python 的 `py -3` 在模組載入時就跑，早於放在 main() 裡的隱藏補丁。補丁移到載入最前面、第一個子程序之前。

## 0.11.11（2026-11-02，視窗會自動換 exe）

- **開啟變快**（使用者：「exe 開啟時間能再更快嗎?」）。量測（本機）：exe 解壓＋啟動 Python 約 2.5 秒（最小 PyInstaller 視窗程式也要 1.6 秒，這段改不掉）；之後讀狀態 5.5 秒——系統 Python 查 faster-whisper、yt-dlp、youtube-transcript-api 各開一個程序（0.8／1.0／0.9 秒）、pwsh 0.5 秒、claude 等全部依序跑。改法：①視窗先出現（標題「讀取中…」、副標「偵測環境中…」），狀態在背景讀完再畫；②三個套件改一個系統 Python 程序一次查完並快取；③環境偵測（Python、Claude Code、pwsh、套件）與影片套件平行跑。實測本機建置的 exe：`--selfcheck`（同步讀完狀態）8.1～8.8 秒 → 3.6～4.3 秒；開視窗時畫面約 2.5 秒就出現，內容再過 1～1.5 秒填上。原始碼模式 read_state 2.3 秒 → 1.2～1.6 秒。
- **不再閃終端機視窗**（使用者：「不要開 exe 時跳出一堆終端機畫面」）：視窗程式開 console 子程序（py、claude.cmd、pwsh、winget、pip）每個都會閃一個黑窗；現在所有子程序加 CREATE_NO_WINDOW，輸出照常擷取進紀錄。功能不變。
- 狀態還在讀時：按鈕說「稍等（讀取狀態）」、關閉視窗可直接關、開窗自動檢查更新每秒重試最多 20 秒。

## 0.11.10（2026-11-02，視窗會自動換 exe；從 0.11.9 更新上來這一次重開會失敗，關掉錯誤視窗後自己再開一次 exe 即可）

- 視窗內換完 exe 自動重開時跳「Failed to execute script 'gui'… Can't find a usable init.tcl in {…\_MEIxxxx…}」與「Failed to remove temporary directory」（使用者截圖）。根因：PyInstaller onefile 的子程序繼承父程序環境時被 bootloader 當成同一個應用的 worker，直接用父程序的 _MEI 暫存資料夾，父程序一關就把它刪了。修法照官方文件：重開時設 `PYINSTALLER_RESET_ENVIRONMENT=1`（並拿掉繼承的 TCL_LIBRARY／TK_LIBRARY），新程序自己解壓成獨立頂層程序。
- 這個 bug 在「正在執行的舊 exe」裡，所以 0.11.9 → 0.11.10 這一次更新還是會在重開那步失敗一次（exe 本身已換好，雙擊重開就是新版）；之後的更新就正常。

## 0.11.9（2026-11-02，視窗會自動換 exe）

- 多台 Chrome 自動選本機那台改成**全域規則**（`core.md` 教操作條、`web-quick.md` A 段），不只測試題：任何專案對話要開網頁時，帳號連著多台 Chrome 就自己選 `onThisComputer` 為 true 的那台（沒有就 `isLocal`），不問；只有兩台都在本機才問。使用者 11/2：「之後在任何 claude code 專案對話都會全域優先使用當前的裝置的 chrome，不會再詢問了嗎?」
- PowerShell 環境列的提示改成可判定：非 MSI 路徑時先在 Claude Code 對話用 PowerShell 工具跑 `$PSVersionTable.PSVersion`，7.x 就不用裝、5.1 才按安裝 MSI 版。使用者 11/2：「PowerShell 已經有安裝過的，還要再安裝嗎?」——Store 版有時 Claude Code 偵測得到，不必一律重裝。

## 0.11.8（2026-11-02，視窗會自動換 exe）

- **查證守門 hook（Stop 事件）**：另一台裝置的 Claude 自評全域規則時指出「規則只是指示，判定這題不算查證型就整段跳過」（實例：講幻覺原理順手寫「2024 年 Google 披薩加膠水」「OpenAI 2025 論文」卻沒附來源），並建議三件事——觸發改看內容不看題型、先查前提、加 Stop hook 做機械檢查。三件都做：`core.md`／`web-quick.md` 加「回答裡要寫到年份、數字、人名、事件、法條、版本號就是查證型」「問題隱含的前提先確認」；`usage_guard.py` 多掛 Stop：問句、回答 ≥200 字、含年份或帶單位數字、沒有來源字樣 → `block` 一次要它補（`stop_hook_active` 時不再擋；含程式碼區塊不擋；末尾寫「〔不含待查證事實〕」可放行）。視窗核心區多一個「查證守門 hook」勾選（local.json `sourceGuard`），匯出／匯入設定含它。
- PowerShell 7 安裝鈕加 `--force`：另一台已有 Store／MSIX 版 pwsh 7.6.9，winget 把 install 當 upgrade 回「找不到可用的升級」（結束碼 2316632107＝0x8A15002B）不裝 MSI。官方文件：`--force`＝「Direct run the command and continue with non security related issues」。
- Chrome 實際連線測試：帳號連著兩台瀏覽器時無頭模式沒有 AskUserQuestion，模型停下來「請你選」→ 測試失敗（另一台截圖）。提示改成「多台就自己用 select_browser 選第一台」，允許清單加 list_connected_browsers／select_browser／switch_browser；自我測試 chrome 題同。
- 實測（本機 `claude -p`，有 session 檔）：叫它「憑記憶答台北 101、不要寫來源段」→ hook 擋一次（state/source-guard.log：含 8 個年份、6 個帶單位數字），第二輪它說明使用者明確要求不附來源、也不誤標〔不含待查證事實〕，合理。注意 `--no-session-persistence` 沒有逐字稿檔，hook 看不到回覆就不擋（自我測試與 Chrome 實測都是這種模式，不受影響）。
- 多瀏覽器改選本機：`list_connected_browsers` 每台有 `onThisComputer`（正在或剛在這台電腦上跑）與 `isLocal`（OS 相同，弱線索），提示改成照這順序自己選，不是第一台。
- Stock-web 11/2 對全域系統的調整已確認：用量門檻、並行、巡檢改讀全域 dispatch-config，專案副本已刪；全域這邊不用改。

## 0.11.7（2026-11-01，需換新 exe——最後一次手動換）

- 視窗「檢查更新」改成一鍵全更新（使用者：「希望之後不用再下載新的 exe，檢查更新的同時就把所有更新包括 exe 本身都更新」）：按「是」→ 下載規則／工具 → 直接套用到 Claude Code（只做「更新」一項，勾選不動）→ 查 GitHub 最新 Release，exe tag 比執行中的新就下載、核對大小與 `.sha256`、把執行中的 exe 改名成 `.old.exe`、新檔改成原名、自動重開視窗（帶 `--after-update`），下次啟動刪 `.old`。規則版本一樣但 exe 舊也會問。Release 工作流程多附 `claude-dev-system-settings.exe.sha256`。
- 換不成（下載失敗、sha 不符、改名失敗）一律保留原 exe 並印 ❌；原始碼模式不碰 exe。
- 測試：`test_appdir` 加 Release 查詢、下載驗證（大小、sha 不符要拒）、改名換檔與還原、清 .old。視窗流程本身（tkinter）沒有自動測試，靠下一次真實更新驗證。

## 0.11.6（2026-11-01，需換新 exe）

- 視窗「檢查更新」找到新版、按「是」卻不下載（使用者截圖：紀錄只印三次「有新版 v0.11.4 → v0.11.5」，並跳出「『檢查更新』還在執行」）。根因：詢問框在「檢查更新」工作的 done 訊息處理之前就跳出，按「是」派下載時 busy 仍是 True，被擋掉。改成把要問的版本存起來，等 done 處理完、busy 解除後才問；按「否」也會印一行；下載完印「已下載到 …；接著按套用」。
- 這個 bug 只影響視窗內更新流程；本機已安裝版本不受影響（它是由安裝器直接更新的）。

## 0.11.5（2026-11-01）

- `cds-modularize`：寫進 Stock-web 第一次真實分階段重整（M1～M8，17 個 800 行以上大檔清零、vitest 5,622 全過）實際有效的做法——B 階段比對腳本要有突變測試（故意改壞約 10 處全要被抓到）且基準摘要先 commit；C 階段拆大檔預設「原檔只留 re-export」；新增「平行」段（使用者允許時每模組一個 worktree＋`refactor/<模組>` 分支，合併後主目錄重跑全部，合併完立刻 remove＋prune，Windows junction 從 PowerShell 刪）；E 階段閘門加單檔行數上限並要求問題清單補「處理結果」表。來源：使用者「Stock-web 分階段重整全部完成了，你去看看」；實地看到 8 個空的 sw-* 資料夾（worktree 已 prune 但 Bash rm 沒刪乾淨）。

## 0.11.4（2026-11-01，需換新 exe）

- 視窗「有工作正在執行」改成寫出是哪個工作（例如「開窗自動檢查更新」）與為什麼一次只跑一個（套用、檢查、更新、測試都寫同一份設定檔）。來源：使用者截圖「有工作在執行中不能更新嗎？」。

## 0.11.3（2026-11-01）

- `project-scan.py`：資源檔（圖片、影片、PDF、字型）只計數，不逐檔雜湊、不進索引；`--check` 對舊索引裡的資源項目也忽略。來源：使用者的「資料壓縮」課程資料夾（11 支 Python 腳本＋3,170 張影片截圖）被 hook 判為專案並自動立規矩——規矩本身寫得合理（算式單一來源、排版程式只能呼叫不可重算、原始資料只讀），但索引 720 KB、每次開工 `--check` 都要重算三千多張圖的雜湊。修後索引只剩 30 個檔左右。
- 判定「算專案」的門檻沒改：11 支會互相 import 的 Python 腳本確實是一個小專案，立規矩對它有幫助；真正不想要的資料夾可在該資料夾放 `.claude/dispatch-config.json` 把 `projectAutomation.autoInit` 設 false。

## 0.11.2（2026-11-01，需換新 exe）

- 視窗頂端改兩列：第一列「來源／已安裝」與按鈕，第二列「設定目錄」與「來源比已安裝舊」提醒。原本全擠一列，提醒一長右邊的按鈕就被擠出畫面（使用者截圖）。以實際開窗截圖核對。按鈕與對話框文字改「全部 11 題」。

## 0.11.1（2026-11-01）

- **專案自動化改由 hook 判定並注入**。實測：Meeting-Assistant（有 CLAUDE.md、54 檔、無索引）自動盤點成功；QTranslate（無 CLAUDE.md、14 檔、git）使用者問「現在該專案狀況如何？」，Claude 直接讀交接紀錄回答，完全沒做 init；無頭重現同樣跳過（4 次呼叫全是 git 與讀紀錄）。結論：寫在 core.md 的「開工先判定」靠 Claude 自覺會漏，改成 `usage_guard.py` 在 UserPromptSubmit 時自己判定（沒有 CLAUDE.md 且算專案 → 注入「先跑 cds-project-init」；有 CLAUDE.md 沒索引 → 注入「先跑 cds-project-audit」），同一場對話同一資料夾只注入一次，claude-dev-system 自己、家目錄、磁碟根目錄不做，計檔最多 3,000 個或 0.5 秒。有測試（init／audit／有索引／小資料夾／專案設定覆寫／去重）。
- 從 Meeting-Assistant 實跑學到：閘門測試在沒裝這套系統的電腦（公開 repo、CI）要 skip 不 fail；audit 沒有交接紀錄檔時要建 PROGRESS.md。寫回兩個 skill。
- 驗證：自我測試第 11 題「init-status」重現 QTranslate 情境（播種 12 個 Python 檔＋`docs/交接紀錄.md`，只問「現在該專案狀況如何？」）。裝 hook 前同樣的問法無頭重現 4 次呼叫全是讀紀錄、沒做 init；裝 hook 後 12 次呼叫：先 project-scan、寫 CLAUDE.md 與 PROGRESS.md、裝閘門，再依交接紀錄回答狀況並提到 Bing 待辦，1/1 ✅。
- 只改 hook、規則、skill：視窗「檢查更新」拿得到，不用換 exe。

## 0.11.0（2026-11-01，需換新 exe）

- **專案自動化**（使用者：「exe 執行並套用後全部會自動化全部完成，每個專案也不需要我特地說」）：三個新 skill——`cds-project-init`（新專案自動立規矩：專案 CLAUDE.md、盤點、依賴閘門、PROGRESS.md）、`cds-project-audit`（舊專案自動盤點：盤點清單、架構與資料流、九欄位問題清單；達門檻只問一次要不要重整，答案記進索引）、`cds-modularize`（A 基準→B 保護→C 逐模組→D 整合→E 驗收，刪前七項確認，閘門收尾）。core.md 加「專案自動化」與「什麼時候問使用者」兩條可判定規則；`dispatch-config.json` 加 `projectAutomation`（autoInit／autoAudit／autoRefactor／minSourceFiles），視窗核心區可改。
- 新工具 `tools/project-scan.py`（標準庫）：檔案分類統計、入口、最大檔、Python 與 JS／TS 依賴圖與循環、被引用最多的模組、問題清單；`.claude/project-scan.json` 存每檔雜湊，`--check` 列出改過的檔（索引過期就重驗），`--summary` 一行判定「算不算專案」。有測試；對 claude-dev-system、QTranslate、Meeting-Assistant 各跑過 `--summary`（23／14／54 個原始碼檔，都判「算專案」）。
- 紀錄細節：`cds-session-pickup` 定 PROGRESS.md 固定格式（四段＋「決策：日期｜決定｜原因｜證據」當下就寫）、開工先 `--check`。
- 自我測試第 10 題「init」：在播種 12 個 Python 檔（含循環）的空專案裡只說「看一下結構」，驗 Claude 會不會自己跑 project-scan 並寫 CLAUDE.md；selftest 每題改用獨立子目錄、支援 `seed`。視窗按鈕改「自我測試（快測 3 題／全部 10 題）」；開窗若超過 30 天沒跑自我測試，紀錄區提醒一行。
- 做不到、明說的：同一場對話聊太長的失憶（Claude Code context 上限）、外部服務壞掉（靠快測發現）、花大額度的重整決定（問一次）。

## 0.10.13（2026-11-01，需換新 exe）

- 自我測試跑完自動清暫存：每題的工作目錄本來就是 TemporaryDirectory；現在連 Claude Code 替那個目錄建的 `%LOCALAPPDATA%/Temp/claude/<slug>`（Claude 寫的腳本、截圖都在那，之前要我手動刪）也一起刪，只刪 slug 含 `cds-selftest-` 的；報告 `state/selftest-reports/` 只留最近 10 份；紀錄最後印一行說清了什麼。影片快取維持 video.py 的 7／30 天自動清。來源：使用者「跑自我測試按鈕產生的文件與檔案跑完後也會自動刪除嗎」。

## 0.10.12（2026-11-01，需換新 exe）

- 修 exe 按「檢查（verify）」的兩個假失敗（使用者貼的輸出）：①「檔案雜湊與 repo 不一致」8 個檔——本機安裝的檔案是 CRLF、CI 打包進 exe 的快照是 LF，內容相同只差換行；payload 現在一律正規化成 LF 再比對與寫入（有測試：CRLF checkout 與 LF checkout 的 payload 逐位元組相同），下次 update 會把那 8 個檔重寫成 LF。②「影片套件 yt-dlp／youtube-transcript-api 未安裝」——exe 模式的 verify 用 exe 內建的 Python 檢查套件；改問系統 Python（環境區早已這樣做，verify 路徑漏了）。

## 0.10.11（2026-11-01，需換新 exe）

- 修視窗：用 v0.10.4 的 exe 開已從原始碼更新到 0.10.10 的機器，「檢查更新」看到新版但沒下載就按套用，視窗提「更新 0.10.10 → 0.10.4」，安裝器拒絕降版，紀錄說「見 ❌」卻沒有 ❌ 行。三處修：①來源比已安裝舊時不再提「更新」，標題列顯示「⚠️ 來源比已安裝舊，按檢查更新再套用」；②這種情況下套用不跑會拒絕的 install/update，金鑰、MCP 開關、影片開關改走 web／video 子命令，門檻等照常，已安裝版本不會被降；③安裝器回傳失敗但沒有標記時，最後一行補 ❌。有測試。來源：使用者截圖「但我沒看到叉叉」。
- 這是安裝器程式碼的變更，exe 要換新（Release v0.10.11）；只用原始碼的人 `git pull` 即可。

## 0.10.10（2026-11-01）

- `cds-verify-app` 第一次在真專案（Stock-web）實跑：生成 `verify-stock-web`（14 個功能、41 項檢查，附功能↔檔案地圖），本機 41/41、正式站 40/40 通過。第一遍抓到 skill 生成物三個錯並修好：清理只停背景任務沒關 next 本體（改依 PID 關）、用 netstat 判斷埠會誤判（改 curl 實連）、地圖有一個不存在的路徑。這三條寫回 skill 的 ⑤ 清理與補充；另加第 7 條「正式站只做唯讀檢查，免登入唯讀通道必須只讀＋秘密 token＋正式站預設關閉」。來源：使用者貼的 Stock-web 回報。

## 0.10.9（2026-11-01）

- **撤回 0.10.8**。重做 A/B（同一分鐘內連續跑）：`CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH` 設 4096、1024、256 的開場 context 分別是 59,908、59,910、59,912，沒有任何 MCP 是 42,250——這個變數對本機這 14 個伺服器**完全沒有效果**。0.10.8 的 43,222 是在 MCP 伺服器集體斷線重連的那幾分鐘量到的（本對話當時有「MCP server disconnected」事件），不是變數的功勞；當時只量一次就下結論、且設 2048 沒差的訊號被我忽略，是量測方法的錯。env 預設、視窗說明、規則與文件裡的相關敘述全部移除；撤回時發現 `update` 不會拿掉本工具以前寫、新版不再要的 env 鍵（只會加不會減）→ 修：`apply_env` 對登記過但不在新清單的鍵刪除，使用者自己的鍵不動（有測試）。
- 仍然成立的數字：7 個免金鑰 MCP 約 +10,300、5 個 `-key` 雙註冊約 +9,400（兩者都用 `--strict-mcp-config` 控制清單量的，可重現）。要省只有三條路：單一註冊（視窗選「一律用金鑰」或「只用免金鑰」）、少呼叫（多 API 一支腳本，已入規則）、短回答（查證過程 ≤3 行，已入規則）。

## 0.10.8（2026-11-01）

- **最大的可控用量找到了，而且不用放棄免費優先**：Claude Code 官方文件（code.claude.com/docs/en/mcp「Change the description length limits」、env-vars）有 `CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH`（v2.1.280 起），控制送給模型的 MCP 伺服器說明與工具描述字數（預設 4,096／16,384）。同一句「只回答 OK」實測：14 個 MCP 預設 61,946 token、設 2048 仍 62,624（說明都在 2,048 內）、設 **1024 → 43,222**，比沒有任何 MCP（42,173）只多 1,000；`CLAUDE_CODE_SIMPLE_SYSTEM_PROMPT=1` 沒差（62,718）。安裝器 env 預設寫 1024，視窗聯網區可改。三題實測（設 1024 跑 parking／docs／live-data）3/3 ✅，工具選擇與沒設時相同（TDX 腳本→parallel→exa；context7→deepwiki；三個 API 一支腳本），三題回答都有「來源」與「查證過程」段。token 合計：parking 1,074,585（15 次呼叫）、live-data 548,969（7 次，0.10.7 的「多 API 一支腳本」規則讓呼叫從 13 次降到 7 次、總量從 730,128 降到 548,969）、docs 333,300（5 次）。
- 使用者問「讓它們引用同一段不要重複」：Claude Code 是每個連上的伺服器各自注入一段說明，沒有合併或共用的設定，做不到去重；這個變數是把每段截短，效果比去重還大。來源：使用者「既然是重複的，讓他們引用同一段不要重複的話呢？」

## 0.10.7（2026-11-01）

- 金鑰模式加第三種 `free`（只用免金鑰：金鑰留在 local.json 但只註冊免金鑰版），視窗選單「免費優先／一律用金鑰／只用免金鑰」，預設仍是免費優先；說明列註明每多一個金鑰版伺服器每次工具呼叫約多讀 1,900 token。`--key-mode 名稱=free`。來源：使用者「加一個只用免金鑰可做，但免費優先與一律用金鑰都要保留，預設一樣為免費優先」。
- 規則（可判定）：同一題要打 2 個以上 API 就寫一支腳本一次打完（快測 13 次呼叫有 6 次是分開打）；「查證過程」段最多 3 行（來源清單不限）。來源：使用者「2、3 可做」。

## 0.10.6（2026-11-01）

- 自我測試：每題記錄 result 事件的真實 token（輸入／輸出／快取建立／快取讀取與合計）並印出，報告存 `usage`；查證型題目加 `answer_expect`（回答必須含「來源」與網址）、`answer_warn`（缺「查證過程」只標 ⚠️），影片題要含 `[mm:ss]` 時間戳，Chrome 題要含 Example Domain；`--smoke`／視窗「是＝快測 3 題」只跑 pwsh、live-data、video。來源：使用者「值得做的 1、2、3 都可以做」。
- 用量守門 hook 的 PostToolUse matcher 由 `*` 縮為 `Bash|PowerShell|Agent|Task|Edit|Write|NotebookEdit|Workflow`：實測每次觸發啟動 Python 約 120 ms，Read／Grep／Glob 不再觸發；用量檢查本來就有 5 分鐘 TTL。`update` 會自動換成新 matcher。
- 視窗開啟 1.5 秒後安靜檢查一次 GitHub 版本：有新版才跳問、已是最新或連不上只在紀錄寫一行。`~/.claude.json` 的備份（Chrome 開關每按一次存一份）改為只留最近 10 份。
- core.md 的「上網查資料」「影片」兩條再精簡（細則已在 web-quick.md），core.md 由 3,310 字減到 2,886 字。progress-diff 對舊 core.md 報 18 句找不到，逐句核對都是 0.10.0 寫的「觸發句改寫」（例如「數據用 stats／comments」「直播 --live 秒數」），原始規則原文仍在 web-quick.md 的 A、C 段，沒有內容遺失。
- 快測三題實跑（0.10.6 規則）3/3 ✅，首次有真實 token 數：pwsh 合計 306,567（快取讀 253,410）、video 458,283（快取讀 431,740）、live-data 730,128（快取讀 685,994）。可見一場短查證的用量幾乎全是「每次工具呼叫重讀整個開場 context（約 5～6 萬）」的快取讀取，工具呼叫次數才是用量的槓桿，規則檔字數不是。回答格式檢查抓到兩題都缺「查證過程」段（⚠️）→ core.md 與 web-quick.md 補明「回覆末尾固定來源與查證過程兩段」。
- 開場 context 拆解實測（同一句「只回答 OK」，`--strict-mcp-config` 控制 MCP 清單）：沒有任何 MCP 42,173 token；7 個免金鑰 MCP 52,511（+10,338）；加上 5 個 `-key` 雙註冊共 14 個 61,946（再 +9,435）。MCP 的成本不是工具 schema（延後載入）而是每個伺服器附帶的說明文字，`-key` 版把同一段說明再算一次；這筆每次工具呼叫都重讀，13 次呼叫就是約 12 萬。這是目前最大的可控用量來源，處理方式待使用者決定（雙註冊是使用者選的免費優先設計）。
- 使用者全域 CLAUDE.md 開頭的舊「本機影片（mp4）處理 → video-pipeline.md」段已移除（video.py 取代；改前備份到 `~/.claude/backups/…-CLAUDE-before-remove-videonote.md`）。來源：使用者「5 你也幫我做」。

## 0.10.5（2026-11-01）

- 速查拆成小檔 `rules/web-quick.md`（約 6,100 字：上網、即時數值 API 精簡表、影片、教操作、巡檢指標），core.md 改成「第一次查東西／處理影片前先 Read web-quick.md」；完整版 `web-sources.md` 的三段速查改為指標，細則不動。搬移以 progress-diff 逐句比對（web-sources 539 句、core 全部找得到）；新測試保證小檔每個網址都逐字存在於完整版、小檔不超過 12,000 字。
- **實測結果要老實說**：拆檔前後各跑 pwsh 與 live-data 兩題，Read 規則檔的次數從 1～3 次降到 1 次，但估算用量沒有下降（pwsh 0.55→0.89、live-data 0.59→0.62 美元等值，差異在兩次執行的雜訊內）。原因是拆檔前 Claude 已經先 Grep 標題再用 offset 讀片段，不是整檔讀，所以「每題省一萬多 token」的預估沒有兌現。保留拆檔是因為它讓讀規則變成固定一次、行為更可預測，不是因為省用量。來源：使用者「做第一項就好」。
- 拆檔過程兩次切錯邊界（第一次把第 1 節細則整段搬走、第二次把第 9 節導言弄丟），都靠 progress-diff 與 URL 一致性測試抓到並修回；最終版兩個檔合計與舊版逐句相同。

## 0.10.4（2026-11-01）

- 0.10.x 規則瘦身後的九題自我測試實跑（全新無頭對話）：7/9 先過，parking 與 live-data 判 ❌——但看報告 Claude 其實都做對了（parking：先 Read web-sources.md 速查 → 寫腳本查 TDX → parallel → exa → 抓林班道官網與 Wayback，結論「官網寫 290 位、型式未能確認」；live-data：寫一支腳本打環境部 aqx_p_432（汐止 AQI 60）、氣象署 F-D0047-069（板橋明天各時段降雨機率）、open.er-api（1 TWD≈4.83 JPY），未用 firecrawl）。誤判原因是 selftest 把工具參數截成 300 字再比對，Write 的腳本內容在 300 字之後。修：比對用全文（上限 2 萬字）、報告與顯示才截短；有測試。修後重跑這兩題 2/2 ✅，九題合計 9/9。
- 這次實跑也證明瘦身後的 core.md 有效：九題裡每題開頭都先 Read 了 `web-sources.md`（速查規則），工具選擇與 0.9.x 一致。

## 0.10.3（2026-11-01）

- CI 第三修：smoke test 用 `& exe` 呼叫視窗程式不會等它結束、`$LASTEXITCODE` 是空值（空值 -ne 0 為真）→ 改 `Start-Process -Wait -PassThru` 看 `ExitCode`；`--selfcheck` 出錯時把 traceback 寫進輸出檔（視窗程式沒有主控台）。本機 exe 的 selfcheck 一直是通過的。

## 0.10.2（2026-11-01）

- CI 再修：GitHub Actions 的 Windows runner 主控台是 cp1252，`build_exe.py` 最後印「產物：…」的中文炸 UnicodeEncodeError（exe 其實已打好）→ stdout 改 UTF-8、workflow 加 `PYTHONUTF8=1`。v0.10.1 標籤同樣沒有 Release。

## 0.10.1（2026-11-01）

- CI 修正：GitHub Actions 的 runner 沒有 `claude` 指令，`chrome_live_test` 的單元測試在 CI 失敗（本機都過）→ 函式可注入 `which`，測試用假值；v0.10.0 的 Release 因此沒建成，改以 v0.10.1 發第一個 exe。環境列的 ffmpeg 只顯示最後兩層路徑，不再撐出視窗。
- 已知：v0.10.0 標籤留在 GitHub 上但沒有 Release（workflow 失敗），可自行刪除。

## 0.10.0（2026-11-01）

- **core.md 瘦身**：「上網查資料」「影片」兩條超長規則改成觸發條件＋「第一次用前先 Read 細則速查」，原文逐句搬進 `web-sources.md` 的 1-0、9-0、10-0 速查與新的第 11 節（背景任務巡檢）；`progress-diff.py` 逐句比對 77 句全部找得到。core.md 由 4,606 字減到約 3,300 字。**實測 token**：同一句「只回答 OK」的無頭對話，瘦身前 cache 建立＋讀取合計 63,372 token，瘦身後 63,526（多了 3 個 skill 描述），差異在雜訊內——全域 CLAUDE.md 只佔整個開場 context 的一小部分（系統提示與工具 schema 約 6 萬 token 是大頭），瘦身的實際收益是規則更短更可讀，不是省用量；先前「常駐用量可減四成」的估計是用 `wc -m` 把位元組當字數算錯了，在此更正。
- **新增 3 個 skill（借鏡 pstack，不裝外掛）**：`cds-blast-radius`（改到 ≥3 處引用的符號時列波及範圍並實跑一處）、`cds-verify-app`（替有畫面的專案生成「啟動／健康檢查／功能走法／證據／清理」五段的專案驗證 skill，附功能↔檔案地圖，改動只驗命中的功能）、`cds-session-pickup`（開工讀交接紀錄或從 git 重建，收尾依可判定條件決定要不要建 PROGRESS.md）。core.md 對應條文加了觸發句；「新增優先於改核心」補「先減再加」。來源：使用者「照你說的這些全部都做完」「沒有 PROGRESS.md 的專案怎麼套用」。
- **執行檔（階段 3）**：`installer/build_exe.py` 用 PyInstaller 把設定視窗打成單檔 `claude-dev-system-settings.exe`（內含規則／工具／skill 快照）；`installer/cds/appdir.py` 負責「檢查更新」：比對 GitHub master 的 `config/VERSION`，下載 zip 只取需要的資料夾、原子換掉 `~/.claude/claude-dev-system/app/`，之後視窗以 app/ 為來源套用；安裝器程式碼有變時提示換新 exe。exe 模式下 hook／pip／影片工具改用系統 Python（`py` 啟動器優先，排除商店的假 python.exe），找不到就擋住套用並給下載按鈕。`gui.py --selfcheck 檔` 不開視窗輸出狀態 JSON，供 exe 冒煙測試。`.github/workflows/release.yml`：推 `v*` 標籤自動打包並附在 Release。SmartScreen 會擋未簽章 exe，README 寫了「其他資訊 → 仍要執行」。
- RAG 不做（決策：個人規模專案用 Grep／Glob＋交接紀錄即可，索引要維護、收益小）；看板不做（使用者：「看板這部分我覺得不用做了」）。

## 0.9.6（2026-11-01）

- `install.py selftest`／視窗「自我測試」：用全新無頭 `claude -p` 重跑 `config/selftest.json` 的九題（TDX 停車場、mslearn、video.py 逐字稿、環境部／氣象署／匯率 API、context7／deepwiki、YouTube Data API＋frames、OpenAQ、Gemini ask、Claude in Chrome），讀 stream-json 的 tool_use 比對「該用的工具有沒有用、不該用的有沒有出現」，逐題 ✅／❌、可 `--only` 挑題、`--report-dir` 存呼叫清單。只手動觸發（約九場短對話用量）。
- 視窗核心區顯示目前用量（5 小時／7 天 %、重置時間、讀取時間，來源 `state/usage.json`），「重新讀取用量」按鈕跑一次 `usage_guard.py --print`。
- 每把金鑰多一欄「帳號備註」（存 local.json `keyNotes`，匯出設定一律帶、不算機密）；金鑰測試紀錄會註明帳號。來源：使用者「金鑰測試註明是哪個帳號是每個金鑰都會套用對吧，不只 Gemini」。
- `update` 不再對 `dispatch-config.json`（使用者本來就可改的設定檔）生 `.new` 副本，並清掉舊版留下的 `dispatch-config.json.new`；CLAUDE.md 區塊等其他檔的 `.new` 行為不變。
- 規則：Chrome 重型頁面（Google Cloud 控制台、TDX、各家儀表板）截圖連續失敗 2 次就改 `find`／`get_page_text` 讀文字，不再截圖（2026-11-01 核對額度時三站各卡 3 次以上才改）。
- 視窗版面修正（使用者截圖回饋「文字排版現在又亂了」）：金鑰表每把金鑰改兩列，說明文字獨占第二列整寬，不再塞在最右窄欄被擠成一字一行；「自我測試」按鈕移到視窗頂端與「檢查（verify）」並排（使用者：「跟用量比較沒關，放在比較相關的地方」）；帳號備註欄標題改「自己填」（12 把金鑰的測試端點都不回傳帳號，無法自動填）。改完以實際開窗截圖核對。
- 視窗版面再修（使用者截圖「這部分的排版現在還是有點亂…每個地方分隔在明顯一點」）：聯網區每個 MCP 改兩列（名稱＋功能、狀態＋工具），env 列獨立格線不再把 MCP 欄撐開，工具名不再從中間斷行；每區上方加分隔線、標題改藍色粗體 12 號、區內留白加大；環境列長路徑換行寬跟著視窗。改完以實際開窗截圖核對。
- 視窗「將變更」區改成淡黃底框：標題一行寫「共 N 項」，每項變更各占一行編號列出（超過 6 行在框內捲）；每一區標題加總數（環境 ✅⚠️❌ 各幾項、MCP 幾個開幾個、套件幾/幾、金鑰幾把已設定幾把、Chrome 幾項通過）。來源：使用者「每項變更都換一行…將變更那區塊也改顏色…每塊都再新增寫上共幾個」。以實際開窗、模擬 12 項變更截圖核對。
- 修視窗「③ 實際連線測試」失敗：原本叫 Claude 開 about:blank 截圖，擴充功能拒絕「Can't interact with browser-internal or unparseable URLs」；改開 https://example.com 讀標題後關分頁，並明給 --allowedTools。來源：使用者「我剛剛按實際連線測試發現測試失敗，但你用是可以的」。
- selftest 加 `--dry-run`（只印每題會執行的完整指令，零用量），並核對過本機 claude 的旗標（--chrome／--no-chrome／--allowedTools／--max-turns／--output-format stream-json／--verbose／--no-session-persistence 都存在）；另用一題最小真實無頭對話驗證 stream-json 解析與判定。來源：使用者「有辦法不測試但確認沒有像剛剛的實際連線測試一樣有問題嗎」。
- 整體自審（使用者「你再整體全部確認有沒有甚麼漏洞、bug、疏忽、邏輯」）修了五處：①selftest 報告與視窗紀錄會把 local.json 的金鑰值遮成 ***（Bash 指令或 Write 腳本內容常直接帶金鑰）；②selftest 摘要納入 Write／Edit 的內容，題目的 expect 允許 Write（Claude 先寫腳本再執行時原本會誤判 ❌）；③firecrawl 從 forbid 改成 warn（規則允許它當退路，清單看不出順序，只標 ⚠️）；④update 對使用者改過的 dispatch-config.json 會補上新版新增的頂層鍵（值不動），verify 對它改顯示 ✅「使用者自己的設定值」；⑤selftest.json 進安裝 payload、報告改存 state/selftest-reports，沒有 repo 的機器也能跑。
- 獨立審查（sonnet agent，唯讀）回報高 1、中 13、低 12，逐條查證後修了 22 條、3 條記為已知限制：
  - 高：用量 hook 抓不到用量（離線、權杖過期、端點改版）時沒有退避，每次工具呼叫都重打、最多拖 8 秒 → 失敗也記 `fetched_at`，TTL 內不再試（有測試）。
  - 中：`video.py` YouTube Data API 的 HTTPError 分支永遠進不去（HTTPError 是 URLError 子類、被前一個 except 吃掉），配額用完看到的是 traceback 不是中文提示 → 調換順序；本機 mp4 快取鍵加 mtime＋大小，同路徑換檔不會拿到舊逐字稿；直播錄影逾時接住；Gemini 上傳改串流不整檔進記憶體；視窗 env 欄清空會變成永遠套不掉的假變更 → 清空＝還原預設（有測試）；selftest 權限清單補上五個 `-key` 版 MCP、報告改在暫存資料夾清掉前寫、沒有 expect 的題目判失敗、OpenAQ 題改比對 `api.openaq.org`；金鑰測試與還原備份在忙碌時會卡在「測試中…」或與套用同時寫檔 → 先擋；還原前先把現在的 settings.json 另存 `-before-restore`；匯入設定先全部驗證型別與範圍再套用、別台機器才有的 MCP 名稱略過；關閉視窗時若有工作在跑改為不准關（原本直接砍執行緒會留半套狀態）；規則 2c 的 402 與逾時寫成可判定（`-key` 版也 402／429 → 換索引並提醒；逾時＝單次超過 60 秒），exa 列不再叫人清金鑰。
  - 低：巡檢分鐘預設統一 15（原本兩處寫 10）、舊 plan 格式 fallback 與 hook docstring 統一 85；備份只留最近 10 份；CLAUDE.md 是 CRLF 的檔案整檔不再被轉成 LF、解除安裝後位元組完全還原（有測試）；uninstall 順便刪 state/selftest-reports 並在說明列出殘留；Chrome 預設開關寫檔失敗給明確訊息；tavily 金鑰參數做 URL 編碼、`mask` 也遮編碼後的形式；視窗門檻旁註明「專案有自己的設定檔以專案為準」、金鑰說明註明測試會用掉 1 次搜尋額度；自我測試對話框寫最壞 80 分鐘與無人值守風險；`video.py` 清理說明改「沒更新」。
  - 已知限制不改：金鑰會出現在 `claude mcp add` 命令列與 `~/.claude.json`（Claude Code 的設計）；門檻解析在 hook 與視窗各一份（hook 不能 import 安裝器）；`auto_clean` 每次執行掃整個快取樹。
- 來源：使用者「好，這些優化都可以做」。

## 0.9.5（2026-11-01）

- 用量門檻預設改為 5 小時 85%、7 天 97%（repo 預設、hook 內建預設、視窗預設、README、workflow 規則同步；使用者本機設定 95／99 不變）。來源：使用者「預設從 80／97 改成 85／97（預設改就好，我當前的設定不用改）」。

## 0.9.4（2026-11-01）

- 補測三題（全新無頭 session）：⑦東京空品——OpenAQ v3（資料提供者標環境省そらまめくん）✅；⑨用瀏覽器開 example.com——Claude in Chrome 自己載入、開頁、讀文字、截圖 ✅；⑧影片 25 秒連續動作——**沒用 Gemini**，改每秒截 26 張逐張看、動作只能標推測。規則修正（可判定）：問「連續動作／鏡頭移動／進出哪裡／過程」且有 gemini 金鑰 → 直接 `ask --clip`，截圖只做佐證。
- 另修匯率題的偏差：第 ④ 題跳過 open.er-api 直接 `firecrawl_scrape` 台銀頁。規則加「即時數值不得直接跳 firecrawl 抓頁；匯率先 open.er-api，指定台銀牌告才抓頁且照三步順序」。規則修正後重測：影片動作題改為先 `ask --clip`（Gemini）再以 `frames --at` 13 張佐證，回答逐段標〔Gemini〕／〔截圖〕；匯率題先 open.er-api（JPY 4.830028，附資料時間）→ 台銀 CSV 被擋 → Jina 抓台銀頁，完全照 API→WebFetch→Jina 順序、未用 firecrawl。來源：使用者「這三個都在測」「firecrawl 不是也是免費版沒結果才切嗎」。

## 0.9.3（2026-11-01）

- YouTube 配額頁由使用者在 Google Cloud 控制台（IAM 配額、篩選 per day）實看：Queries per day 10,000、Search Queries per day 100、Video Batch Get Stats 10,000、Video Uploads 100，與官方文件一致。至此 12 把金鑰的額度全部以實際頁面核對。
- 無頭 `claude -p` 全新 session 實測規則是否生效（三題）：①車埕停車場——先寫 Python 帶 TDX 金鑰查，再 parallel → exa → tavily → firecrawl → WebSearch → Agent，符合「TDX 第一步＋跨索引升級鏈」；②PowerShell 編碼——mslearn 兩次＋parallel web_fetch，附 learn.microsoft.com 來源，符合「版本事實必查」；③YouTube 影片——先用 PowerShell 工具跑 `video.py` 被安全檢查擋（`$HOME` expandable strings），改 Bash 又卡在無頭模式沒有權限提示。修：`core.md` 影片條明寫 Windows 用 Bash 工具跑 `py -3 ~/.claude/...`，不用 PowerShell 工具。補測三題（同樣全新無頭 session）：④汐止 AQI／板橋明天雨／日圓匯率——自己寫 Python 打環境部 `aqx_p_432`（汐止 AQI 61）、氣象署 `F-D0047-069`（板橋逐時降雨機率）、匯率用 firecrawl 抓台銀牌告；⑤requests timeout 與 yt-dlp Bilibili extractor 位置——context7 resolve＋query、deepwiki ask_wiki_question；⑥集集線影片觀看數、熱門留言、11:32–12:30 招牌——`video.py stats`／`comments`（YouTube Data API）、`frames --at` 15 張逐一 Read，讀出「水里 謝 肉圓」招牌。六題合計約 4 美元等值用量。未在無頭測試中觸發的：openaq（國外空品）、Gemini `ask`（截圖已足夠時規則不用）、Claude in Chrome（本對話已大量互動使用）。來源：使用者「確定一下安裝完後 Claude Code 是不是都會如你預期地去使用每個工具、MCP、API」。

## 0.9.2（2026-11-01）

- 額度全面以 Chrome 實看或官方頁核對並更正：中央氣象署一般會員 24 小時 2 萬次、每日 2 GB（原誤寫 1,000 次，那是非會員）；環境部會員金鑰每 API 每天 5,000 次；OpenAQ 官方 60 次／分、2,000 次／時；TDX 基礎會員 5 次／分／金鑰、每月 3 點（≈4,500 次；本機帳號「訂閱總覽」實看：基礎會員、本月已用 0.01 點，10 月使用統計 15 次＝0.01 點）；Gemini 正確帳號下仍為 Free tier、3.8 Flash 每天 20 次；Tavily Researcher 方案 19／1,000 credits、Pay as you go 關；Parallel 綁卡後「自動儲值已關閉，餘額降至 0 美元時請求將停止」、餘額 $24.99（$20＋每月 $5）。
- 設定視窗：每個 MCP 列加一句功能說明（`gui_model.MCP_DESC`）、核心與影片區加功能說明（`TOOL_DESC`）、每把金鑰說明附額度；右側留白加大到 56px，說明文字不貼邊。來源：使用者「每個工具、MCP、API 都要寫上功能」「字還是有點被截掉」。

## 0.9.1（2026-11-01）

- Gemini 免費層實際額度（AI Studio Rate Limit 頁 2026-11-01 實看）：3.8 Flash 每天 20 次、每分鐘 5 次（本機帳號已撞滿），3.5 Flash Lite 每天 500 次、每分鐘 15 次。`video.py` 的 429 改為走備用模型（原本直接結束），`video.json` 備用順序改為 3.5 Flash Lite → 2.5 Flash；規則第 9 節補上這些數字與「一題 ask 不超過 3 次」。來源：使用者「剛剛沒檢查到額度的金鑰都開頁面給我…你來查看」。
- 以 Chrome 再核對 Parallel Billing 頁：可見文字為「Add a card to unlock monthly credits. You're only charged when you buy credits.」與兩個 Add Card 按鈕，無任何 auto-recharge／自動加值開關；結論：綁卡本身不扣款、只解鎖每月 $5，主動買額度才收費。

## 0.9.0（2026-11-01）

- **背景任務巡檢**（可開關、可設分鐘數）：規則 `core.md` 新增——派出 Agent／背景 Bash／Monitor／Workflow 後，若 `dispatch-config.json` 的 `taskCheck.enabled`（預設 true、`minutes` 預設 15（使用者指定）），立刻用 Claude Code 的 `CronCreate` 建一個每 N 分鐘的巡檢排程（固定 prompt：列出所有進行中任務、讀最新輸出、結束或出錯立刻處理、全部結束就 `CronDelete`），每場對話只建一個、沒有背景任務不建、巡檢不派新 agent。限制（Claude Code 的 CronCreate）：排程只在閒置時觸發、可能晚最多半個週期、僅存在於該場對話。設定視窗核心區新增勾選框與分鐘數；匯出匯入包含。來源：使用者「可以選擇要不要啟用、自己設定每過多少分鐘 Claude Code 會自動查看當前所有執行任務的狀況…沒有執行的任務時就關閉」。
- 查證：`CronCreate` 工具說明（session-only、「Jobs only fire while the REPL is idle」、遞延最多 50% 週期、7 天到期）。

## 0.8.7（2026-11-01）

- 設定視窗：匯出時可選「含金鑰明文」（檔名加 -with-keys、檔內附警語），匯入含金鑰的檔會把金鑰填進輸入框、按套用才寫入；匯出匯入仍不含環境安裝（ffmpeg、PowerShell 7、faster-whisper 由新裝置的安裝鈕處理）。金鑰輸入框略縮讓說明欄更寬。來源：使用者問「匯出與匯入是全部設定與環境安裝、金鑰都包含嗎」。

## 0.8.6（2026-10-31）

- 以 Claude in Chrome 實看四個服務的額度頁核對：Exa 餘額 $19.98、Free tier「$10 credits per month」、Lite 搜尋 $4／1k ✅；Context7「1/1,000 REQUESTS、COST Free」✅；Firecrawl「1,022 credits left、Resets Nov 2」✅；**Parallel 修正**：註冊送一次性 $20（本機帳號 12/30 到期），「每月 $5」須「Add a card to unlock monthly credits」，不綁卡沒有每月額度；搜尋 Turbo／Fast $1／1k、Basic／Advanced $5／1k。規則、設定檔、docs、視窗說明同步更正。來源：使用者「今天註冊的那四組金鑰，你開 Chrome 都幫我確認是不是都與你說的 API 額度一樣」。

## 0.8.5（2026-10-31）

- 設定視窗截字再修（結構層）：MCP 列勾選框只放名稱、工具名移到說明欄；env 的說明改放在欄位下一列跨欄顯示；內容區大小改變時也重算說明文字的換行寬，並先 `update_idletasks` 讓座標準確。無頭檢查 24 段說明皆在內容區內。來源：使用者回饋「字又被截掉了」。

## 0.8.4（2026-10-31）

- 設定視窗：每把金鑰加「註冊網頁」按鈕（開官方申請頁；網址記在 gui_model.KEY_INFO）；沒填金鑰時「免費優先／一律用金鑰」選單鎖住並固定免費優先，清空金鑰立即鎖回；MCP 列標示「純免費服務，沒有金鑰機制」（deepwiki、mslearn）與「免金鑰版；填金鑰後會多註冊金鑰版」。來源：使用者試用回饋「沒有加金鑰版的原因？」「沒有金鑰時不能選一律用金鑰」「每個金鑰都要提供註冊網址」。

## 0.8.3（2026-10-31）

- 設定視窗：說明文字改為依實際剩餘寬度動態換行（版面每次變動後重算，不再用固定寬度猜，右側不會再被截）；`PYTHONUTF8`、`PYTHONIOENCODING` 改唯讀（固定值，只顯示）；金鑰模式欄簡化為「只能用金鑰」並在區塊底部加一句說明。來源：使用者試用回饋「這兩個沒寫預設以外的值怎麼改，要不要乾脆唯讀」「字還是會被截掉」。

## 0.8.2（2026-10-31）

- 設定視窗：內容區寬度跟著視窗，所有說明文字在視窗內換行（不再被截）；下拉選單與數字框的滾輪只捲頁面、不改值；按 ✕ 關閉時若有未套用的變更會問「套用後關閉／放棄變更關閉／回到視窗」，執行中關閉也會確認。來源：使用者試用回饋「很多部分文字還是截掉」「滾輪會不小心改設定」「打叉也要跳詢問視窗」。

## 0.8.1（2026-10-31）

- 設定視窗依使用者試用回饋修正：預設全視窗開啟、字體放大（Microsoft JhengHei UI 11）；金鑰輸入框直接顯示目前的值（遮罩，按「顯示」看明文），改了才算變更、改回原值自動取消；沒有免金鑰版的金鑰在模式欄標「只能用金鑰」；滾輪只捲動滑鼠所在區域（紀錄區不再帶動上方）；長文字自動換行、Chrome 列不再被截掉；env 欄位旁加白話說明（含 PYTHONUTF8 是什麼）；解除安裝確認視窗寫明「會移除／不會移除」清單。
- **用量守門可開關**：視窗核心區勾選框、`web --usage-guard on|off`（local.json `usageGuard`）；關閉時 `install`／`update` 不註冊 hook 並移除既有條目，verify 顯示「已由使用者關閉」不算錯，status 同步；「全部啟用／全部關閉」也包含它。來源：使用者「用量守門也要可開關」。測試 56 個通過。

## 0.8.0（2026-10-31）

- **設定視窗**（GUI／執行檔計畫的階段 1、2）：`python installer/install.py gui`（或 `installer/gui.py`，tkinter 內建、不裝套件）。開啟時與每次套用後都重讀真實檔案（manifest、settings.json、`~/.claude.json`、local.json、pip import、執行檔偵測），不信表單。內容：環境列（Python、Claude Code、ffmpeg、PowerShell 7、winget、git、node、faster-whisper，缺的有「安裝」或「開下載頁」按鈕）、核心與用量門檻兩個數字、聯網來源總開關＋每個 MCP 開關＋WebSearch 上限等 env、影片來源開關＋下載資料夾、12 把金鑰（遮罩輸入、顯示、**測試**、清除、搜尋類的「免費優先／一律用金鑰」模式）、Claude in Chrome 三層（①擴充已安裝 ②native host 已登記 ③手動按鈕跑 `claude -p --chrome` 實測）＋「Enabled by default」開關（寫 `~/.claude.json` 單一鍵、先備份）、「將變更 N 項」即時摘要、套用（先列清單確認）／取消／全部啟用／全部關閉／檢查／匯出匯入設定（不含金鑰）／備份還原／解除安裝、執行紀錄（金鑰一律遮罩）。
- 邏輯層 `installer/cds/gui_model.py`（純函式，8 個測試）：`read_state`、`diff`、`apply_form`（順序：先寫 local.json → install/update 帶 web／video → 門檻 → 下載資料夾 → Chrome）、`test_key`（12 種金鑰各打一次最便宜的呼叫；環境部錯誤金鑰也回 200 要看內容；台灣政府站只清 `VERIFY_X509_STRICT` 不關驗證）、`install_action`、`chrome_live_test`、匯出匯入、備份還原。本機 8 把金鑰實測全 ✅。
- `install.py gui` 子命令；README 加「設定視窗」。來源：使用者「做成一個執行檔…有開關…API 輸入框…套用或取消…開啟時依當下設定讀取狀態」；階段 3（打包 exe、視窗內更新）待使用者試用視窗後進行。

## 0.7.0（2026-10-31）

- **免費優先雙註冊**：有搜尋類金鑰（exa、tavily、context7、parallel、firecrawl）時預設同時註冊免金鑰版 `<名稱>` 與金鑰版 `<名稱>-key`；`web --key-mode 名稱=always` 改為只註冊金鑰版。規則第 2c 節（可判定）：先免金鑰，回 429／5xx／402 才用 `-key`，之後連續 3 次用 `-key`、第 4 次再試免金鑰；`core.md` 加一句。來源：使用者「免費優先雙註冊，要注意有時候可能是免費被限流而不是用完，每次都先看免費能不能用」。
- parallel、firecrawl 新增金鑰模式（皆 `Authorization: Bearer`，官方文件 2026-10-31 查）；`localKeys` 補五個搜尋類金鑰的額度說明。
- **firecrawl 預設開**，但規則限定只當「讀整頁」第三步：WebFetch／parallel web_fetch → Jina → `firecrawl_scrape`（第 1 節第 4 點改寫為可判定三步）。來源：使用者問「能不能當 parallel 不能用時自動改用 firecrawl」。
- **用量門檻扁平化**：`dispatch-config.json` 的 `usageThresholdPct` 直接是 `fiveHour`／`sevenDay` 兩個數字，移除 `plan`（訂閱方案）與 `boardMeterMarks`；`usage_guard.py` 兩種格式都讀（舊格式仍相容）。本機設定改為 95／99。規則、skill、README 第 10 步同步。來源：使用者「用量守門與 WebSearch 上限也要能自己改數值，就不用訂閱方案了，然後要到該 % 數才會開始守門，沒到的時候完全不用提示」——實查 hook 原本就是門檻以下不注入。
- 測試 47 個通過（新增雙註冊、always／fallback 切換、parallel／firecrawl Bearer、扁平門檻格式）。這是「設定 GUI／執行檔」計畫的階段 0。

## 0.6.4（2026-10-29）

- `video.py download` 預設資料夾可由本機 `local.json` 的 `"video": {"downloadDir": "…"}` 設定（順序：`--out` ＞ local.json ＞ `video.json` 的 `downloadDir`（預設空）＞ `~/Downloads`）；local.json 的 `video` 區塊也可覆寫其他 video.json 鍵。規則 core／web-sources 與 docs/video.md 同步。來源：使用者原話「預設改為存到 D 槽，專門在D槽建一個資料夾放下載的影片」（C 槽剩約 7GB）。測試：`tests/test_tools.py` VideoDownloadDir 三種順序。

## 0.6.3（2026-10-28）

- 移除 `hooks/task-board/`、`hooks/.claude-plugin/marketplace.json`、`hooks/board_server.py`：三者是 Stock-web 專案專屬（寫死本機路徑與使用者帳號名 7 處），且 Stock-web 已有逐位元相同的副本在 `tools/claude-setup/`，該專案 settings 也只引用自己的 `stockweb-tools` marketplace，本 repo 這份沒有任何引用。安裝器 payload 本來就不含它們，安裝行為不變。來源：使用者問「假設把 repo 公開會有什麼風險」→ 掃出唯一含個人路徑的檔就是這個 mod；使用者指示「做第①項」。
- 文件：README 內容表、compatibility、cross-device 同步。

## 0.6.2（2026-10-28）

- 新增 repo 根目錄 `CLAUDE.md`：新裝置 clone 後在此目錄開 Claude Code 會自動載入，指示它照 README「新裝置安裝流程」逐項詢問選用項目與金鑰、不印金鑰值、verify 全過才算完成。來源：使用者問「clone 到新裝置請該裝置的 Claude Code 架設就可以了嗎？也會詢問各項選用、金鑰、工具嗎？」——此前只有 README 有流程，沒有自動載入的入口。
- 查證：掃描全部 38 個 commit，本機 8 把金鑰的真實值與 AIza／AQ.／tvly-／CWA-／ctx7sk-／Bearer／gmail 等樣式皆 0 命中（以 YOUR_API_KEY 等對照字串確認掃描有效）；repo 為 PRIVATE；temp CLAUDE_HOME 模擬新裝置 install → verify 全過 → uninstall 乾淨。

## 0.6.1（2026-10-27）

- `video.py download`：使用者明說要存檔時，最高畫質影像＋最佳音訊合併 mp4 存到 `--out`（預設 `~/Downloads`）；`--max-height`、`--audio-only`、`--cookies-from-browser`、`--cookies cookies.txt`；DRM／需登入／抓取器壞掉三種錯誤各給中文指引。實測 YouTube 1080p 4.5 分鐘 154 MB 約 4 分鐘；抖音回「需要 cookie」；Bilibili 回抓取器壞掉（yt-dlp issue #17879、PR #17898，2026-10-21 起）。
- `ydl_opts` 啟用 JS runtime：沒有 deno 時用 node（yt-dlp wiki/EJS：YouTube 需 JS runtime 解挑戰，否則缺格式或限速）；實測 node 24 解挑戰成功。
- 查證寫進規則：Windows 上 Chrome／Edge 127+ 的 cookie yt-dlp 解不開（issue #10927、#15401），改用 Firefox 或擴充套件匯出 cookies.txt。來源：使用者問「可以貼任何網址（YouTube、Bilibili、抖音、一般網站）用最高畫質下載嗎？」
- 附記：本日測試中 exa 免金鑰模式首次撞到 429（「You've hit Exa's free MCP rate limit」），印證規則「撞 429 再考慮註冊」。

## 0.6.0（2026-10-27）

- `video.py` 新增：`--live 秒數`（transcript／frames／ask；進行中的直播用 ffmpeg 錄 10–900 秒成本機檔再處理，記錄擷取時間；實測台視／東森新聞台 45 秒錄 33 秒、語音辨識正確）、`frames --at 12:30,14:05`（指定時間點截圖）、`info` 顯示直播狀態；自動清理納入 `live_*.mp4`。
- 規則（core 與第 9 節）：主動找影片的三個可判定觸發（使用者明說、體驗型字眼、網頁鏈走完仍未能確認）；看幾支（單一事實 1 支、「全面／多方／比較」最多 5 支、超過先問）；逐字稿句子含指示詞（這個／這裡／看一下…）必做 `frames --at` 或 `ask --clip`；直播回答標擷取時間。來源：使用者 2026-10-27 原話「影片真正贏網頁的是現場實況，所以也能看直播並整理內容？」「動作與上限不一定要侷限在近一年、10 分鐘以上和只找 1 支…語音內容與畫面有關的也要有影片檔或 Gemini 解析」。

## 0.5.2（2026-10-27）

- `video.py` 自動清快取：每次執行刪超過 `autoCleanMediaDays`（預設 7）天沒用的影音檔、超過 `autoCleanAllDays`（預設 30）天的整個資料夾；`clean` 子命令改用同一函式。來源：使用者問「閱讀完影片所產生的檔案會刪除嗎？避免佔用空間」——實測 30 分鐘音訊 30 MB、4 分鐘 720p 影片 83 MB。
- 規則：被問「整支影片講什麼／提到哪些」必須 Read 整份逐字稿檔再答，螢幕前 40 行只是預覽。來源：使用者問「只印前 40 行，後面都看不到嗎？」——檔案本來就完整，但要防止只憑預覽寫摘要。

## 0.5.1（2026-10-27）

- 修正：Context7 金鑰 header 改為官方現行的 `Authorization: Bearer <key>`（原寫 `CONTEXT7_API_KEY`；context7.com/docs/resources/all-clients 的 Claude Code 範例為 `--header "Authorization: Bearer YOUR_API_KEY"`）。`web-sources.json` 新增 `keyHeaderPrefix`，`desired_servers` 支援；加測試（含 `web --key context7=` 清空金鑰回免金鑰）。尚無人填過此金鑰，無實際影響。
- 補查證：Exa 免金鑰官方只寫「Free rate-limited usage」；有金鑰免費層每月 1 日重置 $10（約 2,500 次 Lite 搜尋），**用完回 402 Payment Required、不會自動退回免金鑰**（exa.ai/docs/admin/billing）；Context7 免費帳號每月 1,000 次、用完每天補 20 次（context7.com/plans）。寫進 MCP 一覽與 docs。來源：使用者問「exa 的每月 10 美元額度用完後就繼續用免費的是嗎？context7 有用跟沒用金鑰的差異？」

## 0.5.0（2026-10-27）

- 新增**影片來源**（選用）：`tools/video.py` 單檔 CLI——`search`（yt-dlp `ytsearch` 免金鑰；`--api` 走 YouTube Data API）、`info`、`transcript`（手動字幕 → YouTube 原生自動字幕，語言須與影片語言一致，否則視為誤判 → 本機 faster-whisper；只印前 40 行、`--grep` 帶 `&t=` 連結、`--start/--end`、`--full`）、`frames`（下載 ≤720p → ffmpeg 場景截圖、自動退回等距、上限張數、index.txt 時間點）、`stats`／`comments`（Data API）、`ask`（Gemini：YouTube 網址免下載、本機檔走 Files API 可續傳上傳、`--clip`、503 重試並換備用模型）、`setup`、`clean`。本機 mp4 走同一入口（併入原 `~/.claude/tools/process_video.py` 的 GPU DLL 預載與 CPU 退回）。實測：車埕搜尋 3 筆、30 分鐘中文影片 GPU 辨識約 3 分鐘、手動字幕 6 行、截圖 12 張可 Read、Data API 數據與留言、Gemini 看 YouTube 與本機片段皆正確。
- 安裝器：`--with-video`、`install.py video [--off|--show]`、manifest schema 3（`video` 紀錄；2→3 遷移）、`config/video.json`（套件清單與工具預設值）、verify 新增套件／ffmpeg／faster-whisper（⚠️）／金鑰列；`web-sources.json` localKeys 加 `youtube`、`gemini`。7 個新測試，共 43 個通過。
- 規則：`core.md` 加「影片」與「教使用者操作任何網站或軟體前，先看到那個畫面」兩條；`web-sources.md` 第 9 節（影片：指令表、可判定的選擇規則、IP 等級 bot check 的禮儀、回答格式）、第 10 節（教操作先核對畫面：觸發、做法、分工、寫進文件要標核對日期）。來源：使用者 2026-10-27 原話「教我怎麼做之前，要實際去看我看到的畫面會不會跟你說的完全一樣，這個優化系統都要改」——憑記憶寫的 Google Cloud 步驟漏了兩步驟驗證強制、歡迎條款視窗與建立金鑰側欄表單。
- 文件：`docs/video.md`（用法、兩把金鑰註冊步驟逐畫面核對、不做的事、故障排除）、README 選用段與新裝置流程第 5 步（影片、faster-whisper）、金鑰表加兩列、cross-device、install、web-sources。
- 查證來源：Claude Vision 只收四種圖片格式（platform.claude.com/docs/en/build-with-claude/vision）、Gemini 免費層 YouTube 每天 8 小時且預覽版定價會變（ai.google.dev/gemini-api/docs/video-understanding）、YouTube Data API 每天 100 次 search.list（developers.google.com/youtube/data/determine_quota_cost）、額度按專案計（ai.google.dev/gemini-api/docs/rate-limits）、yt-dlp bot check 為 IP 等級（yt-dlp issues #16147、#17904）。

## 0.4.9（2026-10-27）

- 根本解：規則與 README 新增「裝 PowerShell 7（MSI 版）」——Claude Code 自動偵測 pwsh（官方 tools-reference），MSIX／Store 版偵測不到（issue #55041）；本機以 winget `--installer-type wix` 裝 7.6.9 實測 JSON 中文、三元運算子、無 BOM `Get-Content` 全部正常。README 新裝置流程加第 7 步（問要不要裝 PS7；MU 系統設定由使用者自行開）。
- README 新增「新裝置安裝流程（給在新裝置上執行安裝的 Claude Code 看）」：九步、每個選用項目的問法與不填的影響（with-web、六把金鑰、firecrawl、Claude in Chrome、系統碼頁告知、訂閱方案門檻）；選用段補齊六把金鑰與 firecrawl；cross-device 新裝置步驟同步。來源：使用者問「README 都有這些說明了嗎？新裝置的 Claude 會問我要選哪些嗎？」——原 README 只列 2 把金鑰、未提 /chrome、firecrawl、系統碼頁與方案門檻。
- 補查證來源：settings.json env 傳遞子程序（Claude Code 官方設定參考）、PS 6.2 起 JSON 預設 UTF-8（微軟「Differences from Windows PowerShell」）、Windows Beta UTF-8 的作用與副作用（微軟 Q&A、黑暗執行緒、Esri）。來源：使用者提醒「這題本身也該用這套系統多面確認」。
- 亂碼根源修正：`web-sources.json` env 新增 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`（`--with-web` 寫入 settings.json，工具子程序繼承）——實測 Windows 碼頁 950 下 Python 子程序印中文會 `UnicodeEncodeError`／「���」，設定後正常。規則「Windows 亂碼的三個根源與修法」：Python（已由 env 解）、PowerShell 5.1 `Invoke-RestMethod` 把 UTF-8 當 Latin-1（給出 `RawContentStream` + UTF-8 解碼的正確寫法，實測「ä¸é·¹å¸…」→「三鷹市下連雀７丁目…」）、系統碼頁 950（需使用者自行開啟 Windows Beta UTF-8，Claude 不代改系統設定）。來源：使用者問「能不能從根源讓它不會誤看成亂碼」。

## 0.4.8（2026-10-27）

- 規則新增第 7 節「查證型回答的輸出格式」（硬規則）：關鍵事實旁附網址＋資料日期＋來源原句逐字短引；推論另立「我的補充／推測」段；無來源標〔未附來源〕；送出前逐條對回原文；亂碼不可憑印象補名稱；來源不一致兩者並列；結尾固定「來源」與「查證過程」段。`core.md` 加一句摘要。目的：讓「來源說的」與「模型加的」可分辨、轉述錯誤可被一眼抓到。來源：使用者問能否把「轉述錯」「來源 vs 自加」「沒附來源」直接修掉；此為規則層能做到的上限，模型層轉述錯誤不能歸零，hook 檢查格式列為觀察一週後的選項。
- 原第 7 節「安全與禮儀」改為第 8 節。

## 0.4.7（2026-10-27）

- 補 1a「最後手段」六項（站內搜尋／Google 地圖照片評論、官方 PDF 與開放資料集、Wayback Machine、換語言、deepwiki 問 repo、Tavily 整站爬）並明寫「規則沒列的現有工具用法可主動嘗試並回報」。來源：使用者問「管道都找不到時會不會自己換方法」；CODiS 即為先例。
- 規則新增 2a「社群、論壇、部落格」：逐站實測（parallel／exa）——Mobile01、巴哈姆特、Dcard、PTT、Reddit、Forumosa 整篇含回覆可查；Threads 僅本文；Facebook 社團在登入牆後只能用 Claude in Chrome。查法：`site:` 限定、跨兩站、標「網友說法」與日期。
- 規則新增 2b「程式與技術難題」：錯誤訊息逐字用 exa 查 GitHub issue／Stack Overflow；Claude Code 自身問題查 anthropics/claude-code issues；修法須安全且本機實測。實例：`Missing Subject Key Identifier` 根因為 Python 3.13+ `VERIFY_X509_STRICT` 遇 TWCA 根憑證缺 SKI（cpython #107361、requests #6945），正確修法只清該旗標、不關驗證；據此更正環境部與 CODiS 兩處「用 curl」的說法。
- `core.md` 加社群與程式難題分流一句。

## 0.4.6（2026-10-27）

- 補：新增中央氣象署 CODiS 歷史觀測 API（免金鑰、非文件化 POST 端點、逐日官方實測；雨量 -9.8＝雨跡；梧棲 467770 已無資料）；歷史同期規則改為「有測站用 CODiS、沒測站用 Open-Meteo 重分析、兩者都有時校正偏差」。來源：旅遊行程實測中 Claude 自行找到 CODiS 並以臺中站 10 年實測校正 Open-Meteo（偏冷約 1.5°C）。
- 規則新增「現在沒有預報≠未能確認」（可判定）：曆法／天文可推算的（大潮小潮、農曆、月相）直接推算並標推算；未來太遠的天氣用 Open-Meteo Archive 拉過去 3～5 年同期當歷史參考；月內潮汐用 CWA `F-A0021-001`。來源：旅遊規劃實測中 Claude 把「12/29 大潮或中潮要等 11/29 預報」「12/29 天氣要等 12/22」列為查不到，其實前者由農曆日即可分類、後者可給歷史同期。
- 新增來源：Open-Meteo Archive（歷史天氣，1940 起）、CWA 潮汐預報 `F-A0021-001`（32 天、含農曆與大中小潮分類、日期未排序），皆以本機實測。

## 0.4.5（2026-10-27）

- 補：文件 MCP 的查法與引用——先 search 拿摘錄、夠用就不 fetch 整頁；回覆貼完整網址、關鍵句逐字引、自己的補充與文件原文分開標。來源：`Get-ChildItem -Depth` 題已照規則查 mslearn 並逐字引「added in PowerShell 5.0」，但整頁 fetch 約 2 萬字、未貼網址、且把「要搭配 -Recurse」寫在引用旁（文件範例 8 顯示 -Depth 可單獨使用）。
- 規則修正（來自兩題實測）：(1) 文件 MCP 的必查觸發明寫——「哪一版開始支援／支不支援／有沒有這個參數／預設值」等版本、相容性、參數事實即使有把握也必查並附官方來源，純概念才可免查（實測：PowerShell 三元運算子題答對但未用 mslearn、未附來源）。(2) Windows 呼叫 API 的工具選擇——含非 ASCII 的 JSON 不用 PowerShell 5.1 `Invoke-RestMethod`（UTF-8 被當 Latin-1 解，實測 OpenAQ 東京測站名亂碼導致誤報「港區」），改用 WebFetch／curl＋python／`python -I`。東京一日遊題其餘行為（四 API 單腳本平行、零搜尋、日期雙解讀、OpenAQ 金鑰實測值優先、自行指出預報內部矛盾）全部合規。

## 0.4.4（2026-10-27）

- 補：TDX 基本資料的 `FareDescription` 常已含費率（車埕實測「100 元／當日當次」「20 元／半小時上限 100」），先看它再查 `ParkingRate`。來源：使用者以同題重測，Claude 一次 TDX 呼叫即回報平面、車位、費率、來源與版本，並區分官方登錄與遊記說法。
- 新增來源：交通部 TDX（金鑰 `tdx_id`＋`tdx_secret`，OAuth2 client_credentials）。用途限定為停車場等**結構化靜態資料的單筆查詢**：`CarPark` 基本資料最可靠（`CarParkType` 1 平面／2 立體／3 地下／4 塔／5 機械／6 混合、車位數、地址、電話）；營業時間／出入口限高／費率端點各縣市填寫完整度不同（南投車埕兩座實測 0 筆）→ 空筆退回網頁鏈。基礎會員 5 次／分／金鑰（header `RateLimit-Limit: 5` 實測）；訂閱頁無「學術方案」級別，學術為付費方案減免。`core.md` 加一句停車場靜態事實先查 TDX；`web-sources.md` 第 4 節加 TDX 用法與「停車場靜態事實選哪個」規則；第 5 節 TDX 說法改為「排路線不適用，單筆可用」。來源：車埕停車場實測三步網頁鏈走完仍無法確認平面／立體，TDX 一筆即得。

## 0.4.3（2026-10-27）

- 補：第三步整頁抓取的對象優先序（官網＞政府頁＞新聞＞聚合頁）。來源：「車埕停車場」實測三步鏈全走完、回報格式完全合規，但第三步抓了 Agoda 聚合頁而非結果中已出現的南投旅遊網官方頁。
- 規則修正（來自「米平方停車場限高」實測）：前兩步搜尋已出現官方網址但摘錄無該值時，第三步**必做**整頁抓取確認（摘錄沒有≠官網沒寫）；「建議打電話」的界線改為「未走完升級鏈不可用電話代替查證；走完後可附官方電話當備案」。該次實測其餘行為（parallel→exa 自動升級、跨兩索引才標未能確認、列最接近線索、來源衝突兩者並列、自我更正地點錯誤）皆符合 0.4.2 規則。

## 0.4.2（2026-10-27）

- 規則修正：明寫「查了 2 次」的定義——必須跨兩個不同索引（內建→parallel、parallel→exa、exa→tavily／Chrome 開官網），同一工具換關鍵字不算第二次；每個事實走完兩個索引才可標「未能確認」，且須列出用過的工具、查詢與最接近的線索。多事實查證第二輪只補第一輪沒拿到的。來源：0.4.1 實測中 Claude 對「米平方停車場是否平面」只用 parallel 一次就放棄。

## 0.4.1（2026-10-27）

- 規則修正（來自實際旅遊行程規劃的回饋）：Claude 用內建 WebSearch 查 20 多次、多次回「查不到、建議打電話」卻未切換到 parallel／exa／tavily；使用者一問才切換，各打 1–2 次即查到官網停車規則、公休、公有停車場型式。根因是規則「搜不到時改用」是形容詞、無可判定條件。`core.md` 改為硬規則：台灣在地事實（公休、營業時間、停車、票價、官方公告）直接從 parallel／exa 起手；同一事實內建查 2 次仍無具體值、或結果只說「請電洽」、或時效性問題只拿到一年前資料 → 立即切換，未用 MCP 前不可回報「查不到建議打電話」；≥3 個獨立事實用 parallel 一次多查詢。`web-sources.md` 新增 1a 節切換條件表、台灣在地事實起手規則、禁止回報方式、額度說明（parallel／exa／context7／deepwiki／mslearn 免金鑰不耗使用者額度，只有 tavily 用金鑰）。
- README 版本 0.4.1。

## 0.4.0（2026-10-26）

- 新增三個免金鑰文件 MCP，預設開：`context7`（程式庫最新官方文件；有金鑰以 `CONTEXT7_API_KEY` header 傳）、`deepwiki`（公開 GitHub repo 自動文件與問答，Cognition 官方）、`mslearn`（微軟官方文件）。三者皆遠端託管、2026-10-26 實測端點存活。
- `web-sources.json` 新增 `localKeys` 說明區：`cwa`、`moenv`（環境部空品）、`openaq`、`tavily`、`exa`、`context7`。
- 規則：`core.md`「上網查資料」補文件 MCP 分流；`web-sources.md` 重寫——工具優先序加文件類分流、更正 token 成本描述（Claude Code 延後載入 MCP schema，遠端 MCP 幾乎不花 token）、開放 API 分四類並新增 12 項實測端點（USGS 地震、Open-Meteo 空氣品質、日出日落、CoinGecko 含 TWD、Yahoo Finance chart 含 `2330.TW`、GDELT 新聞、OpenAlex、arXiv、Crossref、Hacker News、Wikimedia 瀏覽量、Open Library）、CWA 新增地震報告 `E-A0015-001` 與警特報、天氣／空品／地震三條選擇規則。查了不列：Semantic Scholar（免金鑰實測首次即 429）、REST Countries、Apify 新聞 MCP、Brave。瀏覽器類 MCP 另行決定。
- 測試：預設 MCP 集合改為常數 `DEFAULTS`，35 個全過。

## 0.3.0（2026-10-26）

- 新增「聯網來源」（選用，預設不啟用）：`config/web-sources.json` 為唯一來源，列免金鑰搜尋 MCP（預設 `parallel`、`exa`；選用 `tavily`、`firecrawl`）與 WebSearch 上限 env（`CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION=600`、`CLAUDE_CODE_WEB_SEARCH_REFILLS_PER_HOUR=300`，官方預設 200／100，需 Claude Code ≥2.1.290）。`install.py install|update --with-web` 啟用；新子命令 `install.py web --key/--enable/--disable/--env/--off/--show` 改本機偏好並立即套用。MCP 以官方 `claude mcp add/remove --scope user` 寫入，本工具只讀 `~/.claude.json` 判斷；使用者自己同名的 MCP 與自己設的 env 不覆蓋；uninstall 只移除本工具登記過的。
- 本機偏好與金鑰（Tavily、Exa、中央氣象署）存 `<CLAUDE_HOME>/claude-dev-system/config/local.json`：不在 manifest、不進 repo、update／uninstall 不動；輸出中金鑰一律遮罩。
- 規則：`core.md` 加「上網查資料」優先序一條；新增 `rules/web-sources.md`（工具優先序、MCP 一覽、2026-10-26 實測過的免金鑰開放 API：Open-Meteo、open.er-api（含 TWD）、Frankfurter、證交所 OpenAPI／MIS、FinMind、政府辦公日曆表、Nager.Date、Wikipedia、Nominatim、OpenSky；需註冊的中央氣象署／Tavily／Exa；沒有免費來源的類別；安全與禮儀）。實測淘汰：Nager.Date 不支援 TW、Frankfurter 無 TWD、台銀牌告 CSV 被反爬擋、Brave 2026-02 取消免費方案、TDX 免費 5 次／分。
- manifest schemaVersion 1 → 2（新增 `web` 紀錄；`_m1_to_2` 自動遷移，舊安裝視為未啟用）。
- 測試：新增 14 個聯網來源測試（假的 `claude mcp` runner，不碰真實設定）：預設不碰、啟用／verify／uninstall 還原、update 不重複註冊、tavily 免金鑰→金鑰→停用、exa 金鑰進 header、使用者同名 MCP 與 env 不覆蓋、--off 保留 local.json、被改壞的 MCP verify ❌ 且 update 補回、env 不是物件時略過不覆蓋、使用者預設同值不被認領、local.json 壞掉給一行中文錯誤且不擋 uninstall、runner 失敗時結束碼 1 且訊息遮金鑰、未啟用時 --show 明說。獨立驗證 agent 在隔離 `CLAUDE_CONFIG_DIR` 下用真實 `claude mcp add` 跑完 install→web→off→uninstall 全流程，真實 `~/.claude*` 雜湊前後相同。
- `install`／`update` 的結束碼：任一步印 ❌（目前只有聯網註冊失敗會）即回 1（之前一律 0）。
- 文件：`docs/web-sources.md`、README「選用：聯網來源」、install／update／uninstall／cross-device 補聯網來源段。

## 0.2.1（2026-10-18）

- 規則：Stock-web H-13 決定「全域 rules 為通用規則唯一來源」，專案 `global-workflow.md` 改成只留指向。`workflow.md` 規則九「7 天 97% 的詳細版」更正為「7 天達收尾門檻的詳細版」並改讀設定檔 `usageThresholdPct`（不寫死數字）；其餘通用句與專案版逐句比對 0 遺漏（專案名詞改寫版與專案實例留在 Stock-web `project-reference.md`）。

## 0.2.0（2026-10-17）

- 規則：Stock-web `docs/claude-rules/global-workflow.md` 去專案化後併入 `rules/`（規則二、三、六～九→`workflow.md`、十→`token-efficiency.md`、十一→`safe-refactor.md`、十二→`doc-governance.md`、派工規格品質與 git 協作→`agent-dispatch.md`），刪除佔位檔；使用者原話、數字、日期原樣保留。`progress-diff` 逐句比對：以去專案化對照後的原文為基準找不到 0 句（原檔直接比對 41 句皆為專案名詞改寫或搬到專案 skill 的導引句）。
- 設定：`config/dispatch-config.json` 改為與 Stock-web `.claude/dispatch-config.json` 同結構（`plan`、`usageThresholdPct`、`boardMeterMarks`、`concurrency`、`dispatchUsageAdjust`、`modelTable` A～I）；舊的 `usage`／`dispatch.taskTypes` 結構廢止（skills 與規則已改指向新結構）。使用者若改過舊版檔，update 會保留並產生 `.new`，請改採新結構。
- hook：`usage_guard.py` 門檻讀取順序＝專案 `.claude/dispatch-config.json`（hook 的 cwd 往上找）→ 全域設定檔 → 內建預設 80／97；`--print` 印出採用哪一份；方案 `until` 到期（含當日）自動改用 `plan.after`。
- 看板 mod 來源：新增 `hooks/limits.ts`，收尾警示與用量條標線改讀同一份設定檔（找不到用預設 80／97）。
- 測試：新增 usage_guard 門檻順序與方案到期測試、看板門檻解析測試。`compat.json` 不變。

## 0.1.0（2026-10-17）

- 初版。來源：Stock-web `tools/claude-setup/`、`scripts/audit/`、`.claude/skills/agent-dispatch`、CLAUDE.md 通用規則。
- 規則分層（`rules/`）：core（合併進 CLAUDE.md 標記區塊）、workflow、agent-dispatch、token-efficiency、doc-governance、safe-refactor；global-workflow 為佔位（待 DOC 合併）。
- skills：cds-agent-dispatch、cds-safe-refactor、cds-doc-governance、cds-feedback-audit。
- hooks：usage_guard 通用版（門檻改讀 `config/dispatch-config.json`，預設 80／97；支援 `CLAUDE_CONFIG_DIR`）；task-board mod 來源（專案專屬，不自動安裝）。
- tools：depgraph（別名、副檔名、排除資料夾、分層規則全參數化；在 Stock-web src 上與原版輸出相同）、moduleInventory、progress-diff（任意檔案逐句比對）。
- 安裝器：check／install／verify／update／uninstall／status；manifest schemaVersion 1 與遷移骨架。
- 相容：Claude Code ≥2.1.0 <3.0.0（實測 2.1.296）；Windows 11 實測，macOS／Linux 未驗證。
