# claude-dev-system

把 Stock-web 專案系統優化中「成熟且驗證過」的通用流程，封裝成可跨專案、跨裝置安裝的 Claude Code 全域工具。
版本見 `config/VERSION`（目前 0.4.9），相容範圍見 `config/compat.json`，變更見 `CHANGELOG.md`。

## 內容與分層

| 目錄 | 內容 | 安裝到（`<CLAUDE_HOME>`＝`~/.claude`） |
|---|---|---|
| `rules/` | 通用規則（分層說明見 `rules/README.md`）；`core.md` 是唯一會進 CLAUDE.md 的部分 | `claude-dev-system/rules/`；`core.md` 另合併進 `CLAUDE.md` 標記區塊 |
| `skills/` | `cds-agent-dispatch`、`cds-safe-refactor`、`cds-doc-governance`、`cds-feedback-audit`（皆有 frontmatter） | `skills/<名稱>/`（Claude Code 原生個人 skill 位置） |
| `hooks/usage_guard.py` | 用量守門 hook（通用版；門檻讀設定檔） | `claude-dev-system/hooks/`，並在 `settings.json` 註冊 UserPromptSubmit／PostToolUse |
| `hooks/task-board/` | 任務看板 mod 來源（**專案專屬**：讀 Stock-web 的 PROGRESS.md），`hooks/.claude-plugin/marketplace.json` 是本機 marketplace | 不自動安裝；要用的專案在 `.claude/settings.json` 以 `extraKnownMarketplaces`＋`enabledPlugins` 啟用 |
| `tools/` | `depgraph.py`（依賴圖／循環閘門）、`moduleInventory.py`（模組盤點）、`progress-diff.py`（文件瘦身逐句比對）；不寫死路徑，全用參數 | `claude-dev-system/tools/` |
| `config/` | `VERSION`、`compat.json`、`dispatch-config.json`（用量門檻、方案期間、模型表；專案 `.claude/dispatch-config.json` 優先於全域）、`web-sources.json`（聯網來源：免金鑰搜尋 MCP 與 WebSearch 上限 env，選用） | `claude-dev-system/config/`（dispatch-config 可自行修改，更新時保留；本機金鑰與開關在 `local.json`，不進 repo） |
| `installer/` | `install.py`＋`cds/` 模組（只用 Python 標準庫） | — |
| `tests/` | 安裝器與工具的自我測試 | — |
| `docs/` | 安裝、更新、解除安裝、跨裝置、故障排除、相容版本 | — |

**全域只放通用能力**；業務規則、資料模型、專案命令留在各專案 CLAUDE.md（規格 10.1）。專案規則與全域規則衝突時以專案為準。
本工具**不宣稱**靠 CLAUDE.md 就能控制所有行為：CLAUDE.md 區塊只是載入給模型的指引；真正自動執行的只有 hook（用量守門）。

## 必要條件

- Python ≥ 3.10（安裝器、hook、工具都只用標準庫）
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

## 選用：聯網來源

```bash
python installer/install.py update --with-web            # 放寬內建 WebSearch 上限＋註冊免金鑰 MCP（搜尋 parallel、exa；文件 context7、deepwiki、mslearn）
python installer/install.py web --key cwa=CWA-xxxx       # 選用：中央氣象署授權碼（金鑰只存本機 local.json）
python installer/install.py web --key tavily=tvly-xxxx --enable tavily
```
預設不啟用。用官方 `claude mcp add --scope user` 註冊，不覆蓋你自己同名的 MCP 或 env；`web --off` 或 `uninstall` 只移除本工具登記過的。規則 `rules/web-sources.md` 列出實測過的免金鑰開放 API（天氣、空氣品質、地震、匯率、加密貨幣、台股／美股、全球新聞、論文、假日、百科、地理編碼、航班位置）與選擇規則。細節：`docs/web-sources.md`。

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
