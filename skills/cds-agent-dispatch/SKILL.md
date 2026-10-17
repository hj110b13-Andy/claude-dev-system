---
name: cds-agent-dispatch
description: 派 agent 前決定模型（opus／sonnet／haiku）與努力程度（low／medium／high／xhigh）並寫齊派工規格。任何專案在呼叫 Agent 工具派工前使用；專案若有自己的派工 skill，以專案版為準。
---

# 派工模型與努力程度（通用版，claude-dev-system）

## 第一步：判斷任務類型（取最高風險的一項）
讀 `~/.claude/claude-dev-system/config/dispatch-config.json` 的 `dispatch.taskTypes`（沒有就用下表）：

| 類型 | 模型 | 努力 |
|---|---|---|
| A 改核心業務規則、AI 回答流程／提示詞 | opus | high |
| B 多分支合併、解衝突 | opus | high |
| C 研究設計（事先登錄、診斷失敗、重設計；只換參數重跑用 medium） | opus | high |
| D 跨模組新功能（規格已寫清楚） | opus | medium |
| E 單一模組、規格明確的修正 | sonnet | medium |
| F 實際操作驗證 | sonnet | medium |
| G 資料抓取／回填（來源格式已知） | sonnet | medium |
| H 唯讀盤點、整理報告（只列清單用 haiku low） | sonnet | low |
| I 查狀態、grep、讀單一檔 | 不派，自己做 | — |

升級一格：同類已失敗過、影響所有使用者、需跨報告取捨、牽涉權限／隱私。降級一格：規格已寫死、只動文件或測試期望值、重跑既有腳本。

## 第二步：看用量
`python ~/.claude/claude-dev-system/hooks/usage_guard.py --print`。接近門檻時 C、D 降為 opus medium 或 sonnet；超過門檻只派必要的 A、B，其餘排隊。並行數不超過 `dispatch.maxParallelAgents`（專案另有規定從專案）。

## 第三步：填參數與規格
- Agent 工具的 `model`、`effort` 照表填（不支援 effort 的版本就省略）。
- 派工第一行：「（模型／努力程度：X／Y，理由：類型 Z）」。
- 規格七要素：背景與原話、證據、修法方向、不能破壞的行為、可量化驗收、協調資訊、時限＋回報格式（「進度 已完成/總數｜預計還需 N 分（依據）」，交完最終報告就結束）。

## 第四步：事後校正
返工（模型太弱）或浪費（太強）時記一句；同類連 2 次返工升一格、連 3 次輕鬆完成試降一格，改 dispatch-config.json。
