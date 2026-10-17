# 更新與回復舊版

## 更新
```bash
git pull
python installer/install.py status
python installer/install.py update
python installer/install.py verify
```
- 每次 update 先備份 settings.json 與 CLAUDE.md。
- 本工具檔案若被你改過（雜湊與安裝紀錄不同），**保留你的版本**，新版寫成同資料夾的 `<檔名>.new`；CLAUDE.md 區塊被改過時新版寫到 `~/.claude/claude-dev-system/CLAUDE-block.new.md`。手動合併後再 `update --force` 讓紀錄同步。
- 新版移除的檔案：沒改過的刪掉，改過的保留。
- manifest 結構升版時自動遷移（`installer/cds/manifest.py` 的 `MIGRATIONS`）；遇到比安裝器新的 schema 會停止並請你先更新 repo。

## 回復舊版
```bash
git checkout v0.1.0          # 或任一舊版 commit／tag
python installer/install.py update --force   # 降版需要 --force
python installer/install.py verify
```
或完全移除：`uninstall --restore-backup` 用第一次安裝前的備份還原 settings.json；所有備份都在 `~/.claude/backups/claude-dev-system-*`。
