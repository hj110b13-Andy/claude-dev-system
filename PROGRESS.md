# claude-dev-system 交接紀錄

## 接手狀態（2026-11-04，7 天用量 99% 收尾時寫）

**已發布**：v0.14.2（exe 與 .sha256 都在）。工作樹乾淨，沒有未完成的改動或 patch，沒有背景任務。

**本輪做完**：0.13.0～0.14.2（細節見 CHANGELOG.md）——全域系統對照 hook、行數上限自動提醒、工具後提醒、新裝置三問題（視窗開著裝的 Python 找不到、Chrome 勾選框被鎖、native host 查成 Desktop 機碼、Deno 按鈕）。

### 待辦 1：環境區全部改成一鍵安裝（使用者已提、尚未動工）

- 使用者原話（2026-11-04）：「所有環境安裝的部分可不可以都用成點按鈕就直接安裝，不用再去網頁自己載、自己裝，裝的版本就挑穩定又最新的版本，你覺得如何?」我回答贊成；當時 7 天用量 99%，所以只記錄沒動工。使用者尚未回覆「確定要做」，但方向已提出，下一場直接做並回報。
- 現況：ffmpeg、PowerShell 7、faster-whisper、Deno 已是按鈕；只有 Python、Claude Code 是「開下載頁」（`installer/cds/gui_model.py` 的 `DOWNLOAD_PAGES`，`installer/gui.py` 環境區）；git 沒有按鈕（`git` 列 action 為 None）。
- 查證過的事實（2026-11-04）：
  - Claude Code：官方 setup 頁寫「WinGet installations do not auto-update」，`Native installations automatically update in the background`；原生安裝 `irm https://claude.ai/install.ps1 | iex`。winget 的 `Anthropic.ClaudeCode` 是 2.1.302，使用者新裝置已是 2.1.318，較舊。→ 建議用原生安裝，不用 winget。
  - git：winget `Git.Git` 2.56.0.4。
  - Python：winget 每個次版本一個 ID（`Python.Python.3.x`）。這次 `winget search` 輸出被 tail 截斷，**最新 ID 沒看到，動工前要重查**；新裝置實測 Python 3.14.10＋faster-whisper 1.2.1 可用，3.14 是有實測的候選。
- 做法：`INSTALL_ACTIONS` 加 python、git；Claude Code 用原生安裝腳本（`INSTALL_ACTIONS` 是 argv 清單，要確認怎麼呼叫 PowerShell）；`installer/gui.py` 按鈕文字表加項；`DOWNLOAD_PAGES` 留作沒有 winget 時的備案。裝完靠 0.14.2 的 `_ensure_python`／`refresh_path` 不用重開視窗。
- 裝不了、只能開頁的：Chrome 擴充（商店要使用者按）；登入 Claude 由使用者自己做。
- 驗收：測試涵蓋按鈕動作與沒有 winget 的備案；更新 CHANGELOG、VERSION（次版號），發 Release；最終要在全新裝置實測。

### 待辦 2：新裝置端對端確認 0.14.2（等使用者下次測）

- Deno 按鈕裝完環境列是否變 ✅（winget 實裝沒跑過）。
- 不經 `/chrome` 勾選後開對話，② 是否自動變 ✅、重開 Chrome 後能否連上（照官方文件寫的，沒實跑）。
- 視窗開著裝 Python 後按「重新整理」是否可用（只做過 PATH 模擬）。
- 0.14.2 的 exe 沒有下載來跑過（只跑過原始碼的 --selfcheck）。

### 待辦 3：Stock-web（使用者要自己在那場對話交代）

- 5 個腳本超過 800 行還沒拆（exitStrategy.ts 6,588、register.tsx 866、weeklyGoliveCore.ts 839、histRetest.ts 832、simRulesSnapshot.ts 812），行數閘門只管 src/。拆檔要先估用量給使用者同意。

### 已知小問題

- 【共用工作目錄】提醒是比對指令文字，指令裡只要出現 `git add -A` 字樣（例如測試資料）也會跳。同一場對話只跳一次，影響小，未修。

決策：2026-11-04｜YouTube 解挑戰的安裝按鈕裝 Deno 不裝 Node｜使用者說「Node如果比Deno還好就用Node」，查證後 Node 沒有比較好｜yt-dlp wiki/EJS「Deno (recommended) | Enabled by default」、Deno「no file system or network access」、Node 要另外 `--js-runtimes node` 且只有「some permissions restricted」。已裝 Node ≥22 的機器仍算通過。

驗證方式：`py -3 -m unittest discover -s tests`（114 項）、`py -3 installer/install.py verify`。
