---
name: cds-safe-refactor
description: 安全重構流程：建立基準與快照、小步可回復、證明行為不變、依賴循環閘門。要拆檔、抽常數、解循環依賴、合併重複邏輯或刪除疑似無用程式時使用。
---

# 安全重構（claude-dev-system）

1. **基準**：記錄改前測試／型別／建置結果；`python ~/.claude/claude-dev-system/tools/depgraph.py <root> --json <暫存>/before.json`（JS／TS 專案；路徑別名用 `--alias @/=<root>`）。
2. **保護措施**：替要動的模組建立固定輸入→固定輸出的比對（快照、逐值比對腳本）；改動前先跑一次確認可重現（兩次執行逐值相同）。
3. **小步**：每批只做一種變更、獨立 commit、可單獨 revert。
4. **行為不變**：改後重跑比對，逐值相同才算通過；有意改變的行為另開 commit 並列清單。
5. **閘門**：`depgraph.py <root> --max-cycle-files <基準>` 不可上升；分層規則 `--forbid lib:app,components`。
6. **刪除**：先 grep 所有呼叫端（含腳本、排程、測試、文件），刪後全套檢查。
7. **盤點文件**：`moduleInventory.py <root> --out <文件路徑>` 重產模組清單（自動產生檔不手改）。

細則：`~/.claude/claude-dev-system/rules/safe-refactor.md`。
