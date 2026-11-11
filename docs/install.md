# 安裝

1. 確認必要條件：`python installer/install.py check`（Windows：`py -3 installer/install.py check`）。❌ 必須先處理，⚠️ 可繼續。
2. `python installer/install.py install`。輸出會逐行列出：備份檔位置、新增的檔案、settings.json 新增或略過的 hook、CLAUDE.md 區塊。
3. `python installer/install.py verify`：逐項 ✅／❌（安裝紀錄、版本、檔案雜湊、hook、腳本可編譯、CLAUDE.md 區塊、每個 skill、Claude Code 版本）。結束碼 0＝全通過。
4. **重開** Claude Code 對話（或 VSCode 視窗）讓新的 CLAUDE.md、skills、hook 生效。在新對話請 Claude 列出可用的 skill，應看到 `cds-` 開頭的 skill（清單以 README「內容與分層」的 `skills/` 列為準，0.27.0 時 10 個；這裡原寫「七個」）。

## 安裝後自我測試（選用）

`python installer/install.py selftest`：用全新無頭 Claude Code 對話重跑 `config/selftest.json` 的題目（題數以該檔為準；這裡原寫「九題」，0.27.0 健檢時實際 11 題），比對它實際呼叫的工具是否符合規則（細節見 README「自我測試」）。`--list` 列題、`--only 題號` 挑題（可用逗號一次給多題）、`--smoke` 只跑該檔 `smoke` 列的三題、`--dry-run` 只印每題會執行的指令不跑、`--report-dir 路徑` 把每題的工具呼叫清單與回答存成 JSON。費用約每題一場短對話的用量，不會自動跑。

## 目標位置

- 預設 `~/.claude`；若有設環境變數 `CLAUDE_CONFIG_DIR` 則用它；也可 `--claude-home <路徑>` 指定（測試用）。
- hook 指令用「執行安裝器的那個 Python」的完整路徑（`--python` 可改），所以請用之後也會存在的 Python 執行安裝。

## 安裝器不會做的事

- 不改 `permissions`、`model`、`language`、`effortLevel`、`statusLine`、`enabledPlugins`、`extraKnownMarketplaces`、其他 hooks，也不碰 `~/.claude/commands/`。
- 不會覆蓋同名但不是本工具裝的 skill 資料夾（會印 ⚠️ 並略過）。
- 已有你自己的 `usage_guard.py` hook 時不重複註冊（verify 會顯示「使用者既有條目在作用」）。想改由本工具管理：先從 settings.json 移除你自己掛 `usage_guard.py` 的那幾條（原寫「那兩條」，是只有兩個事件時的說法；現在本工具掛 7 個事件），再 `update`。
- 安裝或更新前會先檢查 `settings.json`（要是合法 JSON、最外層是物件、沒有 BOM）與 `CLAUDE.md`（要是 UTF-8、本工具的區塊標記成對且只有一組）；不合格就整個不動、印出是哪個檔與原因（0.27.0 起；之前會裝到一半才失敗）。同一個設定目錄同時只允許一個安裝／更新／解除安裝在跑，第二個會印「另一個安裝程序正在執行」並以結束碼 2 結束。
- 不在 settings.json 加任何非官方鍵；版本與安裝紀錄放在 `~/.claude/claude-dev-system/manifest.json`。
- 不碰 MCP 設定與 `env`——除非你加 `--with-web`（或之後跑 `install.py web`）；那時也只用官方 `claude mcp add --scope user` 註冊、只寫 `env` 裡本工具登記的鍵，見 `docs/web-sources.md`。
- 不 pip 裝任何套件——除非你加 `--with-video`（或之後跑 `install.py video`）；那時用執行安裝器的 Python 裝 `config/video.json` 列的套件，`video --off` 只取消登記不解除安裝，見 `docs/video.md`。
