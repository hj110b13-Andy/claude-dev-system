---
name: cds-doc-governance
description: 文件與規則治理：精簡、搬移、合併 CLAUDE.md／PROGRESS／規則檔時逐句比對不遺漏，維持規則分層。要瘦身或重排任何紀錄、規則、交接文件時使用。
---

# 文件治理（claude-dev-system）

1. 動手前先存改前版本（或確認 git 有乾淨的 HEAD 版本）。
2. 改寫原則：使用者原話、根因、數字、驗收標準、日期只能移位置不能刪；只合併重複、縮短措辭、把舊日誌搬封存檔。
3. 改完逐句比對：
   - 檔案版：`python ~/.claude/claude-dev-system/tools/progress-diff.py --old-file <改前> --new <改後> --new <封存檔>`
   - git 版：`python ~/.claude/claude-dev-system/tools/progress-diff.py --old-ref HEAD --git-path PROGRESS.md --new PROGRESS.md --new PROGRESS-ARCHIVE.md`
4. 逐條判定找不到的句子：改寫（寫出新位置）或遺漏（補回）；全部處理完才 commit，比對結果寫進 commit 訊息。
5. 搬到封存檔的重要教訓，主檔留一條雷區索引：「症狀關鍵字 → 一句話結論 → 日期＋可 grep 到原文的片段」。
6. 規則放對層：通用→全域（本工具 rules/）；專案專屬→專案 CLAUDE.md；不可把專案特例升格成全域規則。
