# 問題清單（還開著的；2026-11-12 全方位健檢後）

盤點工具與健檢找到的問題全部列在 `PROJECT-AUDIT-REPORT.md` 第 B 節（116 條，108 條已修）。這裡只留**還開著的**，每條寫：位置、證據、原因、影響、嚴重度、修法、預期改善、驗證方式、回復方式。

重整決定：**不做分階段重整**（2026-11-12；健檢文件要求「避免不必要的大規模重構」，四個大檔不拆）。記在 `.claude/project-scan.json` 的 `refactorDecision`，之後不再問。

| # | 位置 | 證據 | 原因 | 影響 | 嚴重度 | 修法 | 預期改善 | 驗證方式 | 回復方式 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `hooks/usage_guard.py`（2,217 行）、`installer/cds/gui_model.py`（1,360）、`tools/video.py`（1,209）、`installer/gui.py`（1,125） | `docs/PROJECT-INVENTORY.md`〈問題清單〉 | hook 與工具要能單檔獨立執行；視窗層與模型各一檔 | 閱讀與審查成本高 | 低（維護成本） | 之後改到某一塊時順手把那一塊抽成同資料夾的小模組，不做一次性大拆 | 單檔行數下降 | 全套測試、`project-scan.py --max-cycles 0` | `git revert` 那個 commit |
| 2 | `tools/procs.py` load_cfg、`tools/resgate.py` load_cfg、`hooks/usage_guard.py` `_section` | 稽核 TA-20：三份各自實作「全域設定＋專案覆蓋」，resgate 要 >0、另兩份 >=0 | 三支都是獨立腳本；hook 的測試靠改模組常數隔離，另兩支讀環境變數 | 要改讀法得改三處 | 低 | 先把 hook 的測試隔離方式改成環境變數，再抽共用函式 | 一個來源 | 三個模組既有測試 | `git revert` |
| 3 | `installer/gui.py` 全檔 | 覆蓋率 0% | tkinter 視窗沒有無頭測試 | 視窗層的回歸只能靠人工發現 | 中（測試缺口） | 用 `tkinter` 建 App 後呼叫方法、不進 mainloop 的冒煙測試（要先確認 CI 的 Windows runner 能開 Tk） | 視窗層有基本的自動化驗證 | 新測試在 CI 通過 | 刪掉新測試 |
| 4 | `tools/video.py`（覆蓋率 42%） | 連網的路徑沒有測試 | 不用使用者的金鑰與額度 | yt-dlp、YouTube API、Gemini 的介面變動不會被測試抓到 | 中（測試缺口） | 錄一份回應樣本當固定資料，測解析那一段 | 介面變動能被抓到 | 新測試 | 刪掉新測試 |
| 5 | `tools/cleanup.py` plan_temp | 稽核 TA-10 | 沒有可靠方法知道別場對話是否還開著 | 別場閒置超過 24 小時的對話暫存可能被列為可刪（要使用者同意才刪） | 低 | 待 Claude Code 提供可查的工作階段清單再做 | — | — | — |
| 6 | `tools/video.py` 下載、轉檔 | 稽核 TA-18 | 沒有大小上限與逾時 | 極長的影片會跑很久 | 低 | 有實測數據再定上限 | — | — | — |
| 7 | macOS／Linux | `config/compat.json` | 沒有實機 | 只有單元測試通過，實際安裝與 hook 觸發沒有驗證過 | 中（如果要在那些平台用） | 在實機照 `docs/cross-device.md` 走一遍並回報 | 平台標成已驗證 | `verify` 全 ✅、hook 實際觸發 | — |
