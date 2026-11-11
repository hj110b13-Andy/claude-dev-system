# 派 agent 規矩（細則）

## 派工規格七要素
1. 背景與使用者原話（逐字引用，不轉述成模糊需求）。
2. 已查證的根因或證據（數字、commit、檔案與函式名）。
3. 明確修法方向（能由程式決定的就程式決定，AI 只負責解說）。
4. 不能破壞的既有行為清單。
5. 可量化的驗收標準與驗證步驟。
6. 協調資訊（誰在改哪些檔、遇到未提交變更怎麼辦）。
7. 總時限、每 10 分鐘回報、回報格式：開頭「進度 已完成/總數｜預計還需 N 分（依據）」；交完最終報告就結束。

## 派工固定條款（0.16.0 起每份派工都附，原文照抄進派工說明）
1. **交最終報告前確認自己開的背景程序全部結束**：含 `until`／`while` 等待迴圈、`tail -f`、回測、測試、開發伺服器；依自己記下的 PID 或埠號結束，不可整批結束 node／bash；結束不了的寫進報告（PID＋命令）。
   （2026-11-08 Stock-web：agent 留下 `until [ $(grep -c "FULL" …run-s1.log) -ge 13 ] … do sleep 10; done` 與 tail.exe，交報告後從 21:02 空轉到隔天，使用者自己看到才問。）
2. **重型程序（回測、全套測試、build、影片轉逐字稿）開跑前先過記憶體閘門**：`py -3 ~/.claude/claude-dev-system/tools/resgate.py run --project <專案> --desc "<工作>" -- <要跑的指令>`
   （優先用 `run`：閘門與工作是同一個指令，記憶體夠才執行、exit code 透傳，不足就不執行；`wait` 仍可用，但後面不可接管線，例如 `wait … | tail && 工作` 會讓閘門的 exit 1 被 `tail` 的 0 蓋掉而硬跑，2026-11-11 全套測試就這樣在 1.9 GB < 3 GB 時跑了。Bash 工具前景跑 timeout 設 600000）。`run` 夠了就跑並以工作的 exit code 結束；`wait` 的 exit 0 才開跑；exit 1＝等滿 10 分鐘仍不足，**不跑**，報告寫「記憶體不足、沒有執行」（已自動登記延後清單）。門檻只在 dispatch-config.json 的 `resourceGate.minFreeMemGB`（預設 3 GB），派工說明不另寫數字。
3. **暫存檔用自己的子資料夾**：scratchpad 底下先建 `<agent 名稱或任務代號>/` 再寫檔，不直接寫在 scratchpad 根目錄。
   （2026-11-08 Stock-web：session scratchpad 與其他 agent 共用，覆蓋了別人的 head.md／tail.md；2026-11-09 這個 repo 的派工也在共用 scratchpad 撞到別人的 re.py。）

4. **寫明工作目錄與 commit 的分支**（0.21.0）：agent 的工作目錄繼承主對話派工當下的位置（主對話在 worktree 裡，agent 就在那個 worktree、那個分支）。派工說明寫「在 `<絕對路徑>` 工作，commit 到分支 `<名稱>`」或「不 commit，只交 patch」；派工前自己先 `git branch --show-current` 確認。
   （2026-11-10 Stock-web：main 當時在 EdgeOne 試用 worktree，派出的研究 agent 照派工單 commit，結果進了部署分支 `claude/edgeone-trial`，派工單沒寫分支。）

## agent 開工時實際拿到什麼（0.21.0，2026-11-11 查 Stock-web 81 份 agent 紀錄＋官方文件 code.claude.com/docs/en/sub-agents）
- 有：全域與專案 CLAUDE.md、AGENTS.md、MEMORY.md 索引、skill 清單、git 狀態快照、派工說明。Explore、Plan 連 CLAUDE.md 都沒有。
- 沒有：主對話的對話內容、回覆語言設定、記憶檔內文、主對話讀過的檔、UserPromptSubmit 與 Stop hook 的守門（查證守門、建議守門、專案自動化都不對 agent 觸發；PostToolUse 會）。
- 實測遵守率：寫進派工說明的規則幾乎都照做（「繁體中文」81 份都寫、最終報告都是中文；`resgate` 28 份有寫、28 份有跑）；只在 CLAUDE.md、沒寫進派工說明的常被略過（上網前先讀 web-quick.md：9 個上網的只有 2 個讀；記憶內文：81 個裡只有 1 個讀過（用指令讀了一條的前 15 行；0.23.0 用 agent-audit.py 重算後更正，原寫 81 個都沒讀））。
- 所以：**這份工作一定要守的規則，逐條寫進派工說明**（官方文件同一結論："If a rule must [reach the subagent]... restate it in the prompt you give Claude when delegating"）；與這份工作有關的記憶，把內文重點或檔案路徑寫進派工說明。SubagentStart hook 會自動補語言、工作目錄與分支、記憶路徑、自我核對清單（`subagentBrief.enabled`，預設開），但那是保底，不取代派工說明。
- 收報告時 main 要自己核對：agent 的結論不經查證不可直接轉給使用者（數字對回它寫的檔、判定標準是不是看到結果後才定的、commit 在哪個分支）。
- **交報告守門（0.22.0，`subagentBrief.guard`，預設開）**：agent 呼叫 `SubagentHandback` 交報告時 hook 核對語言、數字出處、上網前有沒有讀 web-quick.md、有沒有讀相關記憶內文、沒寫分支卻 commit 有沒有交代；不合格退回一次。只有 auto mode、非 fork、Claude Code 2.1.271 以上才有這個工具；其他情況由 SubagentStop 後備核對最後一則訊息（後備沒有實跑驗證過）。守門只查程式能判定的五項，**判定標準是不是事後才定、結論有沒有過度簡化仍要 main 自己看**。
- **派完看遵守情況（0.23.0）**：`py -3 ~/.claude/claude-dev-system/tools/agent-audit.py <專案路徑> --latest 1`（加 `--detail` 看每個 agent 依序做了什麼）。Stock-web 恢復派工後第一批 3 個（opus 研究型 1、sonnet 2）：讀記憶內文 2／3、上網前先讀 web-quick 2／2、報告中文 3／3、重型工作過閘門 3／3、被守門退回 1 個並補交。
- **Stock-web 2026-11-11 全天 11 個 agent（opus 7、sonnet 4）**：讀記憶內文 7／11、上網前先讀 web-quick 4／4、最終報告中文 8／9、重型工作過閘門 8／8、被守門退回 3 個且 3 個都補交。兩個跑數小時的 opus 研究型開工時都沒讀記憶，被守門退回後才真的去讀 2～3 條——**opus 研究型不會照開工補充主動讀記憶，要靠守門；與這份工作有關的記憶仍要寫進派工說明**。中途文字 27 則裡 14 則英文（0.26.0 把語言提醒改成每則新的都提醒）。
- 0.22.0 實派結果（hook 全開、派工單沒寫語言／記憶／上網規則，3 個 sonnet agent）：讀相關記憶內文 3／3、上網前先讀 web-quick.md 1／1、最終報告中文 3／3、commit 分支有交代 3／3、記憶體不足時照閘門不跑 2／2。樣本只有 3 個、都是 sonnet；opus 與長時間研究型工作還沒有數據。

## 重型工作與延後清單（0.16.0；使用者 2026-11-09 決定）
- 使用者原話：「等 10 分鐘還不夠就不跑：直接回報「記憶體不足、沒有執行」，由我決定之後再跑。不會卡住，也不會硬跑出問題，只是那個工作會延後。我選這個，但要寫清楚規則當有其他agent完成時，要確認記憶體是否足夠了，並開始跑「記憶體不足、沒有執行」的任務。然後先設固定 3GB就好，提醒就不用了，記憶體門檻要用成視窗可更改的。」
- 門檻唯一來源：`dispatch-config.json` 的 `resourceGate`（`minFreeMemGB` 3、`waitMinutes` 10、`pollSeconds` 60；專案 `.claude/dispatch-config.json` 優先；設定視窗可改 `minFreeMemGB`，1～32）。
- 閘門：`resgate.py run --desc "<工作>" -- <指令>`（優先；與 `wait` 共用同一段等待，夠才執行並透傳 exit code，不足不執行、`--rerun` 沒給就用指令字串登記）；`resgate.py wait` 可用實體記憶體 < 門檻就每 60 秒看一次、最多 10 分鐘；仍不足 exit 1、印「記憶體不足、沒有執行」並登記延後清單。只想查不想等用 `resgate.py check`。
- **只處理自己專案登記的延後工作**（0.26.1）：`resgate.py next` 預設只看目前專案（`--all` 才不分專案），hook 的提醒也只提這個專案的；別的專案的由那邊的對話處理，不要代跑。
- 延後清單唯一一份：`<CLAUDE_HOME>/state/deferred-jobs.json`（全部專案共用，每筆記專案、工作描述、怎麼重跑、登記時間、當時可用記憶體）；`resgate.py list` 看、`resgate.py done <編號>` 開跑後移除。
- **主對話的規則**：每當有 agent／背景任務完成（收到完成通知、巡檢發現結束），先跑 `resgate.py next`：記憶體 ≥ 門檻就依登記順序開跑第一項（重派，或 SendMessage 喚回原 agent 接著跑），`done` 移除後再查一次，夠再開下一項；不夠就等下一個完成事件。hook 在延後清單有項目且記憶體夠時注入【延後工作（hook）】，派背景任務時的巡檢提醒也會帶上清單項數。
- 不做「同時 N 個重型」的提醒（使用者：「提醒就不用了」）。

## 模型與努力程度
- 依 `dispatch-config.json`（專案 `.claude/` 優先於全域）的 `modelTable` 表（skill `cds-agent-dispatch` 有完整步驟）。規格越精確越適合便宜模型；需要判斷、取捨、跨模組設計才用最強模型。
- 升級：同類已失敗過、影響所有使用者、要跨報告取捨、牽涉權限隱私。降級：規格已寫死、只動文件／測試期望值、重跑既有腳本。
- 派工說明第一行寫「（模型／努力程度：X／Y，理由：類型 Z）」。
- `model`／`effort` 是 Claude Code Agent 工具實際支援的參數（2.1.x 實測）；不支援的版本就省略，不可虛構。

## 協作
- 共用工作目錄：只 add／commit 自己的檔；同檔有別人在改，先看 `git diff -- <檔>` 只收自己的區塊。
- 推送前同步：本機有 merge commit（合併過 agent 分支）用 `git pull --no-rebase`（或 `--rebase=merges`），沒有才可 `--rebase`（`workflow.md`〈推送前同步〉）。
- 小步 commit；未完成改動存 patch 到暫存資料夾並在回報寫路徑。
- 並行數量依設定檔 `concurrency`（文字說明；用量接近門檻時降到 1～2 個）；會改同一檔的排先後。


---
# 完整規則原文（自 Stock-web 全域工作流規則去專案化，使用者原話、數字、日期原樣保留）

## 派工規格品質（2026-10-05 使用者明訂：「下限看模型、上限看我們」也適用於派工）

- 每份派工都要包含：①背景與使用者原話（逐字引用回報，不轉述成模糊需求）；②已查證的根因或證據（數字、commit、檔案與函式名）；③明確修法方向與「程式決定、AI 只解說」的偏好；④不能破壞的既有行為清單（引用交接紀錄雷區）；⑤可量化的驗收標準與驗證步驟（線上環境怎麼測、測哪幾項、限幾項）；⑥協調資訊（哪些檔案別人在改、遇到未提交變更怎麼辦）；⑦限時、每 10 分鐘回報、回報格式。
- 規格越精確越適合交給 Sonnet 以節省額度；需要判斷、取捨、跨模組設計的才用 Opus。多個 Opus 同時跑容易一起撞上限，並行數量要節制。

## git 與協作

- 多個 agent 共用同一個工作目錄與 git index：只能 `git add <自己改的檔案>` 並用 `git commit -m "..." -- <同樣路徑>`，**絕不** `git add -A`／`git add .`，也不能 stash／reset／checkout 別人未提交的變更（2026-10-01 曾把別人 staged 的檔案掃進自己的 commit）。
- **絕不用 `taskkill /IM node.exe` 等方式結束全部 node 程序**（2026-10-14 某 agent 這樣關本機測試伺服器，連帶中斷其他 agent 的 dev server、vitest、build）：只結束自己開的程序，依埠號（`Get-NetTCPConnection -LocalPort <埠>`）或自己記下的 PID 結束；派工指示也要寫明。
- **同一個檔有別人在改時，commit 前先看 `git diff -- <檔>`，只收自己的區塊（`git add -p` 或暫時索引）**：`git commit -- <檔>` 會把整個工作檔、含別人未提交的行一起提交（2026-10-14 主對話提交某測試檔時夾帶另一個 agent 未提交的測試行，HEAD 因型別不存在而編譯失敗）。
- **驗證 agent 一律限時**（2026-10-05 教訓：盤中驗證 agent 跑近 1 小時、連 SendMessage 都不回）：寫明總時限（例如 30 分鐘）、單一步驟超過 3 分鐘放棄並記「未能驗證」、不可用超過 90 秒的 sleep／waitForTimeout；超時先 SendMessage 詢問，10 分鐘無回應即停掉重派（只驗未驗項目）。
