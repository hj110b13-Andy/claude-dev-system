# claude-dev-system 交接紀錄

## 接手狀態（2026-11-11 21:1x）

**已發布**：v0.26.1（0.26.0 之後只多了「延後工作分專案」這個修正）。工作樹乾淨、本機安裝 0.26.1、沒有背景任務。下面「11:3x 寫的」那節列的事都做完了：0.25.1 已發（背景指令等到記憶體放行後自動完成）；待辦 A（CLAUDE.md 瘦身）＝0.26.0；待辦 B（Stock-web 兩個 opus agent）結果寫在 CHANGELOG 0.26.0 與 `rules/agent-dispatch.md`。

**還沒做的**：
- 瘦身後一週內看規則有沒有被略過變多：`py -3 tools/agent-audit.py <專案> --since <日期>` 與 `~/.claude/state/source-guard.log`；有退步就 `git revert` 0.26.0 的 core.md 那個 commit 再發一版。
- 語言提醒改成「每則新的都提醒」後樣本還太少：2026-11-11 晚上 Stock-web 只有 1 個 opus agent（`a233a40e`）實際收到第二次提醒，紀錄是「英、提醒、英、提醒、中」，第二次後改中文；另一個（`a2d280af`）一次提醒後連續 7 則中文。下次 Stock-web 多派幾個 opus agent 後看中途文字英文比例（0.26.0 前是 14／27）。〔原句：語言提醒改成「每則新的都提醒」後還沒有真實樣本（下次 Stock-web 派 opus agent 後看中途文字英文比例，0.26.0 前是 14／27）。〕
- 背景 agent＋與主對話同模型＋主對話沒在等工具時的壓縮判定沒有實跑（CHANGELOG 0.24.0）。
- 【全域系統對照】一天一次只有單元測試；11/12 看 Stock-web 第一則提示是否只出現一次。
- 新裝置端對端確認（本檔〈待辦 2〉，等使用者在另一台測）。
- Stock-web 那場對話要重開才吃得到 0.24.0 的延後載入與 0.26.0 的瘦身（由使用者在那邊決定）。
- Stock-web 2026-11-11 18:02 是接續（resume）同一場對話、不是新開；接續後 context 長到 56 萬 token、406 次請求合計約 1.49 億 token。已建議使用者在 Stock-web 開全新對話。
- 量「新對話第一次請求 context」時要注意：數字會隨第一次請求前連上幾個 MCP 伺服器而差幾千 token（2026-11-11 同一設定量到 45,058／49,618／51,032／54,343），比較前後要先確認兩次的 `mcp_instructions_delta` 伺服器數相同。

**這場對話另外處理掉的（不用再做）**：
- （已於 0.26.1 修好：提醒與 `resgate.py next` 只看這個專案登記的）原紀錄：新發現、沒修（2026-11-11 21:3x）：【延後工作（hook）】把別的專案登記的延後工作也叫這場對話去跑——claude-dev-system 的對話被要求跑 Stock-web 的 #15「11f/11g 腳本 tsc」。延後清單是全專案共用一份，hook 提醒時應只提這個專案（登記時的專案路徑與目前 cwd 的專案根相同）的項目，別的專案只提一句「另有 N 項屬於其他專案」。main 沒有代跑，留給 Stock-web 那場對話。

**驗證方式**：`py -3 tools/resgate.py run --desc "全套測試" -- py -3 -m unittest discover -s tests`（輸出導檔、exit code 存變數，不接管線；2026-11-11 為 187 項通過、1 項略過）、`py -3 installer/install.py verify`、`gh release view v<版本>` 確認 exe 與 .sha256。

決策：2026-11-11｜core.md 縮短的條文原文整條搬到 core-detail.md，不逐句改寫分散到各細則檔｜逐句比對工具能直接證明沒有遺漏；分散改寫容易兩邊各留一份不同版本｜progress-diff 舊版 103 句、找不到 0。
決策：2026-11-11｜免金鑰與金鑰版 MCP 說明重複（約 8 KB）維持現況；tavily 金鑰不重新產生｜使用者原話「1.維持現況」「3.不換」｜本檔 v0.24.0 節。

## 11:3x 寫的接手狀態（以下各項已於 0.25.1／0.26.0 完成，原文保留）

**為什麼換對話**：這場對話從早上做到 0.25.1，內容非常長，每回一次都要重讀全部；5 小時用量 11:3x 到 98%（門檻 95%）。使用者說過有重置券不用擔心額度，但繼續在這場做瘦身會很貴又可能被切斷。

**進行中、會自己完成的**：背景指令（這場對話的工作階段）在等記憶體閘門，最多 5 輪、每輪 10 分鐘：放行→全套測試→通過才 update、verify、push、打 tag v0.25.1、等 Release。11:3x 可用記憶體 2.1 GB（門檻 3 GB），佔用的是 Stock-web 兩個 opus agent 的回測。
- 接手先查：`git tag -l v0.25.1`、`git status -sb`、`gh release view v0.25.1`。
- **沒發成功時**（本機 master 比 origin 多 commit、沒有 tag）：`py -3 tools/resgate.py run --project claude-dev-system --desc "0.25.1 全套測試" -- py -3 -m unittest discover -s tests`（輸出導檔、exit code 存變數，不接管線），exit 0 才 `install.py update --with-web --with-video`、`verify`、`git push`、`git tag v0.25.1 && git push origin v0.25.1`、`gh release view v0.25.1` 確認兩個附件。0.25.1 只改 `tools/agent-audit.py` 與它的測試（7 項已單獨通過）。
- 延後清單可能留著幾筆「0.25.1 全套測試」：跑完後 `py -3 tools/resgate.py list`、`done <編號>` 清掉。

**使用者 2026-11-11 的三個決定**（原話：「1.維持現況 2.照你安排做 3.不換」）：
1. 免金鑰版與金鑰版的 MCP 說明重複（約 8 KB）：**維持現況**，不動。
2. 全域 CLAUDE.md 瘦身：**照 main 安排做**——見下方待辦 A，還沒開工。
3. tavily 金鑰（出現在那場對話的工具輸出）：**不換**。

### 待辦 A：全域 CLAUDE.md（rules/core.md）瘦身（使用者已同意，未開工）

- 現況（2026-11-11 量）：`rules/core.md` 27 行、14,327 位元組；合併進 `~/.claude/CLAUDE.md` 後約 6,602 字，每個專案每次請求都帶著。最長的幾條：「上網查資料」「背景任務巡檢」「影片」「教使用者操作任何網站或軟體前」「先找現成做法」「隨時可接手」「專案自動化」。
- 目標：長條文只留「什麼情況觸發＋必做的那一步＋細節看哪個檔哪一節」，細節搬到 `rules/` 細則檔（web-quick.md、web-sources.md、workflow.md、agent-dispatch.md 多半已有對應段落，先確認細則檔已含同樣內容再刪 core.md 的重複，不要兩邊各留一份不同版本）。
- **不可搬走的**（自己定的原則，依據是 2026-11-11 的實測「只在細則檔、沒寫在眼前的規則常被略過」：上網前先讀 web-quick.md，9 個上網的 agent 只有 2 個讀）：每一條的觸發條件與硬性動作要留在 core.md；使用者原話與日期只能移位置不能刪（repo 規則）；hook 會點名的標籤（【改到安裝副本】【背景任務巡檢】等）在 core.md 要找得到對應條文。
- 做法：一次只改 2～3 條；每次改完用 `python ~/.claude/claude-dev-system/tools/progress-diff.py` 逐句比對，確認被移走的句子在細則檔找得到；skill `cds-doc-governance` 有流程。全部改完跑全套測試（有測試檢查 core.md 的內容與長度，改之前先 `grep -rn "core.md" tests/` 看有哪些）。
- 驗收：core.md 位元組數與字數的改前改後；progress-diff 的輸出證明沒有句子遺失；全套測試通過；update 後 `~/.claude/CLAUDE.md` 的區塊確實變短；開一場新對話（或 `claude -p`）量第一次請求的 context 改前改後（量法見 CHANGELOG 0.24.0：讀該對話紀錄第一則助理訊息的 usage）。
- 風險與回復：瘦身後規則被略過變多。上線後用 `tools/agent-audit.py` 與 `~/.claude/state/source-guard.log` 看一週；有退步就 `git revert` 那個 commit 再發一版。
- 版本：次版號（改規則）。同一天不要再連發多版（【全域系統對照】已改成一天一次，但仍盡量併版）。

### 待辦 B：Stock-web 兩個 opus agent 的結果（等它們交報告）

- 2026-11-11 10:35 派的 `a51c3d97`（A2 除權息停損研究續做）、`a96d7f54`（急跌跌深放寬持股上限研究），11:3x 仍在跑。到 11:1x 為止兩個都上網查了資料但沒有先讀 web-quick.md，也還沒讀記憶內文；照設計交報告時會被守門退回一次。
- 看法：`py -3 tools/agent-audit.py C:\Users\88691\Documents\Claude\Stock-web --since 2026-11-11 --detail`（0.25.1 裝好後「重型工作」才不會把讀檔算進去）。要回報使用者：有沒有被退回、退回後有沒有真的補讀（看退回之後的工具呼叫，不是只看報告怎麼寫）、opus 是不是只靠守門兜底。
- 這是第一份 opus 長時間研究型＋守門的樣本；結果寫回本檔與 `rules/agent-dispatch.md`〈agent 開工時實際拿到什麼〉的實測段。

### 其他還沒做的（都記過，列在一起方便接手）

- 背景 agent＋與主對話同模型＋主對話沒在等工具時的壓縮判定沒有實跑（CHANGELOG 0.24.0）。
- 【全域系統對照】一天一次只有單元測試，隔天看 Stock-web 第一則提示有沒有只出現一次。
- 新裝置端對端確認（本檔〈待辦 2〉，等使用者在另一台測）。
- Stock-web 那場對話已壓縮 9 次以上，要重開才吃得到 0.24.0 省下的固定開銷（由使用者在那邊決定）。

## 2026-11-11：v0.25.0（兩個提示的雜訊）

- 使用者原話：「照你建議做」（main 建議的兩項：【全域系統對照】太頻繁、【背景任務巡檢】重複提醒）。做法與數字在 CHANGELOG 0.25.0。
- 驗證：全套 unittest 185 項通過（1 項略過，經 `resgate.py run` 放行）；update 後 settings.json 的 PostToolUse matcher 已含 `CronCreate|CronDelete`；這場對話實跑——建巡檢排程後派背景指令沒有提醒，刪掉排程後再派有提醒。【全域系統對照】一天一次只有單元測試（要隔天才看得到實際行為）。
- 待觀察：Stock-web 10:35 派的 3 個 agent（opus 研究型 2、sonnet 1）交報告後的遵守情況，用 `py -3 tools/agent-audit.py <Stock-web 路徑> --since 2026-11-11 --detail` 看；結果寫在本節下一行。

## 2026-11-11：v0.24.0（修完剩下兩項＋觀察 Stock-web）

- 使用者原話：「繼續全部修好，然後Stock-web也有持續在動作，你可以關注看看改的全域優化系統對它的影響如何」。
- 做了（數字與來源在 CHANGELOG 0.24.0）：①建議守門排除敘述句 ②agent 壓縮判定補完同模型情況（實跑通過）③**新發現並修掉**：firecrawl 兩份工具定義 45 KB 每次請求都帶著，註冊改成延後載入，新對話第一次請求 68,636 → 54,317 token。
- Stock-web 觀察結論：agent 遵守情況好（3 個，見 0.23.0）；主對話沒有被 Stop 守門退回；最大的問題是壓縮太頻繁（2 小時 16 分 7 次），主因是 09:19 換成視窗較小的模型＋固定開銷約 10 萬 token。這次只處理了我們自己造成的那一塊（firecrawl）。
- 還能再省、沒做（都要動使用者的內容或有取捨，先記著）：
  - Stock-web 對話重開才吃得到延後載入；那場已壓縮 7 次，hook 也已建議開新對話。
  - 固定開銷其他大項（字元數，Stock-web 對話實測）：內建工具定義 79 KB、claude.ai 的 artifacts 連接器 29 KB（不是我們裝的）、MCP 伺服器說明 22 KB（其中 `-key` 版與免金鑰版說明重複，約 8 KB）、Stock-web 專案 CLAUDE.md 9,728 字、全域 CLAUDE.md 6,602 字、MEMORY.md 3,614 字。
  - 【全域系統對照】當天對 Stock-web 注入 4 次（這個 repo 一天升了 4 個次版號）。之後同一天的多個小改動盡量併成一版，或把只修 bug 的改成修訂號。
- 沒實跑：背景 agent＋與主對話同模型＋主對話沒在等工具時的壓縮判定（靠 context 大小比較）。
- 這場對話用過的實驗資料夾在 scratchpad 的 `compact-exp/`、`fallback-exp/`（暫存，對話結束可清）。診斷開關 `~/.claude/state/hook-debug.on` 已刪。
- **金鑰外洩到對話紀錄**：main 為了看 MCP 設定印出 `~/.claude.json` 的伺服器網址，tavily-key 的網址帶著 API 金鑰，出現在這場對話的工具輸出（沒有進任何檔案或 commit）。已告知使用者，要不要重新產生由使用者決定。之後讀 MCP 設定只印名稱與指定欄位，不印 url。

## 2026-11-11：v0.23.0（使用者：「都做，我有重置卷所以不用擔心額度」）

- 起因：使用者問「還有甚麼要做或優化的嗎?」，main 列 9 項；第 9 項（新裝置端對端確認）等使用者在另一台測，其餘 8 項的做法、數字、來源在 CHANGELOG 0.23.0。
- 做完並驗證過：①`resgate.py run` ②查證守門分清觸發來源 ③`tools/agent-audit.py`（更正 0.21.0 的 0／81→1／81）④Stock-web 第一批 3 個 agent 的數據，順帶修守門誤擋與漏洞 ⑤SubagentStop 後備在無頭模式實跑通過 ⑥Stock-web 專案版 skill 已對齊、沒改 ⑦agent 中途文字語言提醒，實測有效。
- ⑧agent 自己壓縮被注入主對話開工清單：**已重現**（探針 agent 用 `autoCompactWindow: 100000` 讀大檔；壓縮 2～3 次都被注入、主對話壓縮計數被加）。第一版修法（看 compact_boundary 有沒有落檔）實測無效——hook 執行當下 boundary 還沒寫進檔（非同步；診斷紀錄 mtime_age 14 秒、boundaries 空）。第二版：payload 的 `model`≠主對話模型且＝正在跑的 agent 的模型→agent；模型相同才等最多 2 秒看 boundary 落在哪。**第二版的實跑結果寫在本節最後一行；「模型相同」那條路只有單元測試。**
- 診斷開關：`~/.claude/state/hook-debug.on` 存在時，SessionStart 的 payload 與檔案狀態寫到 `hook-debug.jsonl`；平常不存在。實驗結束已刪。
- 重現方法（之後要再驗）：在一個暫存資料夾放 `.claude/agents/compact-probe.md`（tools: Read、model: haiku、autoCompactWindow: 100000）與一個約 29 萬位元組的大檔，`claude -p "Use the Agent tool … subagent_type compact-probe … 分 9 次各讀 500 行" --model sonnet --permission-mode default --allowedTools Agent Read --output-format json`，再看 `~/.claude/projects/<該資料夾>/<session>/subagents/*.jsonl` 裡 `compact_boundary` 次數與 `hook_additional_context`（hookEvent SessionStart）次數。
- 用量：做到一半 5 小時用量 97%（門檻 95%）。使用者已說有重置券不用擔心額度，所以沒停工，但之後沒有再派新的工作 agent。
- 沒做：第 9 項新裝置端對端確認；「模型相同」時的壓縮判定沒有實跑；opus 長時間研究型 agent 的樣本仍只有 1 個。
- 新發現、沒修：建議守門把敘述句裡的「建議你」也當成提出建議（2026-11-11 main 的收尾回覆寫「會誤建議你開新對話」被退回一次）；`SG_RECO` 要排除「誤建議／會建議／不建議」這類前綴或改成只認句首。
- 第二版實跑結果（2026-11-11，主對話 sonnet、探針 haiku）：agent 壓縮 2 次、注入 0 次、主對話壓縮計數沒有被加；hook 診斷紀錄兩次都是 from_subagent=True、判定 0.0 秒。全套 unittest 177 項通過（1 項略過），用 `resgate.py run` 經閘門放行（可用 4.0 GB）。

## 2026-11-11：v0.22.0（0.21.0 留下的四項全做完）

- 使用者原話：「還沒解決的繼續全都做完。」「你的任務本身也可以派給agent，順便測試效果怎麼樣。如果不衝突的話，能並行處理就並行處理加快速度。」中途問：「然後你現在優化完了嗎?我可以叫Stock-web派agent了嗎?」
- 做了（細節、數字、來源在 CHANGELOG 0.22.0）：①交報告守門（PreToolUse SubagentHandback）＋SubagentStop 後備 ②設定視窗兩個開關、核心區六列自動換行 ③實派 3 個 sonnet agent 做實際工作＋1 個故意違規探針，量遵守率 ④【共用工作目錄】誤報、專案自動化把子資料夾當新專案兩個 hook bug ⑤README 版本需求小節 ⑥Stock-web 的記憶 `do-it-yourself-no-agents` 沒有動：使用者 11/11 已在 Stock-web 對話親自解除（「可以派agent了」），那場對話自己更新了記憶。
- 決策：2026-11-11｜守門攔在 SubagentHandback 不攔 SubagentStop｜SubagentStop 時報告已送達、還會被內部分支觸發｜官方 hooks 文件〈SubagentStop input〉、anthropics/claude-code#87065、#91910。
- 決策：2026-11-11｜`compat.json` 最低版本不抬到 2.1.271｜低於該版只會漏擋不會壞，抬高等於不支援舊版｜README 新小節。
- 決策：2026-11-11｜派工單叫 commit 沒寫分支→照做並在報告揭露（不是拒絕 commit）｜agent 無從判斷哪個分支才對，揭露後由 main 核對；實派的 agent 也是這樣做｜CHANGELOG 0.22.0。
- 沒做／待觀察：
  - SubagentStop 後備只有單元測試，沒有在非 auto mode 實跑。
  - 遵守率樣本只有 3 個 sonnet agent；opus、長時間研究型（Stock-web 那種回測研究）還沒有數據。Stock-web 恢復派工後，用 `~/.claude/state/source-guard.log` 的 `block-agent` 筆數與 agent 紀錄看實際表現。
  - agent 的中途文字仍有一半是英文（最終報告都是中文）；守門只查最終報告。
  - anthropics/claude-code#91910：subagent 自己壓縮時 SessionStart(compact) 不帶 agent 欄位，「壓縮後重新開工」清單可能注入到 agent；payload 分不出來，沒處理。
  - 設定視窗在 980 寬時「用量守門」「查證守門」兩個長勾選框是單一元件，沒有超出但也不會換行。
- 結果：全套 unittest 158 項通過（1 項發版衛生在打 tag 前略過）；update 後 verify 全部通過；v0.22.0 Release 的 exe 與 .sha256 都在。**閘門失誤**：main 的指令寫成 `resgate.py wait … | tail -3 && unittest`，管線把 resgate 的 exit 1 蓋成 0，所以記憶體不足（1.9 GB < 3 GB）時全套測試還是跑了（22 秒，沒有出問題）。之後閘門指令不可接管線，用 `resgate.py wait … && <工作>` 或先單獨跑閘門看 exit code。
- 驗證方式：`py -3 -m unittest discover -s tests`、`py -3 installer/install.py verify`；派一個要它交英文報告的 agent，應被【報告守門（hook）】退回一次。

## 2026-11-11：v0.21.0（agent 不守規則的查證與保底）

- 使用者原話：「它派出去的agent常常都不會遵守該專案裡的規則與長期記憶等等，還有連全域優化系統的規則它也不不遵守，不知道是不遵守還是不會看，你幫我確認看看。」
- 結論：兩者都有。agent 看得到 CLAUDE.md 與 MEMORY.md 索引，但拿不到回覆語言設定、記憶內文、UserPromptSubmit／Stop 守門，工作目錄繼承主對話當下位置；寫進派工單的規則幾乎都照做，只在 CLAUDE.md 的常被略過。數字與來源在 CHANGELOG 0.21.0、`rules/agent-dispatch.md`〈agent 開工時實際拿到什麼〉。
- 做了：SubagentStart hook 自動補語言、工作目錄與分支、記憶路徑、自我核對清單（`subagentBrief.enabled`，預設開）；派工固定條款第 4 條；core.md、skill 同步。
- 驗證：unittest 145 項通過（1 項略過）；update 後 verify 全部通過；實派一個 general-purpose agent（不准用工具）逐字抄出【派工補充（hook）】全文，工作目錄與分支正確。
- 沒做／待觀察：①SubagentStop 守門沒加（沒有量到可用程式判定的違規樣式）；②保底清單送到了，但 agent 會不會照做還沒有實際工作的數據——下次任何專案派 agent 後，看它有沒有讀記憶內文、上網前有沒有讀 web-quick.md；③Stock-web 的記憶 `do-it-yourself-no-agents`（11/10 使用者要 main 全部自己做）仍有效，要不要恢復派工由使用者在那邊決定；④設定視窗沒有 `subagentBrief` 開關，要關只能改設定檔。

## 2026-11-11：複查 0.17.0～0.19.0（Stock-web 對話 11/9～11/10 改的）

- 0.17.0～0.19.0 都已在 master、本機安裝副本與 repo 內容一致（只差使用者自訂的 config/dispatch-config.json，update 保留，屬正常）；unittest 139 項通過（1 項略過）。細節與使用者原話在 CHANGELOG。
- 缺口：0.19.0（`1caafcc`）已推 master 但沒打 tag、沒出 Release，其他裝置拿不到。11/11 補打 `v0.19.0` 並推送。
- 這台 dispatch-config.json 是 11/1 的舊自訂版（fiveHour 95／sevenDay 99），沒有 0.12.0 起的健康檢查與 alignOnUpdate 鍵，hook 用內建預設（與出廠值相同）。使用者說「好，補到設定視窗」→ v0.20.0：視窗可改這些健康檢查門檻與開關（不改的話不寫入），並修正存「專案自動化」會刪掉其他鍵；Release 兩個附件已確認。

## 2026-11-09：v0.16.2（查證守門收緊）

- 使用者同意（「改」）：0.16.0 G 項只要有任一 .md／.json 檔名就算有來源，順口提 PROGRESS.md 就能放行憑印象的數字。改成工作文件與設定檔（`SG_LOCAL_GENERIC`）不算，回測報告等本機路徑照舊放行。舊程式／新程式對照與測試見 CHANGELOG 0.16.2。

## 2026-11-09：v0.16.1（Stock-web 對話派工，A～I 全做，E 照使用者決定；v0.16.0 tag 的 CI 測試因 8.3 短檔名失敗沒出 Release，0.16.1 修好重發）

- 做了：project-scan 不再把 worktree／.next／junction 算進依賴圖、讀 tsconfig 別名、每檔只讀一次（Stock-web 9.2 秒→1.8 秒）；健康檢查比對實際行數；新工具 procs.py（殘留程序）、resgate.py（記憶體閘門＋延後清單，門檻 resourceGate 3 GB、視窗可改）、cleanup.py（安全清理，預設只列清單）；查證守門認本機路徑；git 推送前同步規則與對照提醒點名寫死 `git pull --rebase`；對話暫存每 7 天提醒；派工固定三條款。細節、原話、數字在 CHANGELOG 0.16.0。
- 驗證：`py -3 -m unittest discover -s tests`（137 項，1 項發版衛生在打 tag 前略過）、`install.py update --with-web --with-video`、`verify` 全部通過；hook 量測 PostToolUse +4 ms、UserPromptSubmit +5 ms（中位數）。
- 沒做：E 以外沒有遺留。這台安裝的 dispatch-config.json 是使用者改過的版本（update 保留），沒有新的 resourceGate／procCheck／cleanup 段，工具用內建預設（同出廠值）；視窗改記憶體門檻時會寫入。Stock-web 兩個 skill（progress-handoff、push-gate-deploy）仍寫死 `git pull --rebase`，下次 Stock-web 對話的【全域系統對照】會點名。

## 接手狀態（2026-11-07）

**已發布**：v0.15.1（exe 與 .sha256 都在）。0.15.1＝使用者貼另一台自我測試 9/11：pwsh、docs 改判「有沒有查一手來源」不寫死工具，兩題這台重跑都通過；細節見 CHANGELOG。另一台下次跑全套 11 題確認。工作樹乾淨，沒有未完成的改動或 patch，沒有背景任務。

**2026-11-07 做完**（使用者：「週用量更新了，可以繼續做了…把待辦與問題都修好。」）：
- 原待辦 0、1 全部完成並併成 v0.15.0：一鍵安裝（Python 3.14、Git、Node LTS、Claude Code 官方 stable、Deno）、Deno／Node 分兩列、hook 盤點過期計數改用 project-scan 同一套 .gitignore 判斷、發版衛生測試與 repo CLAUDE.md 規則、併入誤標 0.14.2 的 `95c184c`。原文、查證來源與數字都在 CHANGELOG.md 0.15.0；原待辦內容移到本檔最後「已完成待辦原文」。
- 實測：這台用視窗同一個安裝函式實裝 Deno 2.9.8，PATH 不重開就補回、環境列變 ✅（原待辦 2 第一項完成）。
- 使用者截圖的 AI-Search&Fetch 問題（圖片分析時 Gemini 三個模型 503、轉 41 秒）：在那個專案修好並推送 `97da618`，2026-11-08 使用者允許後已部署（Worker Version aa982a3a，`/api/health` ok），剩手機再傳一次圖片驗證。（原句：正式站還沒部署——`npm run deploy` 被 Claude Code 權限擋下，要使用者自己跑或允許。）細節在 AI-Search&Fetch 的 PROGRESS.md 第十六節。

### 待辦 2：新裝置端對端確認（等使用者下次測；0.15.0 起含一鍵安裝）

- ~~Deno 按鈕裝完環境列是否變 ✅~~：2026-11-07 這台實裝通過。新裝置再看 Python、Git、Node、Claude Code 四個新按鈕（Claude Code 裝完要自己登入）。
- 不經 `/chrome` 勾選後開對話，② 是否自動變 ✅、重開 Chrome 後能否連上（照官方文件寫的，沒實跑）。
- 視窗開著裝 Python 後按「重新整理」是否可用（只做過 PATH 模擬）。
- 先勾「Enabled by default」、之後才裝擴充的流程有沒有正常（使用者 11/4 問過；只驗過設定會保留，官方說偵測不到擴充時會跳安裝提示，都沒實跑）。
- 0.14.2 的 exe 沒有下載來跑過（只跑過原始碼的 --selfcheck）。

### 待辦 3：Stock-web（使用者要自己在那場對話交代）

- 5 個腳本超過 800 行還沒拆（exitStrategy.ts 6,588、register.tsx 866、weeklyGoliveCore.ts 839、histRetest.ts 832、simRulesSnapshot.ts 812），行數閘門只管 src/。拆檔要先估用量給使用者同意。閘門要擴到 scripts/；確定一次性不再修改的才寫進專案 `.claude/dispatch-config.json` 的 `projectAutomation.bigFileExceptions`（逐檔寫原因）。這項不是在這個 repo 做。

### 已知小問題

- 【共用工作目錄】提醒是比對指令文字，指令裡只要出現 `git add -A` 字樣（例如測試資料）也會跳。同一場對話只跳一次，影響小，未修。（2026-11-11 已在 0.22.0 修好：只在 git 真的被當指令執行時才跳，見 CHANGELOG 0.22.0。）

決策：2026-11-04｜YouTube 解挑戰的安裝按鈕裝 Deno 不裝 Node｜使用者說「Node如果比Deno還好就用Node」，查證後 Node 沒有比較好｜yt-dlp wiki/EJS「Deno (recommended) | Enabled by default」、Deno「no file system or network access」、Node 要另外 `--js-runtimes node` 且只有「some permissions restricted」。已裝 Node ≥22 的機器仍算通過。

驗證方式：`py -3 -m unittest discover -s tests`（114 項）、`py -3 installer/install.py verify`。

## 已完成待辦原文（2026-11-04 寫、2026-11-07 完成，只移位置不刪）

**2026-11-04 本輪做完**：0.13.0～0.14.2（細節見 CHANGELOG.md）——全域系統對照 hook、行數上限自動提醒、工具後提醒、新裝置三問題（視窗開著裝的 Python 找不到、Chrome 勾選框被鎖、native host 查成 Desktop 機碼、Deno 按鈕）。

#### 待辦 0：補發 0.14.3（用量重置後第一件，約 5 分鐘）

- 問題：`95c184c`（AI-Search&Fetch 11/4 18:32 提交，project-scan 不算 .gitignore 排除的檔）的版本也標 0.14.2，比 `v0.14.2` tag（`718831a`，18:27）晚 5 分鐘，不在任何 tag 或 Release 裡。VERSION 相同，所以其他裝置「檢查更新」不會判定有新版，拿不到這個修正；CHANGELOG 也有兩段 `## 0.14.2`。這台已安裝的是新的（verify 全部通過）。
- 做法：VERSION 改 0.14.3，把 `95c184c` 那段 CHANGELOG 改標 0.14.3 放最上面，update、verify、push、打 tag、確認 Release 兩個附件都在。不要移動 `v0.14.2` tag。
- 整類修法：repo CLAUDE.md「改這個 repo 時」加一條，多場對話會同時改這個 repo，改動前先 `git pull`、看 `git tag --points-at`／最新 tag；目前 VERSION 已打過 tag 就要往上加，不可沿用；可加測試或 hook 檢查「VERSION 已有 tag 但之後還有非 PROGRESS 的 commit」。
- 同一版一起修：hook 的 `_count_newer`（`hooks/usage_guard.py`，健康檢查「盤點過期」的計數）沒有跟著 `95c184c` 改，仍只排除固定資料夾與點開頭資料夾，被 .gitignore 排除的檔照算。Stock-web 有 436 個被排除的檔（多為 docs/eval 評測輸出），跑評測就可能讓「改過 >20 檔」提早觸發；`--check` 與 hook 算法不一致，違反唯一來源。修法：hook 用同一套 `git ls-files --others --ignored --exclude-standard --directory` 判斷（注意 budget 0.8 秒，git 失敗就照舊），加測試。此項是讀程式碼判定，未實跑重現。
- 已複查沒問題：`fa4bc5c`（0.14.1，Stock-web，逾時自動移背景也提醒巡檢）有 tag 與 Release。這兩個 commit 都是改 repo 再 update，沒有再直接改安裝副本。測試全過、工作樹乾淨。

#### 待辦 1：環境區全部改成一鍵安裝（使用者已提、尚未動工）

- 使用者原話（2026-11-04）：「所有環境安裝的部分可不可以都用成點按鈕就直接安裝，不用再去網頁自己載、自己裝，裝的版本就挑穩定又最新的版本，你覺得如何?」我回答贊成；當時 7 天用量 99%，所以只記錄沒動工。使用者已同意（2026-11-04：「你說的都可以」「可以，都記錄下來到時候接手可以做」），含 Claude Code 用原生安裝不用 winget、Python 選有實測的版本、Deno 與 Node 都裝；用量重置後直接做，不用再問。
- 現況：ffmpeg、PowerShell 7、faster-whisper、Deno 已是按鈕；只有 Python、Claude Code 是「開下載頁」（`installer/cds/gui_model.py` 的 `DOWNLOAD_PAGES`，`installer/gui.py` 環境區）；git 沒有按鈕（`git` 列 action 為 None）。
- 查證過的事實（2026-11-04）：
  - Claude Code：官方 setup 頁寫「WinGet installations do not auto-update」，`Native installations automatically update in the background`；原生安裝 `irm https://claude.ai/install.ps1 | iex`。winget 的 `Anthropic.ClaudeCode` 是 2.1.302，使用者新裝置已是 2.1.318，較舊。→ 建議用原生安裝，不用 winget。
  - git：winget `Git.Git` 2.56.0.4。
  - Python：winget 每個次版本一個 ID（`Python.Python.3.x`）。這次 `winget search` 輸出被 tail 截斷，**最新 ID 沒看到，動工前要重查**；新裝置實測 Python 3.14.10＋faster-whisper 1.2.1 可用，3.14 是有實測的候選。
- 做法：`INSTALL_ACTIONS` 加 python、git；Claude Code 用原生安裝腳本（`INSTALL_ACTIONS` 是 argv 清單，要確認怎麼呼叫 PowerShell）；`installer/gui.py` 按鈕文字表加項；`DOWNLOAD_PAGES` 留作沒有 winget 時的備案。裝完靠 0.14.2 的 `_ensure_python`／`refresh_path` 不用重開視窗。
- Deno 與 Node 兩個都給按鈕（使用者 2026-11-04：「我覺得Deno與Node兩個都裝可以嗎?」，已答不衝突）：Node 用 winget `OpenJS.NodeJS.LTS`（當日 26.13.0），不用 Current 版；環境列要分開顯示兩列或各自有按鈕（現在 `js_runtime` 找到 Deno 就算通過，Node 不會出現按鈕）。`tools/video.py` 的 `ydl_opts` 有 Deno 就用 Deno，不用改。
- 順手修：`tools/video.py` 的 `ydl_opts` 只看有沒有 node，沒查版本；node 低於 22（yt-dlp 最低要求）時仍會指定它，應與 `installer/cds/video.py` 的 `JS_MIN` 同一套門檻（小問題，環境列已會顯示未通過）。
- 裝不了、只能開頁的：Chrome 擴充（商店要使用者按）；登入 Claude 由使用者自己做。
- 驗收：測試涵蓋按鈕動作與沒有 winget 的備案；更新 CHANGELOG、VERSION（次版號），發 Release；最終要在全新裝置實測。

