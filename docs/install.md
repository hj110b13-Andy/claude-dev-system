# 安裝

1. 確認必要條件：`python installer/install.py check`（Windows：`py -3 installer/install.py check`）。❌ 必須先處理，⚠️ 可繼續。
2. `python installer/install.py install`。輸出會逐行列出：備份檔位置、新增的檔案、settings.json 新增或略過的 hook、CLAUDE.md 區塊。
3. `python installer/install.py verify`：逐項 ✅／❌（安裝紀錄、版本、檔案雜湊、hook、腳本可編譯、CLAUDE.md 區塊、每個 skill、Claude Code 版本）。結束碼 0＝全通過。
4. **重開** Claude Code 對話（或 VSCode 視窗）讓新的 CLAUDE.md、skills、hook 生效。在新對話請 Claude 列出可用的 skill，應看到 `cds-*` 四個。

## 目標位置

- 預設 `~/.claude`；若有設環境變數 `CLAUDE_CONFIG_DIR` 則用它；也可 `--claude-home <路徑>` 指定（測試用）。
- hook 指令用「執行安裝器的那個 Python」的完整路徑（`--python` 可改），所以請用之後也會存在的 Python 執行安裝。

## 安裝器不會做的事

- 不改 `permissions`、`model`、`language`、`effortLevel`、`statusLine`、`enabledPlugins`、`extraKnownMarketplaces`、其他 hooks，也不碰 `~/.claude/commands/`。
- 不會覆蓋同名但不是本工具裝的 skill 資料夾（會印 ⚠️ 並略過）。
- 已有你自己的 `usage_guard.py` hook 時不重複註冊（verify 會顯示「使用者既有條目在作用」）。想改由本工具管理：先從 settings.json 移除你自己的那兩條，再 `update`。
- 不在 settings.json 加任何非官方鍵；版本與安裝紀錄放在 `~/.claude/claude-dev-system/manifest.json`。
- 不碰 MCP 設定與 `env`——除非你加 `--with-web`（或之後跑 `install.py web`）；那時也只用官方 `claude mcp add --scope user` 註冊、只寫 `env` 裡本工具登記的鍵，見 `docs/web-sources.md`。
