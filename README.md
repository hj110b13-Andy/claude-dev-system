# claude-dev-system

把 Stock-web 專案系統優化中「成熟且驗證過」的通用流程，封裝成可跨專案、跨裝置安裝的 Claude Code 全域工具。
版本見 `config/VERSION`（目前 0.9.5），相容範圍見 `config/compat.json`，變更見 `CHANGELOG.md`。

## 內容與分層

| 目錄 | 內容 | 安裝到（`<CLAUDE_HOME>`＝`~/.claude`） |
|---|---|---|
| `rules/` | 通用規則（分層說明見 `rules/README.md`）；`core.md` 是唯一會進 CLAUDE.md 的部分 | `claude-dev-system/rules/`；`core.md` 另合併進 `CLAUDE.md` 標記區塊 |
| `skills/` | `cds-agent-dispatch`、`cds-safe-refactor`、`cds-doc-governance`、`cds-feedback-audit`、`cds-blast-radius`、`cds-verify-app`、`cds-session-pickup`（皆有 frontmatter） | `skills/<名稱>/`（Claude Code 原生個人 skill 位置） |
| `hooks/usage_guard.py` | 用量守門 hook（通用版；門檻讀設定檔） | `claude-dev-system/hooks/`，並在 `settings.json` 註冊 UserPromptSubmit／PostToolUse |
| `tools/` | `depgraph.py`（依賴圖／循環閘門）、`moduleInventory.py`（模組盤點）、`progress-diff.py`（文件瘦身逐句比對）、`video.py`（影片：搜尋、逐字稿、截圖、數據、Gemini 問答；選用，需 `--with-video`）；不寫死路徑，全用參數 | `claude-dev-system/tools/` |
| `config/` | `VERSION`、`compat.json`、`dispatch-config.json`（用量門檻、方案期間、模型表；專案 `.claude/dispatch-config.json` 優先於全域）、`web-sources.json`（聯網來源：免金鑰搜尋 MCP 與 WebSearch 上限 env，選用）、`video.json`（影片來源：要 pip 的套件與 video.py 預設值，選用） | `claude-dev-system/config/`（dispatch-config 可自行修改，更新時保留；本機金鑰與開關在 `local.json`，不進 repo） |
| `installer/` | `install.py`＋`cds/` 模組（只用 Python 標準庫） | — |
| `tests/` | 安裝器與工具的自我測試 | — |
| `docs/` | 安裝、更新、解除安裝、跨裝置、故障排除、相容版本 | — |

**全域只放通用能力**；業務規則、資料模型、專案命令留在各專案 CLAUDE.md（規格 10.1）。專案規則與全域規則衝突時以專案為準。
本工具**不宣稱**靠 CLAUDE.md 就能控制所有行為：CLAUDE.md 區塊只是載入給模型的指引；真正自動執行的只有 hook（用量守門）。

## 必要條件

- Python ≥ 3.10（安裝器、hook、工具都只用標準庫；選用的影片來源例外，`--with-video` 會 pip 裝 yt-dlp 等）
- git（從版本庫取得本工具）
- Claude Code ≥ 2.1.0、< 3.0.0（實測 2.1.296）
- Node.js：本工具不需要

## 安裝

```bash
git clone https://github.com/hj110b13-Andy/claude-dev-system.git ~/Documents/Claude/claude-dev-system   # 位置可自選
cd ~/Documents/Claude/claude-dev-system
python installer/install.py check      # Windows 用 py -3 代替 python
python installer/install.py install
python installer/install.py verify     # 全部 ✅ 才算完成；重開 Claude Code 對話後生效
```

安裝會做：①備份 `settings.json` 與 `CLAUDE.md` 到 `~/.claude/backups/claude-dev-system-<時間>*`；②複製規則／工具／hook／設定到 `~/.claude/claude-dev-system/`、skills 到 `~/.claude/skills/cds-*`；③在 `settings.json` 只**新增**指令結尾帶 `# claude-dev-system` 的 hook（若已有你自己的 `usage_guard.py` hook 就不重複註冊、不寫檔）；④在 `CLAUDE.md` 末端加 `<!-- claude-dev-system:begin … -->`～`<!-- claude-dev-system:end -->` 區塊，區塊外一字不動；⑤安裝紀錄（版本、每個檔的雜湊、加了哪些條目）寫在 `~/.claude/claude-dev-system/manifest.json`。
不碰 `permissions`、`model`、`language`、`statusLine`、`enabledPlugins`、其他 hooks 與 `~/.claude/commands/`。不會把任何金鑰或 `.credentials.json` 打包進工具。
細節：`docs/install.md`。

## 設定視窗（不用打指令）

```bash
python installer/install.py gui        # Windows：py -3 installer/install.py gui
```
所有選用項目、金鑰（框內顯示目前值、可測試、可填「哪個帳號申請的」備註）、用量守門開關與門檻、目前用量（5 小時／7 天 %）、背景任務巡檢（每 N 分鐘）、WebSearch 上限、下載資料夾、Claude in Chrome 都在視窗裡改；底下會列「將變更 N 項」，按「套用」才動，按「取消」回到實際狀態。開啟與套用後都重讀真實檔案，畫面不會和實際不一樣。缺 ffmpeg／PowerShell 7／faster-whisper 有安裝按鈕。打包成 exe 與視窗內更新在下一版。

## 執行檔（不用裝 Python 也能開設定視窗；Windows）

從 [Releases](https://github.com/hj110b13-Andy/claude-dev-system/releases/latest) 下載 `claude-dev-system-settings.exe`，直接開。第一次 Windows SmartScreen 會擋（沒有程式碼簽章）：按「其他資訊」→「仍要執行」。
- exe 內含一份規則／工具／skill 快照；頂端「檢查更新」會比對 GitHub 的版本，有新版就下載到 `~/.claude/claude-dev-system/app/`，之後按「套用」寫進 Claude Code，不用換 exe。只有安裝器程式碼本身有變（視窗功能）才需要到 Releases 抓新 exe，視窗會提示。
- hook 與影片工具仍需要系統有 Python ≥3.10（exe 內建的 Python 不能代替）；環境區會顯示找到的是哪個 Python，沒有就有「開下載頁」按鈕。
- 自己打包：`py -3 -m pip install pyinstaller && py -3 installer/build_exe.py`，產物在 `dist/`。推 `v*` 標籤時 GitHub Actions 會自動打包並附在 Release。

## 自我測試（確認 Claude Code 真的會自己用這些工具）

```bash
python installer/install.py selftest --list          # 列九題
python installer/install.py selftest                 # 全跑（約 20～40 分鐘、九場短對話的用量；Chrome 題要瀏覽器開著）
python installer/install.py selftest --only video --only live-data
```
每題在全新無頭 `claude -p` 對話裡只給問題、不提工具名，讀它實際呼叫的工具與 `config/selftest.json` 的預期比對（例如停車場題要先打 TDX 再跨索引、即時數值題不得用 firecrawl 抓頁、影片動作題要走 Gemini `ask`）。改了規則就跑一次；視窗核心區也有同一顆按鈕。

## 選用：聯網來源

```bash
python installer/install.py update --with-web            # 放寬內建 WebSearch 上限＋UTF-8 env＋註冊免金鑰 MCP（搜尋 parallel、exa；文件 context7、deepwiki、mslearn）
python installer/install.py web --key cwa=… --key moenv=… --key openaq=… --key tdx_id=… --key tdx_secret=… --key tavily=… --enable tavily
python installer/install.py web --key exa=… --key context7=… --key parallel=… --key firecrawl=…   # 搜尋類金鑰預設「免費優先」：免金鑰版與 <名稱>-key 版並存，規則撞限流才用 -key；--key-mode exa=always 改為一律用金鑰
python installer/install.py web --enable firecrawl       # 選用：JS 頁面抓取，與 parallel 重疊，預設關
```
預設不啟用。用官方 `claude mcp add --scope user` 註冊，不覆蓋你自己同名的 MCP 或 env；`web --off` 或 `uninstall` 只移除本工具登記過的。規則 `rules/web-sources.md` 列出實測過的免金鑰開放 API（天氣、空氣品質、地震、潮汐、匯率、加密貨幣、台股／美股、全球新聞、論文、假日、百科、地理編碼、航班位置、停車場）、社群論壇與程式難題的查法、查證型回答格式、教操作前先核對畫面。細節：`docs/web-sources.md`。

## 選用：影片來源

```bash
python installer/install.py update --with-video          # pip 裝 yt-dlp、youtube-transcript-api；tools/video.py 可用
python installer/install.py web --key youtube=… --key gemini=…   # 選用：YouTube Data API（數據、留言）、Gemini（真的看畫面）
python ~/.claude/claude-dev-system/tools/video.py setup  # 檢查 ffmpeg、faster-whisper、金鑰（Windows 用 py -3）
```
讓 Claude 找影片、拿逐字稿（字幕優先，沒字幕用本機 faster-whisper）、切關鍵畫面或指定時間點截圖、錄一段進行中的直播、查觀看數與留言、用 Gemini 逐幀看影片、使用者要存檔時最高畫質下載；YouTube 以外的網站與本機 mp4 同一套。全部免費，不裝第三方 YouTube MCP。細節與金鑰註冊步驟：`docs/video.md`。

## 新裝置安裝流程（給在新裝置上執行安裝的 Claude Code 看）

照順序做；**每個「問」都要停下來問使用者，不可自行決定**。

1. `check` → 缺 Python ≥3.10、git、`claude` 指令任一就先請使用者裝好。
2. 先問使用者要用**設定視窗**還是逐項指令：視窗 → `python installer/install.py gui`（或直接從 Releases 下載 exe，見「執行檔」節），裡面有同樣的選項與金鑰輸入框，使用者自己勾完按套用即可，下面第 3～10 步只需在視窗裡確認；指令 → 繼續往下。
3. **問：要不要啟用聯網來源？**（建議要；不啟用則只有規則沒有工具）→ 要就 `install --with-web`，否則 `install`。
4. **問：有哪些金鑰要填？** 逐一列出，使用者有的才填，沒有的跳過、功能自動退回免金鑰來源：
   | 金鑰名 | 用途 | 沒填的影響 |
   |---|---|---|
   | `cwa` | 中央氣象署：台灣鄉鎮預報、潮汐、地震報告、警特報 | 天氣退回 Open-Meteo（全球模式），潮汐只能用農曆推算 |
   | `moenv` | 環境部：台灣各測站官方空品 | 退回 Open-Meteo 模式值 |
   | `openaq` | OpenAQ：國外官方測站空品 | 同上 |
   | `tdx_id`＋`tdx_secret` | 交通部 TDX：停車場平面／立體、車位、費率 | 停車場只能靠網頁 |
   | `tavily` | 搜尋＋擷取＋整站爬（填了要加 `--enable tavily`） | 少一個搜尋索引；可改免金鑰模式 `--enable tavily` 不填金鑰 |
   | `exa`、`context7`、`parallel`、`firecrawl` | 搜尋／文件／抓頁的「加大額度」金鑰，全部免費（exa 每月 $10、context7 1,000 次、parallel 註冊送 $20 一次性、firecrawl 1,000 credits／月）；預設免費優先，撞限流才用 | 完全不影響功能，只是免金鑰的限流較緊 |
   | `youtube` | YouTube Data API：觀看／按讚／留言數、熱門留言、日期篩選搜尋（影片來源用） | 影片仍能搜、拿逐字稿、截圖；只少數據與留言 |
   | `gemini` | Gemini：真的逐幀看影片、招牌文字、無聲影片（影片來源用） | 只能靠逐字稿＋截圖理解影片 |
   金鑰由使用者**自己在終端機**輸入 `web --key 名稱=值`，不要請使用者貼在對話裡。Google 兩把的註冊步驟（含第一次進 Google Cloud 會遇到的兩步驟驗證與條款畫面）在 `docs/video.md`；**要教使用者點哪裡之前，先用 Claude in Chrome 開到那個畫面核對**（規則第 10 節），不可憑記憶寫步驟。
5. **問：要不要關 firecrawl？**（0.7.0 起預設開，只當讀整頁第三步；不想要就 `web --disable firecrawl`）。
6. **問：要不要啟用影片來源？**（讓 Claude 看 YouTube／網路影片／本機 mp4 的逐字稿與畫面）→ 要就 `update --with-video`（pip 裝 yt-dlp 等）；需要 ffmpeg（Windows `winget install Gyan.FFmpeg`）；再問 **要不要裝 faster-whisper**（沒字幕的影片才需要；`python -m pip install faster-whisper`，NVIDIA 顯卡另加 `nvidia-cublas-cu12 nvidia-cudnn-cu12`；體積約 1.5GB）。`youtube`／`gemini` 金鑰回到第 3 步的表。
7. `verify` 全 ✅ 才算完成；請使用者**重開 Claude Code 對話**。
8. **問：要不要啟用 Claude in Chrome？**（開網頁看狀況、操作需登入的網站、FB 社團、測自己的網站都靠它）→ 要就請使用者裝 Chrome 擴充「Claude in Chrome」、同帳號登入、在對話打 `/chrome` 開「Enabled by default」。這不是安裝器能做的。
9. **問：要不要裝 PowerShell 7？**（Windows 建議要；5.1 的 JSON 中文亂碼、`Get-Content` 編碼、不支援 `&&`／三元運算子等坑在 7 全部消失，Claude Code 會自動改用它）→ `winget install --id Microsoft.PowerShell --source winget --installer-type wix`（**要 MSI 版**，Store 版 Claude Code 偵測不到；會跳 UAC）。PowerShell 自身走 Microsoft Update 更新是安裝預設；若使用者想讓 Windows Update 一併接收其他 Microsoft 產品更新，請他自己到「設定 → Windows Update → 進階選項」打開，Claude 不代改。裝完重開 Claude Code。
10. **告知（不代做）：Windows 系統碼頁**。安裝器已用 env 修好 Python 子程序的中文輸出；若使用者還常遇到 PowerShell 5.1 讀無 BOM 檔亂碼，可自行開啟 Windows「Beta: 使用 Unicode UTF-8 提供全球語言支援」並重開機；副作用與取捨見 `rules/web-sources.md`「Windows 亂碼的三個根源與修法」。Claude 不可代改系統設定。
11. **問：用量門檻要設多少？** `config/dispatch-config.json` 的 `usageThresholdPct` 預設 5 小時 85%、7 天 97%；沒到門檻完全不提示也不動作，到了才注入收尾提醒。Max 方案的人常改 95／99。直接改兩個數字即可（0.7.0 起沒有方案概念），安裝器之後 update 會保留他的版本。
12. 已裝過舊版的機器：`git pull` → `update --with-web --with-video` → 補金鑰 → `verify`。

## 更新

```bash
git pull
python installer/install.py status     # 看已安裝版本與 repo 版本
python installer/install.py update
python installer/install.py verify
```

更新前會再備份一次。你改過的本工具檔案（例如 `dispatch-config.json`）或 CLAUDE.md 區塊會**保留**，新版放在旁邊的 `.new` 檔讓你自己合併；確定要覆蓋加 `--force`。降版需 `--force`。細節：`docs/update.md`。

## 解除安裝

```bash
python installer/install.py uninstall                 # 只移除帶標記的條目、區塊與本工具的檔案
python installer/install.py uninstall --restore-backup  # 另外用第一次安裝前的備份還原 settings.json
```

會印出移除了什麼；你改過的本工具檔案會保留（`--force` 才刪）。若移除後的 settings.json 與安裝前備份逐鍵相等，直接還原原檔（連排版都一樣）。細節：`docs/uninstall.md`。

## 跨裝置

本機安裝**不會**自動同步到其他電腦。做法：把本 repo 推到你自己的 Git 遠端（私人庫即可）→ 新裝置 clone → `install` → `verify`。個人偏好（permissions、model 等）與機密（登入憑證、API 金鑰）不在本工具內，各裝置自行設定。細節：`docs/cross-device.md`。

## 故障排除

常見問題（hook 沒觸發、verify ❌、區塊標記壞掉、Python 版本不符、Windows 中文亂碼）見 `docs/troubleshooting.md`。相容版本與未驗證平台見 `docs/compatibility.md`。

## 開發

```bash
python -m unittest discover -s tests -v
```

修改後：更新 `config/VERSION`（語意化版本）、`CHANGELOG.md`；改到 manifest 結構時把 `installer/cds/__init__.py` 的 `MANIFEST_SCHEMA` +1 並在 `installer/cds/manifest.py` 的 `MIGRATIONS` 加遷移函式。通用規則更新後必跑自我測試（規格 11.5）；不可把單一專案的特殊需求升格成全域規則。
