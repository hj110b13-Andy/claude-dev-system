---
name: cds-project-init
description: 新專案立規矩：第一次在一個資料夾開工、沒有專案 CLAUDE.md 而且算得上專案（git 或 ≥10 個原始碼檔）時自動執行——寫專案 CLAUDE.md（技術棧、分層、新增功能怎麼接、保護規則）、建 PROGRESS.md 與驗證地圖空殼、把依賴閘門裝進測試，之後每次改動靠閘門守住不退化。小腳本資料夾不做。
---

# 新專案立規矩（claude-dev-system；自動觸發，做完告訴使用者一句，不問）

**觸發（可判定，全部成立才做）**：資料夾沒有 `CLAUDE.md`；`py -3 ~/.claude/claude-dev-system/tools/project-scan.py . --summary` 印出「算專案」；不是 claude-dev-system 自己。任一不成立就跳過，什麼都不建、不問。

1. **掃描**：`project-scan.py .` 產出 `docs/PROJECT-INVENTORY.md` 與 `.claude/project-scan.json`。全新空專案（0 個原始碼檔但有 git）也做，之後索引會隨檔案長大。
2. **寫專案 CLAUDE.md**（短，30 行內，只寫全域規則沒有的）：技術棧與版本、啟動與測試指令、資料夾分層與依賴方向（例：`lib` 不可引用 `app`）、新增功能的接法（新增模組→實作既有介面→補測試→登記）、哪些核心檔要改必須先說明原因、業務規則放哪裡、文件第二節的保護規則三條：不得因為看起來多餘就刪、改既有行為要獨立列出、不可逆操作先問。
3. **裝閘門**：JS／TS 專案把 `depgraph.py <root> --max-cycle-files <目前循環數> --forbid <分層規則>` 加進 `npm test` 或 CI；Python 專案把 `project-scan.py --check` 與循環數檢查加進測試。門檻用「現在的數字」，只准降不准升。
4. **建空殼**：`PROGRESS.md`（第一節：今天建立、下一步）、`.claude/skills/verify-<專案>/SKILL.md` 只在有畫面或可啟動服務時用 `cds-verify-app` 生成，純函式庫不建。
5. **收尾一句話**：「已替這個專案立好規矩：CLAUDE.md、盤點、閘門（循環 N、分層 M 條）、PROGRESS.md」。不列細節、不問要不要。
6. **之後**：每次改動照全域規則走（波及範圍、驗證地圖、閘門）；單檔超過 800 行或某模組被 ≥15 個檔引用時提一句「該拆了」並當下小範圍拆，不累積成大掃除。
