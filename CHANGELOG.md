# 變更紀錄

格式：語意化版本（主.次.修）。主版號變動＝manifest 或設定結構不相容；次版號＝新增規則／skill／工具；修訂號＝修正。

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
