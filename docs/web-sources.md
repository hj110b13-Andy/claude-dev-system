# 聯網來源（選用）

讓每台電腦的 Claude Code 查資料更不容易「查不到」或「查到一半停掉」，而不多花每場對話的 token。預設**不啟用**；啟用後做四件事：

1. 寫入 `settings.json` 的 `env`：放寬內建 `WebSearch` 的次數上限（官方預設每場 200 次、每小時補 100 次 → `config/web-sources.json` 的 600／300；需 Claude Code ≥2.1.290），以及 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`（Windows 碼頁 950 下 Python 子程序中文輸出不再亂碼）。
2. 用官方 `claude mcp add --scope user` 註冊免金鑰 MCP：預設搜尋 `parallel`、`exa` 與文件 `context7`（程式庫文件）、`deepwiki`（GitHub repo）、`mslearn`（微軟文件）；選用 `tavily`、`firecrawl`。
3. 規則：`rules/core.md` 多一條「上網查資料」優先序；細則 `rules/web-sources.md` 列出 2026-10-26 實測過的免金鑰開放 API（天氣、匯率、台股、假日、百科、地理編碼、航班位置）與金鑰位置。這兩項隨一般 `install`／`update` 安裝，不需 `--with-web`。
4. 需要金鑰的來源（中央氣象署、Tavily、Exa）金鑰只存本機 `<CLAUDE_HOME>/claude-dev-system/config/local.json`，不進 repo。

## 啟用

```bash
python installer/install.py update --with-web      # 已安裝者；新裝置可直接 install --with-web
python installer/install.py verify                 # 應看到「MCP parallel 已註冊」「MCP exa 已註冊」「env …」
```
重開 Claude Code 對話後 `/mcp` 應看到 parallel、exa 連線成功。之後每次 `update` 會沿用啟用狀態並自動補齊（不重複註冊）。

## 加金鑰、開關 MCP（`web` 子命令）

```bash
python installer/install.py web --show                              # 看目前會啟用什麼、有哪些金鑰（金鑰只顯示名稱）
python installer/install.py web --key cwa=CWA-xxxx                  # 中央氣象署授權碼
python installer/install.py web --key moenv=xxxx --key openaq=xxxx  # 環境部空品、OpenAQ（規則檔教 Claude 怎麼用）
python installer/install.py web --key tavily=tvly-xxxx --enable tavily
python installer/install.py web --enable firecrawl                  # 免金鑰
python installer/install.py web --disable exa                       # 關掉某個預設
python installer/install.py web --env CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION=1000   # 覆寫 env 值
python installer/install.py web --off                               # 關閉：移除本工具加的 MCP 與 env，保留 local.json
python installer/install.py web --usage-guard off                   # 關閉用量守門 hook（update 時移除；on 開回）
```
每次 `web` 都會先備份 settings.json，改完立即套用並更新安裝紀錄。金鑰在安裝器所有輸出中都遮成 `***`，也不會寫進 manifest；但**必然以明文**存在 `local.json`、`~/.claude.json` 的 MCP URL（Tavily）或 header（Exa），以及當下執行的 `claude mcp add` 命令列——這兩個檔請勿分享或 commit。`claude` 不在 PATH 或註冊失敗時，`install`／`update --with-web` 會印 ❌ 並以結束碼 1 結束（其他部分仍已套用，修好後重跑即可補齊）。

註冊方式：
- **中央氣象署**：https://opendata.cwa.gov.tw/ 加入會員 → 登入 → 開發指南 →「API 授權碼」→ 取得（`CWA-` 開頭）。免費；試用額度 1,000 次／天。
- **Tavily**：https://app.tavily.com/ 用 Google／GitHub 登入，dashboard 自動產生金鑰。免費 1,000 credits／月、不用信用卡。不註冊也能用（免金鑰模式只開 search／extract）。
- **Exa**：不註冊即可用；https://dashboard.exa.ai/api-keys 註冊後每月 1 日重置 $10 額度（≈2,500 次）。金鑰版額度用完回 402，但 0.7.0 起預設「免費優先」，免金鑰版 `exa` 照常可用、`exa-key` 只在限流時用，所以不會整個停擺。
- **Parallel**：不註冊即可用；https://platform.parallel.ai/ 建金鑰：註冊送一次性 $20（有到期日，Billing 頁可看），「每月 $5」要綁信用卡才解鎖，不綁卡額度用完就只剩免金鑰版：`--key parallel=…`，多 `web_research` 工具、速率較高。
- **Firecrawl**：不註冊即可用；https://www.firecrawl.dev/app/api-keys （免費 1,000 credits／月）：`--key firecrawl=…`，開全部工具。
- **Context7**：不註冊即可用；https://context7.com/dashboard 免費金鑰（`ctx7sk-` 開頭）每月 1,000 次、提高速率（`--key context7=…`，以 `Authorization: Bearer` header 送）。
- **環境部空品**：https://data.moenv.gov.tw/ 註冊取 api_key（台灣各測站官方 AQI）。
- **OpenAQ**：https://explore.openaq.org/register 免費金鑰（全球官方測站空品）。
- **TDX（交通部）**：https://tdx.transportdata.tw/ 註冊 → 會員中心 → 資料服務 → API 金鑰，取「API 金鑰內容」的 Client Id／Secret：`web --key tdx_id=… --key tdx_secret=…`。免費 5 次／分，只用於停車場等靜態資料單筆查詢。
- **YouTube Data API（`youtube`）與 Gemini（`gemini`）**：影片來源用，步驟（含實際畫面核對）見 `docs/video.md`。

## 免費優先（搜尋類金鑰的模式，0.7.0 起）

填了 exa／tavily／context7／parallel／firecrawl 的金鑰後，安裝器預設同時註冊**免金鑰版** `<名稱>` 與**金鑰版** `<名稱>-key`；規則（`rules/web-sources.md` 第 2c 節）先用免金鑰版，回 429／5xx／402 才用 `-key` 版，之後連續 3 次用 `-key`、第 4 次再試免金鑰。想一律用金鑰：`web --key-mode exa=always`（只註冊金鑰版）；改回：`--key-mode exa=fallback`。`web --show` 會列出目前模式。

## 安裝器怎麼避免動到你的東西

- MCP 名稱已存在但不是本工具加的 → 略過並 ⚠️（想交給本工具管：`claude mcp remove -s user <名稱>` 後重跑）。
- `settings.json` 的 `env` 裡同名鍵若是你自己設的（值不同且本工具沒登記過）→ 不覆蓋。
- `uninstall` 與 `web --off` 只移除安裝紀錄 `web.mcpAdded`／`web.envCreatedKeys` 登記過的項目；`local.json`（含金鑰）一律保留，不需要請自行刪。
- `~/.claude.json` 只讀不寫，所有寫入都經官方 `claude mcp add/remove`。

## 瀏覽器與 Windows 亂碼（不在安裝器內，但屬同一套做法）

- **Claude in Chrome**：要實際開網頁看、操作需登入的網站、讀 Facebook 社團／Threads、測自己的網站，用 Claude Code 內建的 Chrome 整合：裝 Chrome 擴充「Claude in Chrome」、同帳號登入、在對話打 `/chrome` 開「Enabled by default」。規則檔第 6 節寫明何時用它、何時不用。
- **Windows 亂碼根本解**：裝 PowerShell 7 **MSI 版**（`winget install --id Microsoft.PowerShell --source winget --installer-type wix`，Store 版 Claude Code 偵測不到），重開 Claude Code 後 PowerShell 工具自動改用 pwsh，JSON 中文、`Get-Content`、`&&`／三元運算子的坑全部消失；Python 子程序由本工具寫入的 `PYTHONUTF8=1` 解決。系統碼頁 950 不需要改（「Beta: 使用 Unicode UTF-8」副作用大於收益，除非有具體舊程式問題）。細節：`rules/web-sources.md`「Windows 亂碼的三個根源與修法」。

## 跨裝置

`web-sources.json`、規則、安裝器隨 repo 同步；**是否啟用、金鑰、開關偏好是每台各自的**（`local.json` 不同步）。新裝置：`install --with-web` → 需要的話 `web --key …`。

## 故障排除

- `verify` 出現「MCP x 不在 user scope」：重跑 `install.py web`（或 `update`）會補回。
- `/mcp` 顯示連線失敗：先 `claude mcp get <名稱>` 看錯誤；免金鑰服務偶有限流（HTTP 429），稍後再試；用瀏覽器 GET 這些端點回 405 是正常的（MCP 只收 POST）。
- `claude` 指令找不到：安裝器 `check` 會標 ⚠️；`--with-web` 需要它在 PATH。
- 想完全不要：`install.py web --off`；或 `uninstall`。
