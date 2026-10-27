# 跨裝置

| 類別 | 放哪裡 | 會不會跨裝置 |
|---|---|---|
| 工具原始碼（規則、skills、hook、安裝器） | 本 repo（推到你自己的 Git 遠端） | 會：各裝置 clone／pull 同一版本 |
| 本機安裝結果 | 各裝置的 `~/.claude/claude-dev-system/`、`skills/cds-*`、settings.json hook、CLAUDE.md 區塊 | **不會自動同步**：每台都要跑 `install` |
| 個人偏好 | 各裝置 `settings.json` 的 permissions、model、language 等 | 不在本工具內，各自設定 |
| 機密 | `.credentials.json`、API 金鑰、`.env.local` | 絕不進本 repo；由各裝置登入或自行放置 |
| 聯網來源 | 定義 `config/web-sources.json`、規則 `rules/web-sources.md` 在 repo；**是否啟用、金鑰、開關偏好**在各裝置 `~/.claude/claude-dev-system/config/local.json` 與 `~/.claude.json` | 定義會同步；啟用與金鑰每台各自 `install --with-web`／`web --key …` |
| 影片來源 | `tools/video.py`、`config/video.json` 在 repo；pip 套件、ffmpeg、faster-whisper、快取、`youtube`／`gemini` 金鑰在各裝置 | 每台各自 `--with-video`（pip）＋裝 ffmpeg；金鑰同上 |

## 新裝置步驟
1. 安裝 Python ≥3.10、git、Claude Code（並登入）。
2. `git clone https://github.com/hj110b13-Andy/claude-dev-system.git ; cd claude-dev-system`（私有 repo，2026-10-18 建立；要先 `gh auth login` 或用有權限的帳號）
3. `python installer/install.py check` → `install --with-web --with-video` → `verify`（Windows 用 `py -3`）。金鑰（`cwa`、`moenv`、`openaq`、`tdx_id`、`tdx_secret`、`tavily`、`youtube`、`gemini`）在這台另外 `install.py web --key …`；影片要另裝 ffmpeg（與選用的 faster-whisper）；Claude in Chrome 要裝擴充並打 `/chrome`。完整的選用決策清單見 README「新裝置安裝流程」。
4. 重開 Claude Code。
5. 有需要的專案（例如 Stock-web）另外照該專案的新裝置文件設定專案專屬項目（task-board mod、專案 hook）。

## 平台
- Windows：已實測（Windows 11、Python 3.14、Claude Code 2.1.296）。hook 指令以 Git Bash 執行，結尾 `# claude-dev-system` 為註解。
- macOS／Linux：路徑邏輯（`~/.claude`、`CLAUDE_CONFIG_DIR`、正斜線路徑）已寫好，**未實機驗證**。首次使用請跑 `python3 -m unittest discover -s tests -v` 與 `verify` 並回報結果。
