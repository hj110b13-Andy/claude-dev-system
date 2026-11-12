# 專案全方位健檢報告（2026-11-11～12，v0.26.1 → v0.27.0）

依據：使用者交辦的〈專案全方位深度健檢與最終完善〉。這份是問題清單與處理結果的唯一來源；目前狀態與已知限制看 `PROJECT-STATUS.md`，變更摘要看 `CHANGELOG.md` 0.27.0。

## A. 整體評估

**架構與成熟度**：四個部分——安裝器（`installer/`）、設定視窗與自我更新、一支 hook（`hooks/usage_guard.py`）、九支工具（`tools/`），全部是標準庫 Python 腳本，沒有常駐服務（`docs/ARCHITECTURE.md`）。健檢前已有 187 項測試、發布流程、安裝紀錄與備份機制，模組間沒有循環依賴；屬於「日常在用、持續小步修改」的成熟度，但有三類系統性弱點。

**原始專案的主要問題**
1. **多場對話同時讀寫同一個檔沒有保護**：hook 的狀態檔、延後清單、安裝器的暫存檔都是「讀→改→寫」沒有鎖、暫存檔名固定。實跑 8～12 個程序同時寫，資料大量遺失、檔案損毀。
2. **失敗時做一半**：安裝到一半才發現設定檔讀不懂；解除安裝遇到失敗照樣回報完成；還原備份會還原到錯的那一份。
3. **只在一種環境驗證過**：測試只在發布時、只用 Python 3.12、只在 Windows 跑。宣稱支援的 3.10／3.11 上認不出 junction（清理工具的安全機制失效）；macOS 上列不出程序。
4. 文件與程式脫節 22 處（版本號、事件數、題數、預設值）。
5. 用來「證明文件沒有遺漏」的比對工具本身會漏判（數字、日期、否定字被改都判成找得到）。

**涵蓋範圍**：78 個受版控的檔全部涵蓋。程式 37 個 Python 檔逐行讀（6 個稽核 agent 分模組，各自寫重現腳本實跑）；文件、規則、skill、設定檔逐項對照程式；另跑 pyflakes、vulture、bandit、vermin、覆蓋率。**沒有涵蓋**：實際開視窗操作、真實的外部服務（YouTube、Gemini、yt-dlp 下載、Anthropic 用量端點）、macOS 與 Linux 實機安裝、PyInstaller 打出來的 exe 的互動操作。

**成果**：共列 116 條問題（下面各表 115 列＋文末的 RV-07；CX-02 與 TA-13 是同一件事）：P0 0、P1 17、P2 43、P3 56。修掉 108 條，5 條依判斷不改（TA-20、DC-12、DC-13、DC-18、DC-22），3 條部分處理（TA-10、TA-18、DC-17）。測試 187 → 488 項，覆蓋率 61% → 72%。CI 從「只在發布時跑 3.12」變成「每次 push 跑 3.10／3.12／3.14」。

## B. 問題清單

級別：P0 重大錯誤、資安、資料損毀｜P1 核心功能錯誤｜P2 穩定性、效能、架構｜P3 文件、品質。處理欄沒寫「不改」「部分」的都是已修並有回歸測試。每條的重現指令與修前修後輸出保存在健檢當時的工作資料夾，關鍵數字已抄進 CHANGELOG。

### B1. 安裝器核心（`installer/install.py`、`installer/cds/`）

| 編號 | 類型 | 級別 | 位置 | 問題與原因 | 影響 | 處理 |
|---|---|---|---|---|---|---|
| M-01 | 邏輯／資料 | P1 | `commands.py` uninstall、`_prune_backups` | `--restore-backup` 拿「第一筆有 settings 的備份」當安裝前備份；修剪只留最近 10 份、安裝前沒有 settings.json 時第一筆其實是安裝後的檔 | 更新超過 10 次或全新機器：解除安裝後 settings.json 被寫回 7 條指向已刪腳本的 hook | 備份紀錄加選用鍵 `preInstall`、唯一來源 `pre_install_backup()`、修剪永遠保留它；找不到就不還原並說明。不升 schema（舊 exe 讀到新 schema 會報錯） |
| M-02 | 資料 | P3 | `commands.py` web_config | 每次備份但不修剪 | 備份無限增加 | 走同一個修剪 |
| IN-01 | 功能 | P1 | `commands.py` web_config | 非 `--show` 一律同步聯網來源為「開」；`--usage-guard` 只改偏好不動 hook | 存一把 YouTube 金鑰就註冊 6 個 MCP；`--usage-guard off` 後 verify 7 條 ❌ | 未啟用時只帶偏好類參數就只存偏好；`--usage-guard` 立即同步 |
| IN-02 | 異常處理 | P1 | `commands.py` uninstall、`web.py` remove_mcp | MCP 移除失敗仍回 0、刪掉紀錄 | MCP 留著沒人管，重裝時被當成使用者自己的 | 回 1、保留紀錄可重跑 |
| IN-03 | 異常處理 | P2 | `web.py` sync_mcp | remove 失敗後名稱不在紀錄裡 | 同上 | 失敗時保留所有權；重建時 remove 失敗不接著 add |
| IN-04 | 資料／異常處理 | P2 | `commands.py` apply、uninstall | 先寫檔最後才存紀錄，沒有預檢 | 設定檔讀不懂時留下半套安裝，之後解除安裝清不乾淨 | 寫入前 `_preflight`，與 `check` 共用 `settings_error` |
| IN-05 | 邏輯 | P2 | `paths.py`、`web.py` user_config_path | 兩種寫法的家目錄一個 resolve 一個不 resolve | `~/.claude` 是 junction 時讀錯 `.claude.json` | 正規化一致 |
| IN-06 | 併發 | P2 | `fsio.py` atomic_write_bytes | 暫存檔名固定、沒有鎖 | 3 個程序同時 update：24 次中 11 次 PermissionError | 暫存檔名唯一、replace 重試、作業系統層級檔案鎖 |
| IN-07 | 資安 | P2 | `web.py` set_key_arg | 格式錯誤訊息把整個 `名稱=值` 印出來 | 多打一個空格金鑰就印在終端機與對話紀錄 | 訊息只含名稱 |
| IN-08 | 功能 | P2 | `commands.py` verify | 不檢查 hook 用的 Python 還在不在 | Python 被移除後 7 個 hook 全失敗，verify 仍全 ✅ | 多檢查一列 |
| IN-09 | 資料 | P3 | `commands.py` `_md_text` | 有一個 CRLF 就整檔當 CRLF | 混合換行的 CLAUDE.md 區塊外位元組被改 | 區塊外保持原文 |
| IN-10 | 邏輯 | P3 | `claudemd.py` find_block | 只認第一組標記 | 有兩組時只更新、只移除第一組 | 預檢擋下，請使用者合併 |
| IN-11 | 功能 | P3 | `commands.py` `_sync_files` | 衝突解除後 `.new` 不清 | 殘留檔 | 清掉並同步紀錄 |
| IN-12 | 異常處理 | P3 | `manifest.py` migrate | 缺鍵、版本為 null 時 KeyError／TypeError | 手改或損毀的紀錄造成 traceback | 補缺鍵、比較不丟錯 |
| IN-13 | 功能 | P3 | `commands.py` verify | 編譯檢查會寫 `_verify.pyc` | verify 不是唯讀 | 只在記憶體編譯 |
| IN-14 | 文件 | P3 | `install.py` docstring 等 | 題數、結束碼、選項說明與實際不符 | 照文件做會誤解 | 改正 |
| IN-15 | 品質 | P3 | `commands.py` verify | 一個分支平常到不了 | 讀程式會誤解 | 補註解說明何時會到 |
| RV-03 | 邏輯 | P2 | `commands.py` status、verify、web_config | IN-02 留下的「沒有版本的紀錄」被當成已安裝 | 顯示「已安裝 vNone」、web 子命令 traceback | `incomplete_uninstall()` 唯一判定，各命令回一行說明 |

### B2. 設定視窗、自我更新、發布（`gui.py`、`gui_model.py`、`appdir.py`、`.github/workflows/`）

| 編號 | 類型 | 級別 | 位置 | 問題與原因 | 影響 | 處理 |
|---|---|---|---|---|---|---|
| GU-01 | 邏輯 | P1 | `gui_model.py` find_system_python | 用空白切子程序輸出 | 路徑含空白時 exe 模式所有 hook 註冊成壞路徑 | 逐行解析、路徑要存在 |
| GU-02 | 資料 | P1 | `gui_model.py` `_local` | local.json 壞檔時回空預設值再整檔寫回 | 金鑰無聲消失、畫面顯示成功 | 寫入路徑遇壞檔不寫、回 2 |
| GU-03 | 邏輯 | P2 | `appdir.py` check_update、check_exe_update | 版本解析不出來時比較丟 TypeError | 一個不合法的 tag 讓所有 exe 的更新失敗，備援也不啟動 | 唯一比較函式 `is_newer` |
| GU-04 | 發布 | P2 | `release.yml` | tag 與 `config/VERSION` 沒有比對；tag 樣式 `v*` | 不一致時 exe 會無限提示更新 | 發布前比對；樣式改 `v主.次.修` |
| GU-05 | 驗證 | P2 | `gui.py` `_collect`、`gui_model.py` | 數值只轉型不檢查；同一規則寫兩處 | 0、負數、nan 寫進設定檔；填錯無聲退回 | 唯一驗證函式，三處共用 |
| GU-06 | 流程 | P2 | `gui.py` do_apply | 「套用後關閉」旗標沒重設；失敗也關窗 | 視窗自己關掉、看不到錯誤 | 判斷抽成純函式（視窗層未實跑） |
| GU-07 | 資料 | P3 | `gui_model.py` write_task_check 等 | 整段重建 | 使用者自加的鍵被洗掉 | 只覆寫自己管的欄位 |
| GU-08 | 驗證 | P3 | `gui_model.py` import_profile | 匯入沒有型別檢查 | `"no"` 被當成 True、`"abc"` 讓表單停在一半 | 型別與範圍檢查，不合格整份拒絕 |
| GU-09 | 執行緒 | P3 | `gui.py` do_test_key | 工作執行緒直接讀 tk 變數 | 潛在的不穩定 | 主執行緒先讀（視窗層未實跑） |
| GU-10 | 一致性 | P3 | `gui.py` 自動檢查更新 | 自動檢查不查 exe、與手動檢查兩套邏輯 | 顯示「已是最新」但 exe 是舊的 | 共用 `update_plan` |
| GU-11 | 重複 | P3 | `appdir.py` cleanup_old_exe | 測試測的那份沒在用 | 測試證明不了實際行為 | 共用一份 |
| GU-12 | 品質 | P3 | `gui.py`、`release.yml` | 重複匯入、重開沒帶 `--claude-home`、action 沒釘版 | 自訂設定目錄重開後跑到預設目錄 | 已修；**PyInstaller 版本不釘（不改）**：repo 沒有相依管理檔，釘死的版本會過期而沒人更新 |
| RV-02 | 驗證 | P2 | `gui.py` `_collect` | GU-05 的修正對沒動過的欄位也驗證 | 手改過的舊門檻讓整張表單一直「有誤」 | 沒動過就沿用原值（以腳本驗證，未開視窗） |
| CI-01 | 發布 | P2 | `release.yml` | 4 個 action 用已淘汰的 Node.js 20（最近一次發布有警告） | 日後會直接失敗 | 升大版；第三方 action 釘在 commit SHA |
| CI-02 | 測試 | P2 | `.github/workflows/` | 只有打 tag 才跑測試、只跑 3.12 | 壞掉要到發布才知道；3.10 從沒驗過 | 新增 `tests.yml` |

### B3. hook（`hooks/usage_guard.py`）

| 編號 | 類型 | 級別 | 位置 | 問題與原因 | 影響 | 處理 |
|---|---|---|---|---|---|---|
| HK-01 | 資料 | P1 | `_pa_load`／`_pa_save` | 直接覆寫、讀到壞檔當空、沒有鎖 | 8 個程序各寫 40 次只剩 10／320 個鍵；提醒重複、計數歸零 | 原子寫入＋鎖＋三方合併＋壞檔改名保留 |
| HK-02 | 異常處理 | P1 | `save_state`、`main` | 狀態檔被開著時寫入丟例外，排在輸出之前 | 整則 hook 的提醒全部消失 | 寫入不丟例外；先輸出再存 |
| HK-03 | 邏輯 | P2 | `main` 用量判斷 | 讀不到用量時沿用舊數字，不看重置時間 | 端點失效時每則提示都叫人收尾 | 重置時間已過就當未知 |
| HK-04 | 邏輯 | P2 | `_pa_skip` | Windows 路徑比對分大小寫 | 小寫磁碟代號的家目錄被要求跑 project-init | 唯一的路徑比對函式 |
| HK-05 | 資料 | P2 | `main` 讀 stdin | 用系統碼頁解碼 | 沒有 `PYTHONUTF8` 時中文路徑變亂碼，專案相關功能靜默失效 | 一律當 UTF-8 |
| HK-06 | 邏輯 | P2 | `subagent_lang_nudge`、`sg_last_turn` | 沒過濾系統合成訊息 | 撞用量上限時每個 agent 被誤報語言提醒 | 唯一的過濾函式 |
| HK-07 | 效能 | P2 | `project_auto_msg` | 去重之前就先數檔 | 每則提示多 0.2～0.5 秒 | 調整順序 |
| HK-08 | 邏輯 | P3 | 去重鍵 | 每個資料夾只記一個對話 | 兩場對話交替時每則都注入 | 改記對話清單（相容舊格式） |
| HK-09 | 資料 | P3 | 狀態鍵 | 三類鍵不修剪 | 檔案無限成長 | 各留最近 200 個 |
| HK-10 | 功能 | P3 | `settings_ops.py` matcher、背景任務判定 | 沒有 Monitor | 只開 Monitor 時不提醒建巡檢 | 兩處都加 |
| HK-11 | 測試 | P3 | `tests/test_hooks.py` | `unittest.main()` 夾在檔案中間 | 直接執行只跑 19／56 項 | 移到檔尾、暫存資料夾會清 |
| HK-12 | 文件 | P3 | docstring、註解 | 與行為不符 | — | 改正 |
| HK-13 | 效能 | P3 | Stop 守門讀對話紀錄 | 每次從頭讀整份 | 165 MB 的紀錄每輪多 2 秒 | 從檔尾讀；12 份真實紀錄結果相同 |
| TB-14 | 資料 | P2 | `_sub_scan` | 嚴格 UTF-8，最後一行寫到一半就整個失敗 | agent 還在跑時被判成沒讀記憶、沒上網 | 容錯 |

### B4. 工具甲（`resgate.py`、`procs.py`、`cleanup.py`、`video.py`）

| 編號 | 類型 | 級別 | 位置 | 問題與原因 | 影響 | 處理 |
|---|---|---|---|---|---|---|
| TA-01 | 資料 | P1 | `resgate.py` load_jobs／save_jobs | 沒有鎖、暫存檔名固定、壞檔當空 | 12 個程序同時登記只剩 6／2／1 筆 | 檔案鎖、壞檔改名保留 |
| TA-02 | 邏輯 | P1 | `resgate.py` run | 不照 PATHEXT 找 `.cmd` | Windows 上 `run -- npm` 一律 127，規則要求的做法行不通 | `shutil.which` 解析 |
| TA-03 | 邏輯 | P2 | `resgate.py` run＋規則 | 等待與工作共用前景 10 分鐘上限 | 等很久才開跑的工作被砍 | 說明與規則改成「先 check，不足就背景跑」 |
| TA-04 | 邏輯 | P3 | `resgate.py` free_gb | macOS 的後備走不到 | macOS 閘門永遠放行 | 已修（只有 mock 驗證） |
| TA-05 | 邏輯 | P3 | `resgate.py` same_project | 上層資料夾也算同專案 | 家目錄登記的工作每個專案都被叫去跑 | 只認同專案根或 worktree |
| TA-06 | 資料 | P3 | `resgate.py` `--project` | 名稱被記成 `cwd\名稱` | 清單顯示不存在的路徑（健檢中實際發生） | 記專案根 |
| TA-07 | 品質 | P3 | `resgate.py` | 輸出沒 flush；`done` 找不到也回 0 | 訊息順序錯 | 已修 |
| TA-08 | 資料 | P2 | `cleanup.py` plan_worktrees | 看不到被忽略的檔、不判斷是否在用 | 剛建的 worktree 被列為可刪，`.env` 與輸出檔一起消失 | 三道保留條件 |
| TA-09 | 異常處理 | P3 | `cleanup.py` | `--apply --json` 有錯仍回 0 | 腳本誤判成功 | 回 1 |
| TA-10 | 資料 | P3 | `cleanup.py` plan_temp | 別場閒置超過 24 小時的對話暫存會被列為可刪 | 可能刪到還要用的暫存 | **部分**：清單加說明；判定不改（沒有可靠方法知道別場對話還開著） |
| TA-11 | 功能 | P2 | `procs.py` | 只認 bash，不認 PowerShell 工具的程序鏈 | PowerShell 開出的殘留程序全部漏掉 | 納入帶標記的 cmd.exe |
| TA-12 | 邏輯 | P3 | `procs.py` 孤兒判定 | 父 PID 被重用時漏判 | — | 比較建立時間 |
| TA-13 | 相容 | P3 | `procs.py` `_snapshot_posix` | 用 macOS 沒有的 `etimes` | macOS 列不出任何程序 | 見 CX-02 |
| TA-14 | 邏輯 | P2 | `video.py` 字幕選擇 | 兩條路順序不一致 | 英文影片拿到西班牙文翻譯稿 | 唯一的 `choose_caption` |
| TA-15 | 資料 | P2 | `video.py` clean_cache | 刪快取資料夾底下任何舊子資料夾 | 快取指到共用資料夾時別的資料被刪 | 只碰本工具命名的資料夾 |
| TA-16 | 異常處理 | P3 | `video.py` 參數 | 錯誤參數 traceback | 與說明的 exit 2 不符 | 一行說明＋exit 2 |
| TA-17 | 邏輯 | P3 | `video.py` youtube_id | 無副檔名的本機檔被當成影片 ID | — | 路徑存在時當本機檔 |
| TA-18 | 穩定性 | P3 | `video.py` 下載、轉檔 | 直接寫最終檔名；沒有大小上限與逾時 | 半截檔被當成完整檔重用 | **部分**：先寫 `.part`；大小上限與逾時不加（沒有依據的數字） |
| TA-19 | 品質 | P3 | `video.py` | 沒有佔位符的 f-string | — | 已修 |
| TA-20 | 架構 | P3 | `procs`、`resgate`、hook | 「全域設定加專案覆蓋」實作三份 | 改讀法要改三處 | **不改**：hook 的測試靠改模組常數隔離、另兩支讀環境變數，硬合併會讓測試隔離失效；記為已知技術債 |
| TA-21 | 文件 | P3 | `video.py` clean_cache docstring | 與實際判定不符 | — | 改正 |
| RV-01 | 邏輯 | P2 | `video.py` choose_caption | TA-14 的修正讓同語系人工字幕被自動字幕蓋過 | 簡中／港澳人工字幕降成機器稿 | 加回「同語系人工字幕優先」 |
| RV-04 | 邏輯 | P2 | `cleanup.py` | TA-08 的保留條件太寬 | 跑過 build 的 Next.js worktree 永遠清不掉 | 自動產生的檔不算；只含連結的資料夾不算 |
| RV-06 | 文件 | P3 | `resgate.py` 說明 | 教人用 `bash -c`，Windows 上可能是 WSL 的 bash | — | 改寫 |

### B5. 工具乙（`project-scan.py`、`depgraph.py`、`moduleInventory.py`、`agent-audit.py`、`progress-diff.py`）

| 編號 | 類型 | 級別 | 位置 | 問題與原因 | 影響 | 處理 |
|---|---|---|---|---|---|---|
| TB-01 | 功能 | P1 | `project-scan.py` 寫索引 | 重跑覆蓋 `refactorDecision` | 「只問一次要不要重整」失效 | 保留人寫進去的鍵 |
| TB-02 | 邏輯 | P1 | `progress-diff.py` | 去空白後子字串比對、跨行拼接 | 數字、日期、否定字被改都判成找得到——證明不了文件沒有遺漏 | 重寫為逐句比對，多一類「疑似改寫」 |
| TB-03 | 架構 | P2 | `depgraph.py` | 與 project-scan 兩套走訪 | 閘門把 worktree、`.next` 算進去而漏掉真正的循環 | 共用一份 |
| TB-04 | 邏輯 | P2 | `project-scan.py` py_graph | 匯入解析漏多種寫法 | 依賴圖不完整（這個 repo 只算到 37 條邊，實際 51） | 補齊 |
| TB-05 | 功能 | P2 | `project-scan.py` 入口偵測 | 只認固定檔名 | 找不到入口 | 認 `__main__` 守衛 |
| TB-06 | 邏輯 | P3 | `project-scan.py` | `startswith(".git")` 排除了 `.github` | 工作流程檔不在盤點裡 | 只排除 `.git` |
| TB-07 | 架構 | P2 | `project-scan.py`、hook | 「算不算專案」兩套判定，結果相反 | 同一個資料夾兩邊說法不同 | 唯一的 `count_code_files`，hook 呼叫它 |
| TB-08 | 文件 | P2 | 兩個 skill | 教人把 `--check` 當測試閘門；單位沒寫清楚 | 閘門動不動就失敗 | 新增 `--max-cycles`，改寫 skill |
| TB-09 | 邏輯 | P3 | 匯入解析 | BOM、ESM `./b.js`、`require()` 解析不到 | — | 已修 |
| TB-10 | 異常處理 | P3 | `project-scan.py --check` | 索引不合法時 KeyError；寫檔不是原子 | — | exit 2、原子寫入 |
| TB-11 | 異常處理 | P2 | `moduleInventory.py`、`depgraph.py` | 非 UTF-8 崩潰；root 不存在 exit 0 | 路徑打錯時閘門永遠通過 | exit 2 |
| TB-12 | 效能 | P3 | `--summary` | 做完整雜湊與依賴圖 | 多餘的工作 | 只計數 |
| TB-13 | 邏輯 | P2 | `agent-audit.py` | 判定不看先後順序 | 統計偏高 | 看事件順序 |
| TB-15 | 資料 | P3 | `agent-audit.py` | 同一模型拆成兩類 | — | 取家族名 |
| TB-16 | 異常處理 | P3 | `progress-diff.py` | 讀檔失敗與有遺漏同碼 | — | exit 2 |
| TB-17 | 品質 | P3 | `project-scan.py` count_lines | 死碼 | — | 刪除 |
| TB-18 | 測試 | P3 | `tests/test_tools.py` | `unittest.main()` 夾在中間 | 直接執行只跑 12／29 項 | 移到檔尾 |
| RV-05 | 異常處理 | P3 | `depgraph.py` | TB-03 之後單獨複製走會 traceback exit 1 | 與「閘門不通過」同碼 | 一行說明＋exit 2 |

### B6. 文件、規則、設定檔

| 編號 | 級別 | 位置 | 問題 | 處理 |
|---|---|---|---|---|
| DC-01 | P2 | `README.md` | 寫「目前 0.9.5」（實際 0.26.1） | 不寫死 |
| DC-02 | P2 | `README.md`、`docs/compatibility.md` | hook 事件只列 2 個（實際 7 個） | 改正 |
| DC-03 | P1 | `rules/workflow.md` | 預設門檻寫 80%（實際 85%） | 更正並保留原數字的註記 |
| DC-04 | P1 | `README.md`、`docs/install.md`、`install.py` | 自測「九題」（實際 11 題） | 不寫死 |
| DC-05 | P1 | `docs/install.md` | skill「七個」（實際 10 個） | 改正 |
| DC-06 | P1 | `README.md`、`docs/web-sources.md` | firecrawl 一處寫預設關、一處寫預設開 | 統一為預設開 |
| DC-07 | P1 | `README.md`、`docs/web-sources.md`、視窗文字 | 「用量守門」開關其實關掉整支 hook，文件沒說 | 文件與視窗都寫清楚 |
| DC-08 | P2 | `dispatch-config.json` 說明、`README.md` | 說會生 `.new`（實際不會） | 改正 |
| DC-09 | P2 | `web-sources.json` | exa 撞 402 的處理與規則相反；金鑰模式漏一種 | 改正 |
| DC-10 | P2 | `docs/compatibility.md`、`docs/update.md` | 遷移鏈寫到 0→1、schema 2（實際 0→1→2→3） | 改正 |
| DC-11 | P2 | `CLAUDE.md` | 要問的清單與 README 的步驟不符 | 改正 |
| DC-12 | P2 | `core.md`、`core-detail.md`、`web-sources.md` | 巡檢固定 prompt 三份副本 | **不改內容**：core.md 那份每次載入必須在；改用測試守住三處逐字相同 |
| DC-13 | P2 | `rules/core-detail.md` | 「不一致以這裡為準」形成兩個來源 | **不改設計**：加測試檢查對應關係 |
| DC-14 | P3 | hook docstring | 只列 4 個事件 | 改正 |
| DC-15 | P3 | 規則 | 2 個 hook 標籤沒交代 | `rules/workflow.md` 新增 20 個標籤的對照表 |
| DC-16 | P3 | `core.md` 等 | 「第 10 節」沒寫檔名 | 補上 |
| DC-17 | P3 | 文件 | 部分旗標沒文件 | **部分**：補了自測的旗標；影片的旗標以 `--help` 為準 |
| DC-18 | P3 | `web-sources.json` | tavily 工具名寫法 | **不改**：只用於顯示 |
| DC-19 | P3 | 規則 | 4 處形容詞式、不可判定的條件 | 寫出判定條件 |
| DC-20 | P2 | `README.md` | 「exe 在下一版」（早已做好） | 改正 |
| DC-21 | P3 | `docs/web-sources.md` | 優先序所在的檔寫錯 | 改正 |
| DC-22 | P3 | `web-quick.md` | 字數是約數 | **不改**：在「約」的範圍內 |

### B7. 第一次在其他版本與平台跑測試才發現的

| 編號 | 類型 | 級別 | 位置 | 問題與原因 | 影響 | 處理 |
|---|---|---|---|---|---|---|
| CX-01 | 邏輯／資料 | P1 | `project-scan.py` is_link_dir、`cleanup.py`、hook 的後備 | 靠 3.12 才有的 `os.path.isjunction`，3.10／3.11 直接回「不是連結」 | 宣稱支援的 3.10／3.11 上，清理工具會跟著 junction 刪到 worktree 外面的資料 | 改看重解析點種類；CI 的 3.10 已通過 |
| CX-02 | 相容 | P3 | `procs.py` | 即 TA-13 | macOS 列不出程序 | 改用 `etime`；結果見 E |
| CX-03 | 邏輯 | P3 | `resgate.py` `_git_root` | 沒解開連結 | 同一資料夾經連結有兩種寫法時不算同專案（macOS 的 `/var`） | 先 realpath |
| CX-04 | 測試 | P3 | 4 個測試 | 依賴本機裝了 ffmpeg、Windows 路徑寫法 | 換台機器就失敗 | 去掉環境依賴 |

RV-07（兩個恆真的測試）已補上真正的斷言。

## C. 實際修改紀錄

65 個檔、+7,150／−703 行（`git diff --shortstat v0.26.1 HEAD`，寫這份報告時；之後只會多文件）。分模組的 commit：

| commit | 內容 | 怎麼驗證 |
|---|---|---|
| `4ed2108` | 版本 0.27.0、命令列入口測試 | 13 項測試 |
| `ff2c45f` | CI：`tests.yml`、`release.yml` | 試跑分支實跑（見 E） |
| `57a218d` | 文件與規則對齊＋一致性測試 | `tests/test_docs_consistency.py` 16 項 |
| `5cc922f` | 安裝器（M-01、IN-01～15） | 40 項新測試；重現腳本修前修後 |
| `b40f2ad` | 視窗與自我更新（GU-01～12） | `tests/test_gui_audit.py`；`--selfcheck` |
| `e86f5ca` | hook（HK-01～13、TB-14） | 57 項新測試；耗時對照；12 份真實紀錄比對 |
| `ac8e81b` | 工具乙（TB-01～18） | 38 項新測試；0.26.0 瘦身重驗 |
| `5db1dda` | 工具甲（TA-01～21） | 58 項新測試 |
| `f0c186b`、`32350c2` | 跨模組收尾（TB-07 hook 這一半、HK-10、視窗文字） | 相關 172 項測試 |
| `7565b5f` | 獨立審查的 7 條（RV-01～07） | 10 項新測試；審查者的腳本 |
| `fd70069`、`9038530` | 架構文件、盤點、閘門測試、故障排除、CHANGELOG | 閘門測試 2 項 |
| `612990e` 之後 | CI 發現的 CX-01～04 | CI 四輪試跑 |

**有意改變的既有行為**全部列在 CHANGELOG 0.27.0〈更新後會感覺到的行為改變〉。既有測試的期望值只改了兩種：拿掉已刪參數（hook 測試的 `poll=0`）、路徑改比解開連結後的結果。

**怎麼防止修正互相破壞**：五個模組各在自己的 git worktree 修、各自跑全套測試；合併後再跑全套；用稽核時寫的 19 支重現腳本對合併後的程式重跑；另派一個沒參與修正的 agent 審查整批修改（找到 7 條）。

## D. 優化成果

- **架構**：同一規則的重複實作收斂成唯一來源 11 處（路徑比對、版本比較、數值驗證、字幕選擇、原始碼計數、依賴圖走訪、安裝前備份、設定檔預檢、狀態檔寫入、連結判定的後備、未完成解除安裝的判定）。
- **穩定性**：三處「讀→改→寫」（hook 狀態、延後清單、安裝器）都有鎖與原子寫入；壞檔改名保留不覆寫；安裝與解除安裝不再做一半。
- **安全性**：金鑰不再出現在錯誤訊息；清理工具不刪還在用的 worktree、不跟著 junction（含 3.10／3.11）、影片快取清理不碰別的資料夾；發布流程權限最小化、第三方 action 釘版。
- **效能**：Stop 守門讀 165 MB 的對話紀錄 2.26 秒 → 0.004 秒；專案自動化判定少做一次檔案掃描；其餘事件耗時持平（±11% 內，量測雜訊約 ±10%）。
- **測試**：187 → 488 項；覆蓋率 61% → 72%；CI 每次 push 跑三個 Python 版本。
- **文件**：22 處不一致改正；新增架構文件、hook 標籤對照表、故障排除 7 列；文件與程式的一致性有 16 項測試守住。

## E. 測試與驗證結果

| 項目 | 狀態 | 依據 |
|---|---|---|
| 編譯（`compileall`） | PASS | 本機 3.14，結束碼 0 |
| 全套單元測試，本機 Windows 11／Python 3.14 | PASS | 488 項、3 項略過（POSIX 權限、PowerShell 工具內才能測的程序鏈、目前版本還沒打 tag 的發布衛生檢查） |
| 全套單元測試，CI Windows／Python 3.10 | PASS | 試跑分支第 4 輪 |
| 全套單元測試，CI Windows／Python 3.12 | PASS | 同上 |
| 全套單元測試，CI Windows／Python 3.14 | PASS | 同上 |
| 全套單元測試，CI ubuntu／Python 3.12 | PASS | 同上（第一次在 Linux 上跑；含安裝器的檔案鎖與安裝—更新—解除安裝循環） |
| 全套單元測試，CI macOS／Python 3.12 | PASS | 同上（第一次在 macOS 上跑；前三輪依序抓到 CX-02、CX-03 與兩個測試的環境依賴，修完後第 4 輪通過） |
| 打包 exe＋不開視窗的冒煙測試（新版 action） | PASS | 試跑分支手動觸發，全部步驟成功、沒有 Node 20 警告 |
| 發布到 Release（建 Release、附兩個檔） | 見 `PROJECT-STATUS.md` | 只有真的推 tag 才會跑到 |
| 稽核時的 19 支重現腳本，對修正後的程式重跑 | PASS | 壞行為全部消失 |
| 邊界與異常情境（壞設定檔、同時寫入、失敗的外部命令、不合法輸入） | PASS | 各模組的 `*_audit` 測試 |
| 舊版安裝 → 新版更新 → 驗證 → 解除安裝，使用者設定位元組不變 | PASS | 審查者的腳本（含 8.3 短檔名家目錄、CRLF 的 CLAUDE.md、使用者自己的 hook） |
| 靜態分析：pyflakes | PASS | 只剩 3 條（1 條是刻意的可用性檢查、2 條在既有測試檔） |
| 靜態分析：bandit | PASS | 沒有 `shell=True`；中風險 5 條都是 `urlopen`，網址是程式內的常數或官方回應；高風險 2 條是把 sha1 當快取鍵 |
| 最低 Python 版本 3.10 | PASS | vermin 靜態檢查＋CI 實跑 |
| 依賴循環 | PASS | 0 組，已裝成測試閘門 |
| 文件與程式一致 | PASS | 16 項測試 |
| 設定視窗實際操作（點按、填表、套用、關窗） | NOT TESTED | 沒有開視窗；只驗抽出來的邏輯與 `--selfcheck` |
| 外部服務（YouTube、Gemini、yt-dlp 下載、語音辨識、Anthropic 用量端點） | NOT TESTED | 不用使用者的金鑰與額度；只測到不連網的邏輯 |
| 聯網來源的 MCP 註冊（真的呼叫 `claude mcp add`） | NOT TESTED | 測試用假的執行器 |
| macOS、Linux 實機安裝與 hook 觸發 | BLOCKED | 沒有機器；CI 只能跑單元測試 |
| exe 的自我更新（真的下載、換檔、重開） | BLOCKED | 要有比現在新的 Release 才測得到；邏輯有單元測試 |
| 自我測試 `install.py selftest`（11 題，每題一場無頭對話） | NOT TESTED | 會花對話額度，規則是手動跑 |

## F. 尚未解決與需要人工確認的

**沒修的**
- TA-20：三份設定讀取沒有合併（理由見 B4）。
- TA-10、TA-18、DC-17：部分處理（理由見各列）。
- 四個檔超過 800 行（hook 2,217、`gui_model.py` 1,360、`video.py` 1,209、`gui.py` 1,125）沒有拆。hook 與工具要能單檔獨立執行；健檢文件要求避免不必要的大規模重構。

**需要人工確認**（你方便時看一下即可，都不影響這版使用）
1. **開一次設定視窗實際點過一輪**：數值填錯的提示、套用失敗不關窗、開窗自動檢查 exe——這幾項只有讀碼與邏輯測試，沒有真的在畫面上看過。
2. **另一台裝置更新到 0.27.0 後跑 `verify`**：路徑正規化改過，如果那台的家目錄是 8.3 短檔名，要先 `update` 再 `verify`（順序反過來會多看到 hook「異常」，update 後就好）。
3. **`--usage-guard off` 的範圍**：現在文件與視窗都寫清楚「關掉整支 hook」。如果你要的其實是「只關用量提醒、其他守門照常」，那是另一個功能，要另外做。
4. **`~/.claude/state/` 與 `%TEMP%` 的殘留**：健檢過程在 `%TEMP%` 留下 `cds-audit-*`、`fixhook-*` 等暫存資料夾（agent 的清理指令被擋）；可用 `py -3 ~/.claude/claude-dev-system/tools/cleanup.py` 看清單。

**已知技術限制**
- exe 沒有程式碼簽章；`.sha256` 只能防下載損毀。
- hook 的檔案鎖最多等 0.3 秒，拿不到就不帶鎖寫（hook 不可被卡住）：極端並發下仍可能少幾筆去重狀態（實測 320 個鍵留下 308～317 個），不會損毀。
- `progress-diff.py` 的「疑似改寫」只認數字類與否定字；同義詞替換會落在「找不到」（方向是安全的）。
- PowerShell 工具開出的孤兒程序沒有工作資料夾資訊，`procs.py` 指定專案時認不出來。

## G. 最終交付評估

| 面向 | 評估 |
|---|---|
| 功能完整性 | 已發布的功能都有完整流程；這次沒有新增功能。 |
| 邏輯正確性 | 找到的 17 條 P1 全部修掉並有回歸測試；每一條都有修前修後的實跑對照。 |
| 系統穩定性 | 併發寫入、半途失敗、壞檔三類問題有結構性的處理；hook 仍保持「永不擋住 Claude Code」。 |
| 安全性 | 沒有發現可被遠端利用的問題；本機層面的金鑰外洩、誤刪資料已修。供應鏈上 exe 沒有簽章是已知取捨。 |
| 可維護性 | 重複實作收斂、跨檔介面有測試；四個大檔仍是閱讀負擔。 |
| 可擴充性 | 新增 hook 事件、工具、設定鍵都有既有的接法；manifest 有遷移機制。 |
| 測試完整性 | 邏輯層 72%；視窗層 0%、外部服務沒有自動化測試，這兩塊靠人工。 |
| 文件完整性 | 安裝、更新、解除安裝、故障排除、架構都有且與程式對得上，並有測試防止再脫節。 |

**結論**
1. **可交付**：是。Windows 上（實際使用的平台）自動化驗證全數通過。
2. **適合長期維護**：是。CI、閘門測試、文件一致性測試讓之後的修改有防護網。
3. **值得後續改善**：視窗層的自動化畫面測試；三份設定讀取合併；macOS／Linux 實機驗證；exe 簽章。
4. **重大風險**：沒有發現不建議使用的重大風險。要誠實說的是：這不代表沒有問題——視窗操作與外部服務沒有被自動化測試涵蓋，這次健檢本身就在最後階段才靠 CI 發現一條存在已久的 P1（CX-01），同類「只在沒跑過的環境才會出現」的問題可能還有。
