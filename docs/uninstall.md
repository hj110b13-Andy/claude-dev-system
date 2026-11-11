# 解除安裝

```bash
python installer/install.py uninstall
```
依安裝紀錄只移除：
1. settings.json 中指令含 `# claude-dev-system` 的 hook（以及因此變空、且原本是本工具建立的事件或 `hooks` 鍵）。移除後若與安裝前備份逐鍵相等，直接用備份還原原檔（排版也相同）。
2. CLAUDE.md 的 `claude-dev-system:begin`～`end` 區塊與安裝時加的分隔空行；區塊外內容不動（安裝後你在區塊外加的內容也保留）。
3. 本工具安裝的檔案（雜湊與紀錄相同者）、`.new` 檔、空資料夾。你改過的檔案保留並列出（`--force` 才刪）。
4. 聯網來源（若啟用過）：以 `claude mcp remove --scope user` 移除紀錄 `web.mcpAdded` 中的 MCP；移除 settings.json `env` 裡 `web.envCreatedKeys` 登記的鍵（因此變空且是本工具建立的 `env` 一併移除）。你自己加的 MCP 與 env 不動。`config/local.json`（金鑰、開關偏好）**保留**，會列出路徑提醒你自行刪。

選項：`--restore-backup` 在上述完成後，再用第一次安裝前的 settings.json 備份覆蓋回去（會丟失安裝後你對 settings.json 的其他修改，請先確認）。
- 「第一次安裝前的備份」只認安裝那一次留下、紀錄裡標了 `preInstall` 的那一筆（0.27.0 起；更新時永遠保留它）。0.27.0 前的舊紀錄沒有這個標記時，只有第一筆備份的時間在安裝時間之後 120 秒內才當它是。
- 這些情況**不還原**、只印 ⚠️ 說明，settings.json 維持「已移除本工具條目」的樣子：安裝前本來就沒有 settings.json；那份備份檔已不在；舊安裝更新超過 10 次、安裝前那份早被擠掉。
- 起因（2026-11-12 健檢實跑）：之前拿「紀錄裡第一筆有 settings 的備份」當安裝前備份，更新超過 10 次或安裝前沒有 settings.json 時，會把 7 條指向已刪腳本的 hook 寫回 settings.json。

結束碼：全部移除成功是 0；`claude mcp remove` 失敗（例如 `claude` 不在 PATH）是 1，最後一行是 ❌，安裝紀錄會留著（只剩沒移掉的 MCP 名稱），修好後重跑 `uninstall` 可接著移除（0.27.0 起；之前照樣印「解除安裝完成」並刪掉紀錄，那些 MCP 之後就沒人管）。
解除前也會再備份一次。找不到安裝紀錄時，只清除帶標記的 hook 與 CLAUDE.md 區塊。
