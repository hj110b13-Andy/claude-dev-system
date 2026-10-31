# claude-dev-system（給在這個 repo 目錄裡工作的 Claude Code 看）

這個 repo 是「可跨裝置安裝的 Claude Code 全域優化系統」。使用者在新裝置 clone 後，通常會直接說「幫我安裝這套系統」。

## 使用者要安裝或更新時

1. **先讀 `README.md` 的「新裝置安裝流程（給在新裝置上執行安裝的 Claude Code 看）」**，照它的 1–12 步做（第 2 步可改用設定視窗 `install.py gui`）。
2. 流程裡每一個標「**問：**」的項目（聯網來源、哪些金鑰、firecrawl、影片來源與 faster-whisper、Claude in Chrome、PowerShell 7、系統碼頁、訂閱方案）**都要停下來問使用者**，一次問一組即可，不可自行決定或全部跳過；使用者沒提到的就當「不要」，但要讓他看到清單。
3. 金鑰由使用者**自己在終端機**輸入 `install.py web --key 名稱=值`；不要請他貼在對話裡，也不要把金鑰值印出來。
4. 每步完成跑 `python installer/install.py verify`（Windows `py -3`），全 ✅ 才算完成，然後請使用者重開 Claude Code 對話。
5. 已裝過舊版的機器：`git pull` → `update --with-web --with-video`（依他原本啟用的）→ `verify`。

## 改這個 repo 時

- 規則在 `rules/`（`core.md` 會合併進使用者的全域 CLAUDE.md，要短；細則放 `web-sources.md` 等）；安裝器在 `installer/`（只用標準庫）；工具在 `tools/`。
- 改完：`python -m unittest discover -s tests`、更新 `config/VERSION` 與 `CHANGELOG.md`（每條寫觸發的使用者原話或測試）、本機 `update` 後 `verify`，再 commit／push。manifest 結構有變要 +1 `MANIFEST_SCHEMA` 並加遷移。
- 金鑰、`local.json`、`~/.claude.json` 永遠不進 repo。
