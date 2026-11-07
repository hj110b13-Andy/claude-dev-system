# claude-dev-system 交接紀錄

## 接手狀態（2026-11-07）

**已發布**：v0.15.1（exe 與 .sha256 都在）。0.15.1＝使用者貼另一台自我測試 9/11：pwsh、docs 改判「有沒有查一手來源」不寫死工具，兩題這台重跑都通過；細節見 CHANGELOG。另一台下次跑全套 11 題確認。工作樹乾淨，沒有未完成的改動或 patch，沒有背景任務。

**2026-11-07 做完**（使用者：「週用量更新了，可以繼續做了…把待辦與問題都修好。」）：
- 原待辦 0、1 全部完成並併成 v0.15.0：一鍵安裝（Python 3.14、Git、Node LTS、Claude Code 官方 stable、Deno）、Deno／Node 分兩列、hook 盤點過期計數改用 project-scan 同一套 .gitignore 判斷、發版衛生測試與 repo CLAUDE.md 規則、併入誤標 0.14.2 的 `95c184c`。原文、查證來源與數字都在 CHANGELOG.md 0.15.0；原待辦內容移到本檔最後「已完成待辦原文」。
- 實測：這台用視窗同一個安裝函式實裝 Deno 2.9.8，PATH 不重開就補回、環境列變 ✅（原待辦 2 第一項完成）。
- 使用者截圖的 AI-Search&Fetch 問題（圖片分析時 Gemini 三個模型 503、轉 41 秒）：在那個專案修好並推送 `97da618`，**正式站還沒部署**（`npm run deploy` 被 Claude Code 權限擋下，要使用者自己跑或允許）。細節在 AI-Search&Fetch 的 PROGRESS.md 第十六節。

### 待辦 2：新裝置端對端確認（等使用者下次測；0.15.0 起含一鍵安裝）

- ~~Deno 按鈕裝完環境列是否變 ✅~~：2026-11-07 這台實裝通過。新裝置再看 Python、Git、Node、Claude Code 四個新按鈕（Claude Code 裝完要自己登入）。
- 不經 `/chrome` 勾選後開對話，② 是否自動變 ✅、重開 Chrome 後能否連上（照官方文件寫的，沒實跑）。
- 視窗開著裝 Python 後按「重新整理」是否可用（只做過 PATH 模擬）。
- 先勾「Enabled by default」、之後才裝擴充的流程有沒有正常（使用者 11/4 問過；只驗過設定會保留，官方說偵測不到擴充時會跳安裝提示，都沒實跑）。
- 0.14.2 的 exe 沒有下載來跑過（只跑過原始碼的 --selfcheck）。

### 待辦 3：Stock-web（使用者要自己在那場對話交代）

- 5 個腳本超過 800 行還沒拆（exitStrategy.ts 6,588、register.tsx 866、weeklyGoliveCore.ts 839、histRetest.ts 832、simRulesSnapshot.ts 812），行數閘門只管 src/。拆檔要先估用量給使用者同意。閘門要擴到 scripts/；確定一次性不再修改的才寫進專案 `.claude/dispatch-config.json` 的 `projectAutomation.bigFileExceptions`（逐檔寫原因）。這項不是在這個 repo 做。

### 已知小問題

- 【共用工作目錄】提醒是比對指令文字，指令裡只要出現 `git add -A` 字樣（例如測試資料）也會跳。同一場對話只跳一次，影響小，未修。

決策：2026-11-04｜YouTube 解挑戰的安裝按鈕裝 Deno 不裝 Node｜使用者說「Node如果比Deno還好就用Node」，查證後 Node 沒有比較好｜yt-dlp wiki/EJS「Deno (recommended) | Enabled by default」、Deno「no file system or network access」、Node 要另外 `--js-runtimes node` 且只有「some permissions restricted」。已裝 Node ≥22 的機器仍算通過。

驗證方式：`py -3 -m unittest discover -s tests`（114 項）、`py -3 installer/install.py verify`。

## 已完成待辦原文（2026-11-04 寫、2026-11-07 完成，只移位置不刪）

**2026-11-04 本輪做完**：0.13.0～0.14.2（細節見 CHANGELOG.md）——全域系統對照 hook、行數上限自動提醒、工具後提醒、新裝置三問題（視窗開著裝的 Python 找不到、Chrome 勾選框被鎖、native host 查成 Desktop 機碼、Deno 按鈕）。

#### 待辦 0：補發 0.14.3（用量重置後第一件，約 5 分鐘）

- 問題：`95c184c`（AI-Search&Fetch 11/4 18:32 提交，project-scan 不算 .gitignore 排除的檔）的版本也標 0.14.2，比 `v0.14.2` tag（`718831a`，18:27）晚 5 分鐘，不在任何 tag 或 Release 裡。VERSION 相同，所以其他裝置「檢查更新」不會判定有新版，拿不到這個修正；CHANGELOG 也有兩段 `## 0.14.2`。這台已安裝的是新的（verify 全部通過）。
- 做法：VERSION 改 0.14.3，把 `95c184c` 那段 CHANGELOG 改標 0.14.3 放最上面，update、verify、push、打 tag、確認 Release 兩個附件都在。不要移動 `v0.14.2` tag。
- 整類修法：repo CLAUDE.md「改這個 repo 時」加一條，多場對話會同時改這個 repo，改動前先 `git pull`、看 `git tag --points-at`／最新 tag；目前 VERSION 已打過 tag 就要往上加，不可沿用；可加測試或 hook 檢查「VERSION 已有 tag 但之後還有非 PROGRESS 的 commit」。
- 同一版一起修：hook 的 `_count_newer`（`hooks/usage_guard.py`，健康檢查「盤點過期」的計數）沒有跟著 `95c184c` 改，仍只排除固定資料夾與點開頭資料夾，被 .gitignore 排除的檔照算。Stock-web 有 436 個被排除的檔（多為 docs/eval 評測輸出），跑評測就可能讓「改過 >20 檔」提早觸發；`--check` 與 hook 算法不一致，違反唯一來源。修法：hook 用同一套 `git ls-files --others --ignored --exclude-standard --directory` 判斷（注意 budget 0.8 秒，git 失敗就照舊），加測試。此項是讀程式碼判定，未實跑重現。
- 已複查沒問題：`fa4bc5c`（0.14.1，Stock-web，逾時自動移背景也提醒巡檢）有 tag 與 Release。這兩個 commit 都是改 repo 再 update，沒有再直接改安裝副本。測試全過、工作樹乾淨。

#### 待辦 1：環境區全部改成一鍵安裝（使用者已提、尚未動工）

- 使用者原話（2026-11-04）：「所有環境安裝的部分可不可以都用成點按鈕就直接安裝，不用再去網頁自己載、自己裝，裝的版本就挑穩定又最新的版本，你覺得如何?」我回答贊成；當時 7 天用量 99%，所以只記錄沒動工。使用者已同意（2026-11-04：「你說的都可以」「可以，都記錄下來到時候接手可以做」），含 Claude Code 用原生安裝不用 winget、Python 選有實測的版本、Deno 與 Node 都裝；用量重置後直接做，不用再問。
- 現況：ffmpeg、PowerShell 7、faster-whisper、Deno 已是按鈕；只有 Python、Claude Code 是「開下載頁」（`installer/cds/gui_model.py` 的 `DOWNLOAD_PAGES`，`installer/gui.py` 環境區）；git 沒有按鈕（`git` 列 action 為 None）。
- 查證過的事實（2026-11-04）：
  - Claude Code：官方 setup 頁寫「WinGet installations do not auto-update」，`Native installations automatically update in the background`；原生安裝 `irm https://claude.ai/install.ps1 | iex`。winget 的 `Anthropic.ClaudeCode` 是 2.1.302，使用者新裝置已是 2.1.318，較舊。→ 建議用原生安裝，不用 winget。
  - git：winget `Git.Git` 2.56.0.4。
  - Python：winget 每個次版本一個 ID（`Python.Python.3.x`）。這次 `winget search` 輸出被 tail 截斷，**最新 ID 沒看到，動工前要重查**；新裝置實測 Python 3.14.10＋faster-whisper 1.2.1 可用，3.14 是有實測的候選。
- 做法：`INSTALL_ACTIONS` 加 python、git；Claude Code 用原生安裝腳本（`INSTALL_ACTIONS` 是 argv 清單，要確認怎麼呼叫 PowerShell）；`installer/gui.py` 按鈕文字表加項；`DOWNLOAD_PAGES` 留作沒有 winget 時的備案。裝完靠 0.14.2 的 `_ensure_python`／`refresh_path` 不用重開視窗。
- Deno 與 Node 兩個都給按鈕（使用者 2026-11-04：「我覺得Deno與Node兩個都裝可以嗎?」，已答不衝突）：Node 用 winget `OpenJS.NodeJS.LTS`（當日 26.13.0），不用 Current 版；環境列要分開顯示兩列或各自有按鈕（現在 `js_runtime` 找到 Deno 就算通過，Node 不會出現按鈕）。`tools/video.py` 的 `ydl_opts` 有 Deno 就用 Deno，不用改。
- 順手修：`tools/video.py` 的 `ydl_opts` 只看有沒有 node，沒查版本；node 低於 22（yt-dlp 最低要求）時仍會指定它，應與 `installer/cds/video.py` 的 `JS_MIN` 同一套門檻（小問題，環境列已會顯示未通過）。
- 裝不了、只能開頁的：Chrome 擴充（商店要使用者按）；登入 Claude 由使用者自己做。
- 驗收：測試涵蓋按鈕動作與沒有 winget 的備案；更新 CHANGELOG、VERSION（次版號），發 Release；最終要在全新裝置實測。

