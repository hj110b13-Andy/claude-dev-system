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
解除前也會再備份一次。找不到安裝紀錄時，只清除帶標記的 hook 與 CLAUDE.md 區塊。
