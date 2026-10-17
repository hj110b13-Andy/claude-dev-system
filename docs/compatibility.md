# 相容版本

單一來源：`config/compat.json`（`check`／`verify` 讀它）。

| 項目 | 要求 | 實測 |
|---|---|---|
| Claude Code | ≥2.1.0、<3.0.0 | 2.1.296（Windows） |
| Python | ≥3.10（只用標準庫） | 3.14.4 |
| 作業系統 | Windows／macOS／Linux | Windows 11 已驗證；macOS、Linux **未驗證** |
| Node.js | 不需要 | — |

## 使用的 Claude Code 官方機制（2.1.296 實測確認）
- 使用者層 `~/.claude/CLAUDE.md`（每個專案都載入）。
- 使用者層 skills：`~/.claude/skills/<名稱>/SKILL.md`（`claude plugin init --help` 亦以此為個人擴充位置）。
- 使用者層 `settings.json` 的 `hooks`（UserPromptSubmit、PostToolUse，`type: command`，`hookSpecificOutput.additionalContext` 注入上下文）。
- plugin／marketplace（`claude plugin validate hooks` 通過）：只用於專案專屬的 task-board mod。

## 設定檔版本
- `manifest.json`、`compat.json`、`dispatch-config.json` 皆有 `schemaVersion`。manifest 遷移在 `installer/cds/manifest.py`（`MIGRATIONS`，目前含 0→1 範例）。
- Claude Code 升到 3.x 時 `check`／`verify` 會標 ❌，需先在新版實測後放寬 `compat.json`。
