# 更新與回復舊版

## 更新
```bash
git pull
python installer/install.py status
python installer/install.py update
python installer/install.py verify
```
- 每次 update 先備份 settings.json 與 CLAUDE.md。
- **執行檔使用者**：視窗頂端「檢查更新」比對 GitHub 的 `config/VERSION`，有新版就下載到 `~/.claude/claude-dev-system/app/`，之後按「套用」；只有安裝器程式碼有變才需要到 Releases 抓新 exe（視窗會提示）。
- 本工具檔案若被你改過（雜湊與安裝紀錄不同），**保留你的版本**，新版寫成同資料夾的 `<檔名>.new`（`dispatch-config.json` 例外：本來就給你改的設定檔，不生 `.new`，新版新增的鍵會補上、你的值不動）；CLAUDE.md 區塊被改過時新版寫到 `~/.claude/claude-dev-system/CLAUDE-block.new.md`。手動合併後再 `update --force` 讓紀錄同步。
- 新版移除的檔案：沒改過的刪掉，改過的保留。
- manifest 結構升版時自動遷移（`installer/cds/manifest.py` 的 `MIGRATIONS`）；遇到比安裝器新的 schema 會停止並請你先更新 repo。0.3.0 起 schema 2（新增 `web` 紀錄；舊安裝遷移後視為未啟用聯網來源）。
- 聯網來源：`update` 沿用已安裝的啟用狀態——已啟用的會依新版 `web-sources.json` 補齊或調整 MCP 與 env（不重複註冊）；未啟用的不碰。要開啟加 `--with-web`，要關閉用 `install.py web --off`。

## 回復舊版
```bash
git checkout v0.1.0          # 或任一舊版 commit／tag
python installer/install.py update --force   # 降版需要 --force
python installer/install.py verify
```
或完全移除：`uninstall --restore-backup` 用第一次安裝前的備份還原 settings.json；所有備份都在 `~/.claude/backups/claude-dev-system-*`。
