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
| `另一個安裝程序正在執行` | 同一個設定目錄同時只允許一個 install／update／uninstall／web／video 在跑（設定視窗按「套用」也算）。等另一個結束再重跑；程序被強制結束時鎖由系統自動釋放，不用手動清。 |
| 安裝或更新一開始就 ❌ `settings.json …`／`CLAUDE.md …` | 0.27.0 起寫入前會先檢查這兩個檔：settings.json 要是合法 JSON、最外層是物件、沒有 BOM（PowerShell 5.1 的 `Set-Content -Encoding UTF8` 會加 BOM）；CLAUDE.md 要是 UTF-8、本工具的開始與結束標記成對且只有一組。訊息會寫是哪個檔、哪裡不對；修好再跑，這次什麼都沒動。 |
| `verify` 顯示 ❌ hook 用的 Python 不存在 | 安裝時記下的 Python 被移除或搬走，7 個 hook 每次都會失敗。用現在的 Python 跑 `update --python <新路徑>`。 |
| `uninstall` 最後一行是 ❌、結束碼 1；之後 `status`／`verify` 說「上次解除安裝未完成」 | 有 MCP 沒移掉（多半是 `claude` 不在 PATH）。安裝紀錄只留下還沒移掉的 MCP 名稱；處理好之後再跑一次 `uninstall` 會接著移除，或直接重新 `install`。 |
| `uninstall --restore-backup` 說不還原 | 只認安裝那一次留下的備份。安裝前本來沒有 settings.json、或舊安裝更新超過 10 次（0.27.0 前安裝前那份會被擠掉）就沒有可還原的；settings.json 已經是「移除本工具條目後」的樣子，其他備份在 `~/.claude/backups/` 可手動挑。 |
| `~/.claude/state/` 出現 `*.corrupt`、`*.bad-<時間>`、`*.lock` | hook 與 `resgate.py` 讀到壞掉的狀態檔時會把它改名保留（不再用空內容蓋掉）；`.lock` 是寫入時用的空鎖檔。確認不需要後可以刪。 |
| 視窗「將變更」顯示「表單有誤」 | 這次改的數值超出範圍（用量門檻 1～100、記憶體門檻 1～32 等）；訊息會寫是哪一欄。改回合理值即可。 |
| 想完全回到安裝前 | `uninstall --restore-backup`；或從 `~/.claude/backups/claude-dev-system-*` 手動複製。 |
| macOS 用量守門永遠沒輸出 | macOS 的 Claude 登入憑證在鑰匙圈，不在 `~/.claude/.credentials.json`；usage_guard 目前只讀檔案，Mac 上需改讀鑰匙圈才能用（未實作、未驗證）。 |
