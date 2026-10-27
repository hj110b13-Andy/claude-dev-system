# 影片來源（選用）

讓 Claude Code 能「找影片、聽影片、看影片畫面」：YouTube、yt-dlp 支援的 1,700 多個網站、直接 mp4 網址、本機檔案。全部免費；兩把金鑰（YouTube Data API、Gemini）選用。

Claude 本身不收影片檔（官方 Vision 文件只列 JPEG／PNG／GIF／WebP），所以做法是：**字幕或語音辨識 → 逐字稿**、**ffmpeg 關鍵畫面 → 截圖給 Claude 看**、真的要逐幀理解才用 **Gemini**。規則 `rules/web-sources.md` 第 9 節寫明什麼情況用哪條。

## 啟用

```bash
python installer/install.py update --with-video     # 用執行安裝器的 Python pip 裝 yt-dlp[default,curl-cffi]、youtube-transcript-api
python installer/install.py video --show            # 檢查依賴與金鑰
python ~/.claude/claude-dev-system/tools/video.py setup    # Windows 用 py -3
```

另外需要：
- **ffmpeg**：`winget install Gyan.FFmpeg`（Windows；安裝器會在 PATH 與 winget 安裝目錄找）。
- **faster-whisper**（選用，沒字幕的影片才需要）：`python -m pip install faster-whisper`；NVIDIA 顯卡另加 `nvidia-cublas-cu12 nvidia-cudnn-cu12`，`video.py` 會自動載入這些 DLL 並在 GPU 失敗時退回 CPU。沒裝時 verify 顯示 ⚠️，其餘功能照常。

## 用法

```bash
V="python ~/.claude/claude-dev-system/tools/video.py"   # Windows 用 py -3
$V search "車埕 一日遊" -n 5                 # 免金鑰；--api --date week 用 Data API
$V info https://www.youtube.com/watch?v=XXXX  # 標題、長度、章節、字幕語言
$V transcript https://www.youtube.com/watch?v=XXXX            # 字幕優先，沒字幕自動語音辨識；只印前 40 行
$V transcript https://www.youtube.com/watch?v=XXXX --grep 肉圓  # 找關鍵字，附 &t= 連結
$V frames https://www.youtube.com/watch?v=XXXX --max 12        # 場景截圖，Claude 用 Read 看
$V frames https://www.youtube.com/watch?v=XXXX --at 12:30,14:05 # 只截指定時間點（逐字稿說「這個／這裡」時）
$V transcript https://www.youtube.com/watch?v=LIVEID --live 300 # 進行中的直播：先錄 5 分鐘再轉逐字稿（frames／ask 也可加 --live）
$V stats https://www.youtube.com/watch?v=XXXX                  # 需 youtube 金鑰
$V comments https://www.youtube.com/watch?v=XXXX -n 20         # 需 youtube 金鑰
$V ask https://www.youtube.com/watch?v=XXXX "影片裡的招牌寫什麼？" --clip 0:00 1:30   # 需 gemini 金鑰
$V transcript "D:\影片\demo.mp4"               # 本機檔案同樣可用（transcript／frames／ask）
$V clean --media-only                          # 刪快取裡的影音檔、留逐字稿
```

快取：`~/.claude/claude-dev-system/cache/video/<影片ID>/`（info.json、transcript.*.txt、audio.m4a、video.mp4、frames/）。同一支影片不重抓。**自動清理**：每次執行時刪超過 7 天沒用的影音檔（最大宗，30 分鐘音訊約 30 MB、4 分鐘 720p 影片約 83 MB）、30 天沒用的整個資料夾；`video.json` 可改天數，`clean` 可手動。

## 兩把選用金鑰怎麼註冊（2026-10-27 以 Claude in Chrome 核對實際畫面；標〔未核對畫面〕的步驟是使用者自行完成、Claude 沒看到）

兩邊的額度都算在 Google Cloud「專案」上，不算帳號、不算金鑰，而且是兩個不同的 API、各自計量；用同一個 Google 帳號開兩個專案最乾淨。

### Gemini（`gemini`）

1. 開 https://aistudio.google.com/api-keys 登入。〔未核對畫面〕新用戶會先要同意服務條款，官方說會自動建立預設專案與金鑰；沒有就按 **Create API key** 建新專案。
2. 複製金鑰。2026-10 實測新金鑰格式是 `AQ.` 開頭 53 字，不是舊的 `AIza`。
3. 終端機自己輸入 `python installer/install.py web --key gemini=金鑰`（不要貼在對話裡）。
免費層：YouTube 網址每天 8 小時影片；速率依模型（https://ai.google.dev/gemini-api/docs/rate-limits ）。`video.json` 預設模型 `gemini-flash-latest`，503 高負載時自動重試並換備用模型。

### YouTube Data API（`youtube`）

1. 開 https://console.cloud.google.com/ 登入。**第一次進 Google Cloud 會先遇到兩道關卡**（實際畫面）：
   - 歡迎視窗：「國家／地區」選台灣，勾「我同意《Google Cloud Platform 服務條款》…」，按「同意並繼續」——使用者自己按。
   - 背後頁面若顯示「無法存取 Google Cloud：2026年9月4日起，Google Cloud 已開始強制執行兩步驟驗證」→ 到 https://myaccount.google.com/security 開「兩步驟驗證」，頁面寫「變更應該會在幾分鐘內生效」，等幾分鐘後重新整理——帳號安全設定，使用者自己做。
2. 〔未核對畫面〕上方「選取專案」→「建立專案」，取名例如 `claude-youtube`。
3. 開 https://console.cloud.google.com/apis/library/youtube.googleapis.com ，按「啟用」；啟用後按鈕變「管理」並顯示「API 已啟用」。
4. 開 https://console.cloud.google.com/apis/credentials → 「＋ 建立憑證」→ 下拉第一項「**API 金鑰**」（說明「透過一個簡單的 API 金鑰識別專案…」）。右側滑出「建立 API 金鑰」表單：
   - 「名稱」：改成 `claude-youtube`（預設「API 金鑰 1」）。
   - 「選取 API 限制」（必填）：點開 → 「篩選」框打 `YouTube` → 勾「YouTube Data API v3」→「確定」，下方顯示「已選取的 API：YouTube Data API v3」。
   - 「應用程式限制」：保持「無」（其餘是網站／IP 位址／Android／iOS；本機腳本、家用 IP 會變，選 IP 會把自己鎖在外）。
   - 按左下「建立」——使用者自己按；跳出的金鑰視窗 Claude 不截圖。
5. 回到憑證清單應看到一列：名稱 `claude-youtube`、限制「YouTube Data API v3」、「顯示金鑰」按鈕。
6. 終端機自己輸入 `python installer/install.py web --key youtube=金鑰`。
配額：每天 100 次 `search.list`、其他讀取共 10,000 單位（`videos.list`、`commentThreads.list` 各 1），太平洋時間午夜重置（https://developers.google.com/youtube/data/determine_quota_cost ）。`video.py` 的 `search` 預設不用它。

## 直播

`--live 秒數`（10–900）用 ffmpeg 從 HLS 串流錄一段成 mp4，之後當本機檔跑逐字稿／截圖／Gemini。這不是持續監看，每次只錄一段；錄的片段存在該影片的快取資料夾 `live_<時間>.mp4`，`live_captures.txt` 記錄每次擷取時間，7 天沒用自動刪。2026-10-27 實測台視與東森 24 小時新聞台：45 秒錄 33 秒，語音辨識中文正確。

## 不做的事

- 不裝第三方 YouTube MCP：都是本機常駐程序＋各自依賴，底層同樣是 yt-dlp；單檔 CLI 沒有背景程序、跨裝置只要 pip。
- 不保存、不散布影片；快取只為分析，`clean` 可清。
- 不繞 YouTube 的 bot check：被擋（429／「Sign in to confirm you're not a bot」）就停，不換 IP、不塞 cookies。家用網路正常，雲端或 VPN IP 會被擋。

## 故障排除

- `yt-dlp 失敗`：先 `python -m pip install -U yt-dlp`（YouTube 常改版），再試一次；仍不行查 https://github.com/yt-dlp/yt-dlp/issues 。
- 只有英文自動字幕但影片是中文：那是 YouTube 語言誤判，`video.py` 會自動改走語音辨識；要強制用自動字幕 `--lang en`。
- `沒有字幕，且本機沒裝 faster-whisper`：裝它，或改用 `frames`／`ask`。
- Gemini 503：模型高負載，工具已重試 3 次並換備用模型；仍失敗等幾分鐘。
- 快取太大：`video.py clean --media-only`（刪影音留逐字稿）或 `clean --all`。
