# 跨裝置

| 類別 | 放哪裡 | 會不會跨裝置 |
|---|---|---|
| 工具原始碼（規則、skills、hook、安裝器） | 本 repo（推到你自己的 Git 遠端） | 會：各裝置 clone／pull 同一版本 |
| 本機安裝結果 | 各裝置的 `~/.claude/claude-dev-system/`、`skills/cds-*`、settings.json hook、CLAUDE.md 區塊 | **不會自動同步**：每台都要跑 `install` |
| 個人偏好 | 各裝置 `settings.json` 的 permissions、model、language 等 | 不在本工具內，各自設定 |
| 機密 | `.credentials.json`、API 金鑰、`.env.local` | 絕不進本 repo；由各裝置登入或自行放置 |

## 新裝置步驟
1. 安裝 Python ≥3.10、git、Claude Code（並登入）。
2. `git clone <遠端> ; cd claude-dev-system`
3. `python installer/install.py check` → `install` → `verify`（Windows 用 `py -3`）。
4. 重開 Claude Code。
5. 有需要的專案（例如 Stock-web）另外照該專案的新裝置文件設定專案專屬項目（task-board mod、專案 hook）。

## 平台
- Windows：已實測（Windows 11、Python 3.14、Claude Code 2.1.296）。hook 指令以 Git Bash 執行，結尾 `# claude-dev-system` 為註解。
- macOS／Linux：路徑邏輯（`~/.claude`、`CLAUDE_CONFIG_DIR`、正斜線路徑）已寫好，**未實機驗證**。首次使用請跑 `python3 -m unittest discover -s tests -v` 與 `verify` 並回報結果。
