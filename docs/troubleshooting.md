# 故障排除

| 症狀 | 原因與處理 |
|---|---|
| `verify` 顯示 ❌ 檔案雜湊不一致 | 已安裝檔被改或 repo 有新 commit 但沒 update。跑 `update`；要保留自己的修改就先合併 `.new` 再 `update --force`。 |
| `verify` 顯示 ❌ hook 不存在 | settings.json 被其他工具改寫。跑 `update` 重新加入。 |
| hook 有 2 條重複 | 手動複製過指令。刪掉沒帶 `# claude-dev-system` 的那條，或跑 `update`（會先清掉本工具舊條目再加）。 |
| 新對話看不到 `cds-*` skill | 要重開對話／VSCode 視窗；確認 `~/.claude/skills/cds-*/SKILL.md` 存在、frontmatter `name` 與資料夾同名（verify 會檢查）。 |
| `CLAUDE.md 有開始標記但找不到結束標記` | 手動編輯時刪掉了 `<!-- claude-dev-system:end -->`。補回結束標記（或刪掉整個區塊）後再執行。 |
| 用量守門沒有提醒 | `python ~/.claude/claude-dev-system/hooks/usage_guard.py --print` 手動查；沒輸出代表憑證或端點失效（腳本設計成安靜失敗、不擋操作）。門檻在 `~/.claude/claude-dev-system/config/dispatch-config.json`。 |
| Windows 輸出中文亂碼 | 主控台是 cp950。安裝器已強制 UTF-8 輸出；其他腳本可設 `PYTHONIOENCODING=utf-8`。 |
| `需要 Python 3.10 以上` | 用 `py -3.12`（或更新）執行；hook 會記住執行安裝器的 Python 路徑。 |
| Python 移除或升級後 hook 失效 | hook 指向舊 Python 路徑。用新 Python 跑 `update --python <新路徑>`。 |
| `manifest schemaVersion … 比本安裝器支援的新` | 這台的 repo 比安裝時舊。`git pull` 後再執行。 |
| 想完全回到安裝前 | `uninstall --restore-backup`；或從 `~/.claude/backups/claude-dev-system-*` 手動複製。 |
