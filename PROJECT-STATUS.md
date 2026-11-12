# 專案狀態（v0.27.0，2026-11-12 全方位健檢後）

這份寫「現在是什麼狀態、哪些做完、哪些有限制」。問題清單與逐條處理看 `PROJECT-AUDIT-REPORT.md`；架構看 `docs/ARCHITECTURE.md`；每版改了什麼看 `CHANGELOG.md`；進行中的工作看 `PROGRESS.md`。

## 結論

可以正式使用與長期維護。Windows（實際使用的平台）上自動化驗證全數通過；沒有已知的 P0／P1 問題未處理。兩塊靠人工、沒有自動化測試：設定視窗的畫面操作、外部服務（影片、聯網來源的實際呼叫）。

## 功能完整度

| 功能 | 狀態 | 自動化驗證 |
|---|---|---|
| 安裝、更新、解除安裝、驗證、狀態（`install.py`） | 完成 | 單元測試；舊版 → 新版 → 解除安裝的完整循環 |
| 全域規則（`rules/core.md` 合併進 CLAUDE.md）與 10 個 skill | 完成 | 安裝雜湊與區塊；文件一致性測試 |
| hook：用量守門、查證／建議守門、專案自動化、壓縮後重新開工、agent 開工補充與交報告守門、工具後提醒 | 完成 | 單元測試（各事件端到端的輸出形狀）；實際在這台每天運作 |
| 聯網來源（選用）：MCP 註冊、金鑰、`env` | 完成 | 邏輯有測試；真的呼叫 `claude mcp` 沒有自動化測試 |
| 影片來源（選用）：搜尋、逐字稿、截圖、數據、Gemini 問答、下載 | 完成 | 只有不連網的邏輯有測試（`tools/video.py` 覆蓋率 42%） |
| 設定視窗與 exe、自我更新 | 完成 | 邏輯層有測試（`gui_model.py` 87%、`appdir.py` 88%）；視窗層 `gui.py` 沒有自動化測試，只有不開視窗的 `--selfcheck` |
| 工具：記憶體閘門與延後清單、殘留程序、磁碟清理、專案盤點、依賴圖、文件比對、agent 稽核 | 完成 | 單元測試 |
| 自我測試（`install.py selftest`，11 題無頭對話） | 完成 | 判定邏輯有測試；題目本身要手動跑（花對話額度） |
| 發布：推 tag 自動打包 exe 並附到 Release；平常 push 跑測試 | 完成 | 每次 push 與發布實際執行 |

沒有做到一半的功能。

## 驗證過的環境

| 環境 | 驗證到什麼程度 |
|---|---|
| Windows 11、Python 3.14、Claude Code 2.1.296 | 實機安裝並每天使用；全套測試 488 項通過 |
| Windows（GitHub Actions）、Python 3.10／3.12／3.14 | 全套測試通過（2026-11-12；之後每次 push 都跑） |
| Windows exe（PyInstaller，Python 3.12） | CI 打包＋不開視窗的冒煙測試通過 |
| Linux（GitHub Actions ubuntu-latest、Python 3.12） | **只有單元測試通過**（2026-11-12 第一次跑）；沒有實機安裝、沒有驗證 hook 在 Claude Code 裡觸發 |
| macOS（GitHub Actions macos-latest、Python 3.12） | 同上，**只有單元測試通過**；另外已知 macOS 的登入憑證在鑰匙圈、不在檔案裡，用量守門讀不到用量（`docs/troubleshooting.md`） |

Linux 與 macOS 的單元測試要手動觸發：推到 `ci/all-os/<名稱>` 分支，或在 GitHub 的 `tests` 流程手動執行並勾選。

## 已知限制

**沒有自動化測試的部分**
- 設定視窗的實際操作。0.27.0 改了表單驗證的提示、套用失敗不關窗、開窗自動檢查 exe，這些只有邏輯測試與讀碼。
- 外部服務的實際呼叫：YouTube、Gemini、yt-dlp 下載、語音辨識、Anthropic 用量端點、`claude mcp add`。
- exe 自我更新的實際下載與換檔（邏輯有測試）。

**設計上的取捨**
- exe 沒有程式碼簽章（Windows 第一次開會被 SmartScreen 擋）；Release 附的 `.sha256` 只能防下載損毀。
- hook 寫狀態檔時最多等 0.3 秒的鎖，拿不到就不帶鎖寫——hook 不可以被卡住。極端並發下可能少記幾筆「提醒過了」的狀態（多提醒一次），不會損毀檔案。
- 四個檔超過 800 行沒有拆：`hooks/usage_guard.py`、`installer/cds/gui_model.py`、`tools/video.py`、`installer/gui.py`。hook 與工具要能單檔獨立執行。
- `tools/depgraph.py` 要與 `tools/project-scan.py` 放在同一個資料夾才能用（共用同一份走訪與依賴解析）。
- 「用量守門」開關關的是整支 hook 的 7 個事件。只想關用量提醒、保留其他守門，目前沒有這個選項（調高門檻可以達到接近的效果）。

**已知技術債**
- 「全域設定＋專案覆蓋」的讀法在 `tools/procs.py`、`tools/resgate.py`、hook 各有一份（驗證規則略有不同：resgate 要大於 0，另外兩份接受 0）。
- `tools/cleanup.py` 判斷別場對話的暫存能不能刪，只看「24 小時內有沒有動過」，沒有辦法知道那場對話是不是還開著。
- `tools/video.py` 的下載沒有大小上限、轉檔與語音辨識沒有逾時。
- `tools/progress-diff.py` 的「疑似改寫」只認數字類與否定字被改；同義詞替換會被列成「找不到」（寧可多報）。
- `tools/procs.py` 對 PowerShell 工具開出的孤兒程序，在指定專案時認不出來（命令列裡沒有工作資料夾）。

## 維護時要知道的

- 改完跑 `python -m unittest discover -s tests`；更新 `config/VERSION` 與 `CHANGELOG.md`；發布照 `CLAUDE.md`〈改這個 repo 時〉。tag 必須等於 `v`＋`config/VERSION`，否則發布流程會擋下。
- 加新的 hook 標籤：要同時加進 `rules/workflow.md`〈hook 標籤對照〉（有測試會擋）。
- 改 `rules/core.md`：`core-detail.md` 要同步；巡檢的固定 prompt 三處要逐字相同（有測試會擋）。
- 改 README、docs 裡的數字或清單：`tests/test_docs_consistency.py` 會比對程式的唯一來源。
- 模組間出現循環匯入：`tests/test_project_gate.py` 會擋。
- 改到被多處引用的介面（hook 與 `tools/` 之間的動態載入、`commands` 給視窗用的函式）前，先看 `docs/ARCHITECTURE.md` 第四節列的跨檔引用。

## 數字（2026-11-12）

測試 488 項（健檢前 187）；覆蓋率 72%（健檢前 61%）；依賴循環 0 組；受版控的 Python 檔 46 個。
