# 變更紀錄

格式：語意化版本（主.次.修）。主版號變動＝manifest 或設定結構不相容；次版號＝新增規則／skill／工具；修訂號＝修正。

## 0.4.4（2026-10-27）

- 新增來源：交通部 TDX（金鑰 `tdx_id`＋`tdx_secret`，OAuth2 client_credentials）。用途限定為停車場等**結構化靜態資料的單筆查詢**：`CarPark` 基本資料最可靠（`CarParkType` 1 平面／2 立體／3 地下／4 塔／5 機械／6 混合、車位數、地址、電話）；營業時間／出入口限高／費率端點各縣市填寫完整度不同（南投車埕兩座實測 0 筆）→ 空筆退回網頁鏈。基礎會員 5 次／分／金鑰（header `RateLimit-Limit: 5` 實測）；訂閱頁無「學術方案」級別，學術為付費方案減免。`core.md` 加一句停車場靜態事實先查 TDX；`web-sources.md` 第 4 節加 TDX 用法與「停車場靜態事實選哪個」規則；第 5 節 TDX 說法改為「排路線不適用，單筆可用」。來源：車埕停車場實測三步網頁鏈走完仍無法確認平面／立體，TDX 一筆即得。

## 0.4.3（2026-10-27）

- 補：第三步整頁抓取的對象優先序（官網＞政府頁＞新聞＞聚合頁）。來源：「車埕停車場」實測三步鏈全走完、回報格式完全合規，但第三步抓了 Agoda 聚合頁而非結果中已出現的南投旅遊網官方頁。
- 規則修正（來自「米平方停車場限高」實測）：前兩步搜尋已出現官方網址但摘錄無該值時，第三步**必做**整頁抓取確認（摘錄沒有≠官網沒寫）；「建議打電話」的界線改為「未走完升級鏈不可用電話代替查證；走完後可附官方電話當備案」。該次實測其餘行為（parallel→exa 自動升級、跨兩索引才標未能確認、列最接近線索、來源衝突兩者並列、自我更正地點錯誤）皆符合 0.4.2 規則。

## 0.4.2（2026-10-27）

- 規則修正：明寫「查了 2 次」的定義——必須跨兩個不同索引（內建→parallel、parallel→exa、exa→tavily／Chrome 開官網），同一工具換關鍵字不算第二次；每個事實走完兩個索引才可標「未能確認」，且須列出用過的工具、查詢與最接近的線索。多事實查證第二輪只補第一輪沒拿到的。來源：0.4.1 實測中 Claude 對「米平方停車場是否平面」只用 parallel 一次就放棄。

## 0.4.1（2026-10-27）

- 規則修正（來自實際旅遊行程規劃的回饋）：Claude 用內建 WebSearch 查 20 多次、多次回「查不到、建議打電話」卻未切換到 parallel／exa／tavily；使用者一問才切換，各打 1–2 次即查到官網停車規則、公休、公有停車場型式。根因是規則「搜不到時改用」是形容詞、無可判定條件。`core.md` 改為硬規則：台灣在地事實（公休、營業時間、停車、票價、官方公告）直接從 parallel／exa 起手；同一事實內建查 2 次仍無具體值、或結果只說「請電洽」、或時效性問題只拿到一年前資料 → 立即切換，未用 MCP 前不可回報「查不到建議打電話」；≥3 個獨立事實用 parallel 一次多查詢。`web-sources.md` 新增 1a 節切換條件表、台灣在地事實起手規則、禁止回報方式、額度說明（parallel／exa／context7／deepwiki／mslearn 免金鑰不耗使用者額度，只有 tavily 用金鑰）。
- README 版本 0.4.1。

## 0.4.0（2026-10-26）

- 新增三個免金鑰文件 MCP，預設開：`context7`（程式庫最新官方文件；有金鑰以 `CONTEXT7_API_KEY` header 傳）、`deepwiki`（公開 GitHub repo 自動文件與問答，Cognition 官方）、`mslearn`（微軟官方文件）。三者皆遠端託管、2026-10-26 實測端點存活。
- `web-sources.json` 新增 `localKeys` 說明區：`cwa`、`moenv`（環境部空品）、`openaq`、`tavily`、`exa`、`context7`。
- 規則：`core.md`「上網查資料」補文件 MCP 分流；`web-sources.md` 重寫——工具優先序加文件類分流、更正 token 成本描述（Claude Code 延後載入 MCP schema，遠端 MCP 幾乎不花 token）、開放 API 分四類並新增 12 項實測端點（USGS 地震、Open-Meteo 空氣品質、日出日落、CoinGecko 含 TWD、Yahoo Finance chart 含 `2330.TW`、GDELT 新聞、OpenAlex、arXiv、Crossref、Hacker News、Wikimedia 瀏覽量、Open Library）、CWA 新增地震報告 `E-A0015-001` 與警特報、天氣／空品／地震三條選擇規則。查了不列：Semantic Scholar（免金鑰實測首次即 429）、REST Countries、Apify 新聞 MCP、Brave。瀏覽器類 MCP 另行決定。
- 測試：預設 MCP 集合改為常數 `DEFAULTS`，35 個全過。

## 0.3.0（2026-10-26）

- 新增「聯網來源」（選用，預設不啟用）：`config/web-sources.json` 為唯一來源，列免金鑰搜尋 MCP（預設 `parallel`、`exa`；選用 `tavily`、`firecrawl`）與 WebSearch 上限 env（`CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION=600`、`CLAUDE_CODE_WEB_SEARCH_REFILLS_PER_HOUR=300`，官方預設 200／100，需 Claude Code ≥2.1.290）。`install.py install|update --with-web` 啟用；新子命令 `install.py web --key/--enable/--disable/--env/--off/--show` 改本機偏好並立即套用。MCP 以官方 `claude mcp add/remove --scope user` 寫入，本工具只讀 `~/.claude.json` 判斷；使用者自己同名的 MCP 與自己設的 env 不覆蓋；uninstall 只移除本工具登記過的。
- 本機偏好與金鑰（Tavily、Exa、中央氣象署）存 `<CLAUDE_HOME>/claude-dev-system/config/local.json`：不在 manifest、不進 repo、update／uninstall 不動；輸出中金鑰一律遮罩。
- 規則：`core.md` 加「上網查資料」優先序一條；新增 `rules/web-sources.md`（工具優先序、MCP 一覽、2026-10-26 實測過的免金鑰開放 API：Open-Meteo、open.er-api（含 TWD）、Frankfurter、證交所 OpenAPI／MIS、FinMind、政府辦公日曆表、Nager.Date、Wikipedia、Nominatim、OpenSky；需註冊的中央氣象署／Tavily／Exa；沒有免費來源的類別；安全與禮儀）。實測淘汰：Nager.Date 不支援 TW、Frankfurter 無 TWD、台銀牌告 CSV 被反爬擋、Brave 2026-02 取消免費方案、TDX 免費 5 次／分。
- manifest schemaVersion 1 → 2（新增 `web` 紀錄；`_m1_to_2` 自動遷移，舊安裝視為未啟用）。
- 測試：新增 14 個聯網來源測試（假的 `claude mcp` runner，不碰真實設定）：預設不碰、啟用／verify／uninstall 還原、update 不重複註冊、tavily 免金鑰→金鑰→停用、exa 金鑰進 header、使用者同名 MCP 與 env 不覆蓋、--off 保留 local.json、被改壞的 MCP verify ❌ 且 update 補回、env 不是物件時略過不覆蓋、使用者預設同值不被認領、local.json 壞掉給一行中文錯誤且不擋 uninstall、runner 失敗時結束碼 1 且訊息遮金鑰、未啟用時 --show 明說。獨立驗證 agent 在隔離 `CLAUDE_CONFIG_DIR` 下用真實 `claude mcp add` 跑完 install→web→off→uninstall 全流程，真實 `~/.claude*` 雜湊前後相同。
- `install`／`update` 的結束碼：任一步印 ❌（目前只有聯網註冊失敗會）即回 1（之前一律 0）。
- 文件：`docs/web-sources.md`、README「選用：聯網來源」、install／update／uninstall／cross-device 補聯網來源段。

## 0.2.1（2026-10-18）

- 規則：Stock-web H-13 決定「全域 rules 為通用規則唯一來源」，專案 `global-workflow.md` 改成只留指向。`workflow.md` 規則九「7 天 97% 的詳細版」更正為「7 天達收尾門檻的詳細版」並改讀設定檔 `usageThresholdPct`（不寫死數字）；其餘通用句與專案版逐句比對 0 遺漏（專案名詞改寫版與專案實例留在 Stock-web `project-reference.md`）。

## 0.2.0（2026-10-17）

- 規則：Stock-web `docs/claude-rules/global-workflow.md` 去專案化後併入 `rules/`（規則二、三、六～九→`workflow.md`、十→`token-efficiency.md`、十一→`safe-refactor.md`、十二→`doc-governance.md`、派工規格品質與 git 協作→`agent-dispatch.md`），刪除佔位檔；使用者原話、數字、日期原樣保留。`progress-diff` 逐句比對：以去專案化對照後的原文為基準找不到 0 句（原檔直接比對 41 句皆為專案名詞改寫或搬到專案 skill 的導引句）。
- 設定：`config/dispatch-config.json` 改為與 Stock-web `.claude/dispatch-config.json` 同結構（`plan`、`usageThresholdPct`、`boardMeterMarks`、`concurrency`、`dispatchUsageAdjust`、`modelTable` A～I）；舊的 `usage`／`dispatch.taskTypes` 結構廢止（skills 與規則已改指向新結構）。使用者若改過舊版檔，update 會保留並產生 `.new`，請改採新結構。
- hook：`usage_guard.py` 門檻讀取順序＝專案 `.claude/dispatch-config.json`（hook 的 cwd 往上找）→ 全域設定檔 → 內建預設 80／97；`--print` 印出採用哪一份；方案 `until` 到期（含當日）自動改用 `plan.after`。
- 看板 mod 來源：新增 `hooks/limits.ts`，收尾警示與用量條標線改讀同一份設定檔（找不到用預設 80／97）。
- 測試：新增 usage_guard 門檻順序與方案到期測試、看板門檻解析測試。`compat.json` 不變。

## 0.1.0（2026-10-17）

- 初版。來源：Stock-web `tools/claude-setup/`、`scripts/audit/`、`.claude/skills/agent-dispatch`、CLAUDE.md 通用規則。
- 規則分層（`rules/`）：core（合併進 CLAUDE.md 標記區塊）、workflow、agent-dispatch、token-efficiency、doc-governance、safe-refactor；global-workflow 為佔位（待 DOC 合併）。
- skills：cds-agent-dispatch、cds-safe-refactor、cds-doc-governance、cds-feedback-audit。
- hooks：usage_guard 通用版（門檻改讀 `config/dispatch-config.json`，預設 80／97；支援 `CLAUDE_CONFIG_DIR`）；task-board mod 來源（專案專屬，不自動安裝）。
- tools：depgraph（別名、副檔名、排除資料夾、分層規則全參數化；在 Stock-web src 上與原版輸出相同）、moduleInventory、progress-diff（任意檔案逐句比對）。
- 安裝器：check／install／verify／update／uninstall／status；manifest schemaVersion 1 與遷移骨架。
- 相容：Claude Code ≥2.1.0 <3.0.0（實測 2.1.296）；Windows 11 實測，macOS／Linux 未驗證。
