---
name: cds-session-pickup
description: 接手半成品：新對話開頭、接別人或昨天的工作時，從交接紀錄、git、未提交改動重建「做到哪、剩什麼、下一步」；沒有紀錄檔時依可判定條件決定收尾要不要建 PROGRESS.md。任何專案開工第一步使用。
---

# 接手（claude-dev-system；借鏡 pstack 的 session pickup）

1. **找紀錄**：專案根目錄有 `PROGRESS.md`、`HANDOFF.md`、`TODO.md`、`docs/progress.md` 任一 → 讀最後一節（最近日期那節），不讀整檔。
2. **沒有就從 git 重建**：`git log -10 --oneline`、`git status --short`、`git stash list`、`git diff --stat`；沒有 git 的資料夾就列最近修改的 5 個檔（修改時間）。
3. **整理成三行給使用者確認**：已完成／進行中（含未提交或 stash 的檔）／下一步。紀錄與 git 不一致（紀錄說完成但程式沒有、或反過來）要明寫，不要自己挑一邊信。
4. **開工後**：派出、完成、中斷 agent 或需求變動時，當下更新紀錄最後一節；未完成的改動 `git diff > <路徑>.patch` 並把路徑寫進紀錄。
5. **收尾要不要建 PROGRESS.md（可判定，任一成立就建；都不成立就不建、不問）**：這場對話派過 agent；改動跨 ≥3 個檔；使用者說「下次繼續」。內容 5～10 行：做了什麼、沒做完什麼、下一步、怎麼驗證；建好後告訴使用者一句「已建 PROGRESS.md」。
6. 精簡、搬移或合併紀錄時用 `cds-doc-governance` 逐句比對，不可遺漏數字、使用者原話、日期、驗收標準。
7. **PROGRESS.md 固定格式**（新建時照這個，既有的不強改）：最上面是最近一節，每節四段——「做了什麼」「沒做完什麼（含 patch 路徑）」「下一步」「驗證方式」；另有「決策」小節，一行一條「日期｜決定｜原因｜證據（檔案或測試）」，重要決定當下就寫，不等收尾；超過 30 節把舊的搬到 PROGRESS-ARCHIVE.md 並用 progress-diff 比對。
8. **有盤點索引的專案**（`.claude/project-scan.json`）：開工順手跑 `project-scan.py . --check`，改過的檔 >20 個或動到被引用最多的模組 → 重跑盤點；否則沿用舊索引。
