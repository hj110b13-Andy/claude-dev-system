# 規則分層

| 層 | 位置 | 載入方式 | 內容 |
|---|---|---|---|
| 1. 全域核心 | `core.md` → 安裝時合併進 `~/.claude/CLAUDE.md` 標記區塊 | 每則訊息都載入，所以必須短（目標 ≤ 40 行） | 跨專案都成立的工作原則、什麼時候去讀第 2 層 |
| 2. 全域細則 | 本資料夾其他 `.md`，安裝到 `~/.claude/claude-dev-system/rules/` | 不自動載入；核心規則指名「做 X 時先讀 Y」 | 派工、驗證、重構、文件治理、用量收尾的完整流程 |
| 2'. 全域 skills | `skills/cds-*`，安裝到 `~/.claude/skills/` | Claude Code 依 description 按需載入 | 可直接照做的步驟清單 |
| 3. 專案規則 | 各專案 `CLAUDE.md`、`.claude/` | 專案內自動載入 | 業務規則、資料模型、專案命令、專案門檻 |
| 4. 任務派工規格 | 派 agent 時的指示 | 只對該 agent | 該次任務的驗收與限制 |

衝突時**越下層越優先**（專案規則 > 全域規則）；專案的特殊需求不可升格成全域規則（規格 11.5）。
原 Stock-web `docs/claude-rules/global-workflow.md`（規則二、三、六～十二、派工規格品質、git 協作）已於 0.2.0 去專案化並分入 `workflow.md`（二、三、六～九）、`token-efficiency.md`（十）、`safe-refactor.md`（十一）、`doc-governance.md`（十二）、`agent-dispatch.md`（派工規格品質、git 協作）；各檔後半「完整規則原文」保留使用者原話、數字、日期。
