# 相容版本

單一來源：`config/compat.json`（`check`／`verify` 讀它）。

| 項目 | 要求 | 實測 |
|---|---|---|
| Claude Code | ≥2.1.0、<3.0.0 | 2.1.296（Windows） |
| Python | ≥3.10（只用標準庫） | 3.14.4（開發機）；GitHub Actions 的 `tests` 流程每次 push 另跑 3.10、3.12、3.14 |
| 作業系統 | Windows／macOS／Linux | Windows 11 已驗證；macOS、Linux **未實機驗證**（2026-11-12 起單元測試在 GitHub Actions 的 ubuntu-latest、macos-latest 通過，但沒有實機安裝、hook 沒有在 Claude Code 裡跑過） |
| Node.js | 不需要 | — |

## 使用的 Claude Code 官方機制（2.1.296 實測確認）
- 使用者層 `~/.claude/CLAUDE.md`（每個專案都載入）。
- 使用者層 skills：`~/.claude/skills/<名稱>/SKILL.md`（`claude plugin init --help` 亦以此為個人擴充位置）。
- 使用者層 `settings.json` 的 `hooks`，`type: command`，共 7 個事件（唯一來源 `installer/cds/settings_ops.py` 的 `HOOK_SPECS`；這裡原只列 UserPromptSubmit、PostToolUse 兩個）：UserPromptSubmit、PostToolUse、SessionStart、SubagentStart（用 `hookSpecificOutput.additionalContext` 注入上下文）；Stop、SubagentStop（用 `decision: block` 退回）；PreToolUse（matcher `SubagentHandback`，用 `permissionDecision: deny` 退回）。各事件的最低 Claude Code 版本見 README「agent 開工補充與交報告守門」。
- plugin／marketplace：本 repo 不再附任何 mod（task-board 屬 Stock-web 專案，已移回該專案 `tools/claude-setup/`，0.6.3）。

## 設定檔版本
- `manifest.json`、`compat.json`、`dispatch-config.json` 皆有 `schemaVersion`。manifest 遷移在 `installer/cds/manifest.py`（`MIGRATIONS`，目前 0→1→2→3，`MANIFEST_SCHEMA` 是 3；這裡原寫「目前含 0→1 範例」）。
- Claude Code 升到 3.x 時 `check`／`verify` 會標 ❌，需先在新版實測後放寬 `compat.json`。
