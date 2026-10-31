#!/usr/bin/env python3
"""video.py：讓 Claude Code「找影片、聽影片、看影片畫面」的單一入口（YouTube、yt-dlp 支援的 1,700+ 站、直接 mp4 網址、本機檔）。

設計原則：**拉取不傾倒**——逐字稿、截圖都先寫進快取資料夾，螢幕只印路徑、摘要與前幾行，長影片不會灌爆對話；
**字幕優先**——有字幕幾秒鐘拿到，沒字幕才下載純音訊跑本機 faster-whisper；**畫面是截圖**——Claude 不能直接看影片，
用 ffmpeg 切關鍵畫面讓 Claude 用 Read 看圖；真的要逐幀理解動作才走選用的 Gemini（需 `gemini` 金鑰）。

用法（`py -3 ~/.claude/claude-dev-system/tools/video.py <子命令> …`；`--help` 看全部參數）：
  search  關鍵字 [-n 5] [--date week] [--api]      找影片：預設 yt-dlp 免金鑰；--api 用 YouTube Data API（每天 100 次搜尋）
  info    網址                                      標題、頻道、長度、上傳日、章節、有哪些字幕語言
  transcript 網址|檔案 [--lang zh-TW,zh-Hant,zh,en] [--asr] [--model medium] [--grep 字] [--full]
                                                     逐字稿：字幕 → 沒有就 ASR；印路徑＋前 40 行；--grep 找關鍵字帶時間戳
  frames  網址|檔案 [--mode scene|interval] [--interval 10] [--max 40] [--at 12:30,14:05]   關鍵畫面截圖到快取，印每張的時間點；--at 只截指定時間點
  （transcript／frames／ask 都可加 --live 秒數：進行中的直播先錄一段再處理，10–900 秒）
  stats   網址                                      觀看／按讚／留言數、發布時間（YouTube Data API，需 `youtube` 金鑰）
  comments 網址 [-n 20]                             熱門留言（YouTube Data API，需 `youtube` 金鑰）
  ask     網址|檔案 "問題" [--model gemini-flash-latest] [--clip 開始 結束]   Gemini 真的看影片（需 `gemini` 金鑰；公開 YouTube 免下載）
  download 網址 [--out 資料夾] [--max-height 1080] [--audio-only] [--cookies-from-browser firefox | --cookies cookies.txt]   使用者要存檔時：最高畫質下載（預設 local.json video.downloadDir，未設為 ~/Downloads）
  setup                                              檢查依賴與金鑰
  clean   [--older-than 30] [--all] [--media-only]    清快取（影音檔大，逐字稿小）；每次執行也會自動清超過 7 天沒用的影音檔、30 天的整個資料夾

金鑰讀 <CLAUDE_HOME>/claude-dev-system/config/local.json 的 keys.youtube／keys.gemini（`install.py web --key youtube=…`）。
快取：<CLAUDE_HOME>/claude-dev-system/cache/video/<影片ID>/（info.json、transcript.*.txt、audio.m4a、video.mp4、frames/）。
退出碼：0 成功；2 參數或缺依賴；3 來源拿不到（私人影片、被擋、沒字幕又沒 ASR）。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ---------- 路徑與設定 ----------

def claude_home() -> Path:
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env).expanduser() if env else Path.home() / ".claude"


HOME = claude_home()
PAYLOAD = HOME / "claude-dev-system"
CONFIG_PATH = PAYLOAD / "config" / "video.json"
LOCAL_PATH = PAYLOAD / "config" / "local.json"
DEFAULTS = {
    "cacheDir": "claude-dev-system/cache/video",
    "whisperModel": "medium",
    "geminiModel": "gemini-flash-latest",
    "preferLangs": ["zh-TW", "zh-Hant", "zh", "zh-Hans", "en", "ja"],
    "previewLines": 40,
    "maxFrames": 40,
    "sceneThreshold": 0.35,
    "downloadHeight": 720,
    "sleepBetweenRequests": 1,
    "autoCleanMediaDays": 7,
    "autoCleanAllDays": 30,
}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update({k: v for k, v in json.loads(CONFIG_PATH.read_text(encoding="utf-8")).items() if not k.startswith("_")})
        except Exception as e:  # noqa: BLE001
            warn(f"video.json 讀取失敗（{e}），用內建預設")
    return cfg


def load_keys() -> dict:
    if not LOCAL_PATH.exists():
        return {}
    try:
        d = json.loads(LOCAL_PATH.read_text(encoding="utf-8"))
        return {k: v for k, v in (d.get("keys") or {}).items() if v}
    except Exception:  # noqa: BLE001
        return {}


def load_local_video() -> dict:
    """local.json 的 video 區塊：本機覆寫（例如 downloadDir），不進 repo。"""
    if not LOCAL_PATH.exists():
        return {}
    try:
        v = json.loads(LOCAL_PATH.read_text(encoding="utf-8")).get("video") or {}
        return v if isinstance(v, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def download_dir(out: str | None = None) -> Path:
    """--out ＞ local.json video.downloadDir ＞ video.json downloadDir ＞ ~/Downloads。"""
    d = out or CFG.get("downloadDir")
    return Path(d).expanduser() if d else Path.home() / "Downloads"


CFG = load_config()
CFG.update(load_local_video())
KEYS = load_keys()


def cache_root() -> Path:
    p = HOME / CFG["cacheDir"]
    p.mkdir(parents=True, exist_ok=True)
    return p


def warn(msg: str) -> None:
    print(f"⚠️ {msg}", file=sys.stderr)


def die(msg: str, code: int = 2) -> None:
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(code)


# ---------- 依賴 ----------

def find_ffmpeg() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
        hits = sorted(glob.glob(str(base / "Gyan.FFmpeg*" / "*" / "bin" / "ffmpeg.exe")))
        if hits:
            return hits[-1]
    return None


def have(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:  # noqa: BLE001
        return False


def _preload_cuda_dlls() -> None:
    """Windows：讓 ctranslate2 用得到 pip 裝的 nvidia-cublas-cu12／cudnn（這些 DLL 不在 PATH，且 ctranslate2 不吃 add_dll_directory）。"""
    if sys.platform != "win32":
        return
    import ctypes
    import site
    names = ["nvrtc64_120_0.dll", "cublasLt64_12.dll", "cublas64_12.dll", "cudnn_graph64_9.dll",
             "cudnn_engines_precompiled64_9.dll", "cudnn_engines_runtime_compiled64_9.dll", "cudnn_heuristic64_9.dll",
             "cudnn_ops64_9.dll", "cudnn_cnn64_9.dll", "cudnn_adv64_9.dll", "cudnn_engines_tensor_ir64_9.dll",
             "cudnn_ext64_9.dll", "cudnn64_9.dll"]
    for pkg_dir in site.getsitepackages() + [site.getusersitepackages()]:
        for sub in ("cublas", "cudnn", "cuda_nvrtc"):
            bin_dir = Path(pkg_dir) / "nvidia" / sub / "bin"
            if bin_dir.is_dir():
                os.add_dll_directory(str(bin_dir))
                for name in names:
                    p = bin_dir / name
                    if p.exists():
                        try:
                            ctypes.WinDLL(str(p))
                        except OSError:
                            pass


# ---------- 來源判斷與快取 ----------

YT_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/live/|/embed/)([A-Za-z0-9_-]{11})")


def youtube_id(src: str) -> str | None:
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", src):
        return src
    m = YT_ID_RE.search(src)
    return m.group(1) if m and ("youtube.com" in src or "youtu.be" in src) else None


def is_url(src: str) -> bool:
    return src.startswith(("http://", "https://"))


def source_key(src: str) -> str:
    vid = youtube_id(src)
    if vid:
        return "yt_" + vid
    if is_url(src):
        import hashlib
        return "url_" + hashlib.sha1(src.encode("utf-8")).hexdigest()[:12]
    p = Path(src).resolve()
    import hashlib
    return "file_" + hashlib.sha1(str(p).encode("utf-8")).hexdigest()[:12]


def cache_dir(src: str) -> Path:
    d = cache_root() / source_key(src)
    d.mkdir(parents=True, exist_ok=True)
    return d


def canonical(src: str) -> str:
    vid = youtube_id(src)
    return f"https://www.youtube.com/watch?v={vid}" if vid else src


# ---------- yt-dlp ----------

def ydl_opts(extra: dict | None = None) -> dict:
    o = {"quiet": True, "no_warnings": True, "noprogress": True, "sleep_interval_requests": CFG["sleepBetweenRequests"],
         "socket_timeout": 30, "retries": 2}
    # YouTube 要用 JS runtime 解挑戰，否則缺高畫質格式、下載被限速（yt-dlp wiki/EJS）。deno 預設；沒有就用 node（≥22）。
    if not shutil.which("deno") and shutil.which("node"):
        o["js_runtimes"] = {"node": {}}
    if extra:
        o.update(extra)
    return o


def need_ytdlp():
    try:
        import yt_dlp  # noqa: F401
        return yt_dlp
    except ImportError:
        die("缺 yt-dlp：`py -3 installer/install.py update --with-video` 或 `py -3 -m pip install \"yt-dlp[default,curl-cffi]\"`")


def _ydl_error(e: Exception) -> None:
    s = str(e)
    if "Sign in to confirm" in s or "LOGIN_REQUIRED" in s or "429" in s:
        die("YouTube 擋了這個 IP（bot check／429）。等幾分鐘再試、不要批量重試；雲端或 VPN IP 會被擋，家用網路通常正常。原文：" + s[:200], 3)
    if "Private video" in s or "This video is private" in s:
        die("私人影片，拿不到。", 3)
    if "Video unavailable" in s:
        die("影片不存在或已下架。", 3)
    die("yt-dlp 失敗：" + s[:300], 3)


def extract_info(src: str, flat: bool = False) -> dict:
    yt_dlp = need_ytdlp()
    try:
        with yt_dlp.YoutubeDL(ydl_opts({"extract_flat": flat, "skip_download": True})) as y:
            return y.sanitize_info(y.extract_info(canonical(src), download=False))
    except Exception as e:  # noqa: BLE001
        _ydl_error(e)
        raise


def info_cached(src: str) -> dict:
    d = cache_dir(src)
    p = d / "info.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    if not is_url(src):
        f = Path(src)
        if not f.exists():
            die(f"找不到檔案：{f}")
        info = {"id": source_key(src), "title": f.stem, "webpage_url": str(f.resolve()), "duration": media_duration(f),
                "extractor": "local", "subtitles": {}, "automatic_captions": {}}
    else:
        full = extract_info(src)
        keep = ["id", "title", "channel", "uploader", "duration", "upload_date", "view_count", "like_count", "comment_count",
                "description", "chapters", "language", "webpage_url", "extractor", "live_status", "tags", "categories"]
        info = {k: full.get(k) for k in keep}
        info["subtitles"] = sorted((full.get("subtitles") or {}).keys())
        info["automatic_captions"] = sorted((full.get("automatic_captions") or {}).keys())
    p.write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    return info


def media_duration(f: Path) -> float | None:
    ff = find_ffmpeg()
    if not ff:
        return None
    probe = Path(ff).with_name("ffprobe" + (".exe" if sys.platform == "win32" else ""))
    if not probe.exists():
        return None
    r = subprocess.run([str(probe), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def download(src: str, kind: str) -> Path:
    """kind=audio → audio.m4a（純音訊，最小）；kind=video → video.mp4（≤ downloadHeight）。已存在就直接用。"""
    d = cache_dir(src)
    if not is_url(src):
        return Path(src).resolve()
    target = d / ("audio.m4a" if kind == "audio" else "video.mp4")
    if target.exists() and target.stat().st_size > 0:
        return target
    yt_dlp = need_ytdlp()
    h = CFG["downloadHeight"]
    fmt = "bestaudio[ext=m4a]/bestaudio/best" if kind == "audio" else f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/best[height<={h}][ext=mp4]/best[height<={h}]/best"
    opts = ydl_opts({"format": fmt, "outtmpl": str(d / ("audio.%(ext)s" if kind == "audio" else "video.%(ext)s")),
                     "merge_output_format": None if kind == "audio" else "mp4"})
    ff = find_ffmpeg()
    if ff:
        opts["ffmpeg_location"] = str(Path(ff).parent)
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            y.download([canonical(src)])
    except Exception as e:  # noqa: BLE001
        _ydl_error(e)
    hits = sorted(d.glob("audio.*" if kind == "audio" else "video.*"), key=lambda p: p.stat().st_mtime)
    if not hits:
        die("下載後找不到檔案", 3)
    got = hits[-1]
    if got != target:
        if kind == "audio" and ff and got.suffix not in (".m4a",):
            subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(got), "-vn", "-c:a", "aac", "-b:a", "64k", str(target)], check=True)
            got.unlink(missing_ok=True)
        else:
            got.replace(target)
    return target


def capture_live(src: str, seconds: int) -> Path:
    """直播：用 ffmpeg 從 HLS 串流錄 N 秒（≤720p 影像＋音訊）成 mp4，之後當本機檔處理。不是持續監看，是「錄一段」。"""
    ff = find_ffmpeg()
    if not ff:
        die("缺 ffmpeg（winget install Gyan.FFmpeg）", 2)
    seconds = max(10, min(int(seconds), 900))
    yt_dlp = need_ytdlp()
    try:
        with yt_dlp.YoutubeDL(ydl_opts({"skip_download": True})) as y:
            info = y.extract_info(canonical(src), download=False)
    except Exception as e:  # noqa: BLE001
        _ydl_error(e)
    if not info.get("is_live"):
        die(f"這不是進行中的直播（live_status={info.get('live_status')}），直接用一般的 transcript／frames 即可", 2)
    fmts = info.get("formats") or []
    aud = [f for f in fmts if f.get("vcodec") == "none" and f.get("url")]
    vid = [f for f in fmts if f.get("vcodec") not in (None, "none") and (f.get("height") or 0) <= CFG["downloadHeight"] and f.get("url")]
    both = [f for f in fmts if f.get("vcodec") not in (None, "none") and f.get("acodec") not in (None, "none") and f.get("url")]
    d = cache_dir(src)
    out = d / f"live_{time.strftime('%Y%m%d-%H%M%S')}.mp4"
    if vid and aud:
        v, a = sorted(vid, key=lambda f: f.get("height") or 0)[-1], aud[-1]
        cmd = [ff, "-y", "-loglevel", "error", "-i", v["url"], "-i", a["url"], "-t", str(seconds), "-map", "0:v", "-map", "1:a", "-c", "copy", str(out)]
    elif both:
        cmd = [ff, "-y", "-loglevel", "error", "-i", both[-1]["url"], "-t", str(seconds), "-c", "copy", str(out)]
    else:
        die("直播串流找不到可用的影音格式", 3)
    print(f"錄直播 {seconds} 秒（{info.get('title', '')[:40]}）…", file=sys.stderr)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=seconds + 300)
    if r.returncode != 0 or not out.exists():
        die("直播擷取失敗：" + r.stderr.strip()[-300:], 3)
    (d / "live_captures.txt").open("a", encoding="utf-8").write(f"{out.name}\t{time.strftime('%Y-%m-%d %H:%M:%S')}\t{seconds}s\n")
    print(f"直播片段已存 {out}（擷取時間 {time.strftime('%Y-%m-%d %H:%M')}，{seconds} 秒）", file=sys.stderr)
    return out


# ---------- 時間格式 ----------

def hms(sec: float) -> str:
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def parse_time(s: str) -> float:
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return float(s)
    parts = [float(x) for x in s.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


# ---------- 逐字稿 ----------

def _caption_choice(info: dict, prefer: list[str]) -> tuple[str, str] | None:
    """回傳 (語言碼, 'manual'|'auto')：手動字幕依偏好序 → 自動字幕依偏好序 → 任一手動 → 無。"""
    manual, auto = set(info.get("subtitles") or []), set(info.get("automatic_captions") or [])
    manual = {m for m in manual if not m.startswith("live_chat")}
    for lang in prefer:
        for cand in (lang, lang.lower()):
            if cand in manual:
                return cand, "manual"
    for lang in prefer:
        for cand in (lang, lang.lower()):
            if cand in auto:
                return cand, "auto"
    if manual:
        return sorted(manual)[0], "manual"
    return None


def _yt_tracks(vid: str) -> list | None:
    """YouTube 字幕軌清單（youtube-transcript-api）：只列「原生」軌——手動上傳的與 YouTube 自己辨識的；自動翻譯軌不列。失敗回 None。"""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None
    try:
        return list(YouTubeTranscriptApi().list(vid))
    except Exception as e:  # noqa: BLE001
        warn(f"youtube-transcript-api 失敗（{type(e).__name__}），改用 yt-dlp 看字幕")
        return None


def _fetch_track(t) -> list[tuple[float, float, str]] | None:
    try:
        return [(s.start, s.start + (s.duration or 0), s.text.replace("\n", " ").strip()) for s in t.fetch().snippets]
    except Exception as e:  # noqa: BLE001
        warn(f"字幕下載失敗（{type(e).__name__}）")
        return None


def _lang_match(a: str | None, b: str | None) -> bool:
    return bool(a and b) and a.lower()[:2] == b.lower()[:2]


def _vtt_parse(text: str) -> list[tuple[float, float, str]]:
    out: list[tuple[float, float, str]] = []
    last = None
    for block in re.split(r"\n\s*\n", text):
        m = re.search(r"(\d+:\d+:\d+\.\d+|\d+:\d+\.\d+)\s*-->\s*(\d+:\d+:\d+\.\d+|\d+:\d+\.\d+)", block)
        if not m:
            continue
        body = block[m.end():].strip()
        body = re.sub(r"<[^>]+>", "", body)
        body = re.sub(r"\s+", " ", body).strip()
        if not body or body == last:
            continue
        last = body
        out.append((parse_time(m.group(1)), parse_time(m.group(2)), body))
    # 自動字幕是滾動式，相鄰重複行去掉
    dedup: list[tuple[float, float, str]] = []
    for s, e, t in out:
        if dedup and (t in dedup[-1][2] or dedup[-1][2] in t):
            if len(t) > len(dedup[-1][2]):
                dedup[-1] = (dedup[-1][0], e, t)
            continue
        dedup.append((s, e, t))
    return dedup


def _ytdlp_subs(src: str, lang: str, auto: bool) -> list[tuple[float, float, str]] | None:
    yt_dlp = need_ytdlp()
    d = cache_dir(src)
    opts = ydl_opts({"skip_download": True, "writesubtitles": not auto, "writeautomaticsub": auto, "subtitleslangs": [lang],
                     "subtitlesformat": "vtt/best", "outtmpl": str(d / "sub.%(ext)s")})
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            y.download([canonical(src)])
    except Exception as e:  # noqa: BLE001
        warn(f"yt-dlp 字幕下載失敗：{str(e)[:150]}")
        return None
    files = sorted(d.glob(f"sub.{lang}.*")) or sorted(d.glob("sub.*.vtt")) or sorted(d.glob("sub.*"))
    if not files:
        return None
    text = files[-1].read_text(encoding="utf-8", errors="replace")
    return _vtt_parse(text) if "-->" in text else None


def _asr(src: str, model_size: str, lang: str | None) -> tuple[list[tuple[float, float, str]], str]:
    if not have("faster_whisper"):
        die("沒有字幕，且本機沒裝 faster-whisper 做語音辨識：`py -3 -m pip install faster-whisper`（NVIDIA GPU 另加 nvidia-cublas-cu12 nvidia-cudnn-cu12）", 3)
    ff = find_ffmpeg()
    if not ff:
        die("缺 ffmpeg（winget install Gyan.FFmpeg）", 2)
    audio = download(src, "audio")
    d = cache_dir(src)
    wav = d / "audio16k.wav"
    if not wav.exists():
        r = subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(audio), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            audio.unlink(missing_ok=True)  # 多半是下載到壞檔；刪掉讓下次重抓
            die("ffmpeg 轉音訊失敗（已刪快取的音訊檔，重跑一次會重新下載）：" + r.stderr.strip()[-300:], 3)
    _preload_cuda_dlls()
    from faster_whisper import WhisperModel
    device = "cuda"
    try:
        model = WhisperModel(model_size, device="cuda", compute_type="int8_float16")
        segs, _ = model.transcribe(str(wav), language=lang, vad_filter=True)
        segs = list(segs)
    except Exception as e:  # noqa: BLE001
        warn(f"GPU 推論失敗（{str(e)[:80]}），改用 CPU（較慢）")
        device = "cpu"
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segs, _ = model.transcribe(str(wav), language=lang, vad_filter=True)
        segs = list(segs)
    wav.unlink(missing_ok=True)  # 16k wav 每 30 分鐘約 60MB，辨識完就刪；m4a 留著供重跑
    return [(s.start, s.end, s.text.strip()) for s in segs], f"whisper-{model_size}-{device}"


def write_transcript(d: Path, tag: str, segs: list[tuple[float, float, str]]) -> Path:
    p = d / f"transcript.{tag}.txt"
    with p.open("w", encoding="utf-8") as f:
        for s, _e, t in segs:
            f.write(f"[{hms(s)}] {t}\n")
    return p


def get_transcript(src: str, prefer: list[str], asr: bool, model_size: str, lang: str | None, lang_explicit: bool = False) -> tuple[Path, str, str]:
    """回傳 (檔案, 來源標籤, 語言)。來源標籤：youtube_manual／youtube_auto／subs_manual／subs_auto／whisper-*。"""
    d = cache_dir(src)
    existing = sorted(d.glob("transcript.*.txt"))
    if existing and lang_explicit and not any(p.name.lower().endswith(f".{x.lower()}.txt") for p in existing for x in prefer):
        existing = []  # 使用者指定了語言而快取沒有那個語言：重抓
    if existing and not asr:
        best = next((p for p in existing if "manual" in p.name), None) or next((p for p in existing if "whisper" in p.name), None) or existing[0]
        tag = best.name[len("transcript."):-4]
        return best, tag.rsplit(".", 1)[0], tag.rsplit(".", 1)[-1]
    info = info_cached(src)
    vid = youtube_id(src) if is_url(src) else None
    spoken = info.get("language")  # 上傳者標的影片語言（可能沒有）
    tracks = _yt_tracks(vid) if (vid and not asr) else None
    if tracks is not None:
        # 1) 手動字幕依偏好序  2) YouTube 原生自動字幕，但語言要和影片語言（或偏好）一致  3) 不一致 → ASR（有裝時）
        manual = [t for t in tracks if not t.is_generated]
        auto = [t for t in tracks if t.is_generated]
        pick = next((t for p in prefer for t in manual if t.language_code.lower() == p.lower()), None) or (manual[0] if manual else None)
        kind = "manual"
        if pick is None and auto:
            ok = [t for t in auto if (_lang_match(t.language_code, spoken) if spoken else any(_lang_match(t.language_code, p) for p in prefer))]
            if ok:
                pick, kind = ok[0], "auto"
            elif have("faster_whisper"):
                warn(f"YouTube 自動字幕語言是 {','.join(t.language_code for t in auto)}，與影片語言 {spoken or '／'.join(prefer[:2])} 不符（常是語言誤判，翻譯稿不可信），改用本機語音辨識")
            else:
                pick, kind = auto[0], "auto"
                warn(f"只有 {pick.language_code} 自動字幕且本機沒有 faster-whisper，姑且使用；內容可能是誤判語言的機器稿")
        if pick is not None:
            segs = _fetch_track(pick)
            if segs:
                return write_transcript(d, f"youtube_{kind}.{pick.language_code}", segs), "youtube_" + kind, pick.language_code
    elif is_url(src) and not asr:
        choice = _caption_choice(info, prefer)  # transcript-api 不可用時退回 yt-dlp 的字幕清單（含自動翻譯軌）
        if choice:
            lang_code, kind = choice
            segs = _ytdlp_subs(src, lang_code, kind == "auto")
            if segs:
                return write_transcript(d, f"subs_{kind}.{lang_code}", segs), "subs_" + kind, lang_code
            warn("字幕抓不到，改用語音辨識")
    segs, tag = _asr(src, model_size, lang)
    code = lang or (info.get("language") or "auto")
    return write_transcript(d, f"{tag}.{code}", segs), tag, code


# ---------- 畫面 ----------

def frames_at(src: str, times: list[float]) -> tuple[Path, list[tuple[str, float]]]:
    """指定時間點各截一張（逐字稿裡出現「這個／這裡／看一下」時用）。存到 frames_at/，不動場景截圖。"""
    ff = find_ffmpeg()
    if not ff:
        die("缺 ffmpeg（winget install Gyan.FFmpeg）", 2)
    media = download(src, "video")
    d = cache_dir(src)
    out = d / "frames_at"
    out.mkdir(exist_ok=True)
    pairs = []
    for t in times:
        name = f"at_{hms(t).replace(':', '')}.jpg"
        r = subprocess.run([ff, "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(media), "-frames:v", "1", "-q:v", "3", str(out / name)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode == 0 and (out / name).exists():
            pairs.append((name, t))
        else:
            warn(f"{hms(t)} 截圖失敗（超過影片長度？）")
    return out, pairs


def extract_frames(src: str, mode: str, interval: float, max_frames: int) -> tuple[Path, list[tuple[str, float]]]:
    ff = find_ffmpeg()
    if not ff:
        die("缺 ffmpeg（winget install Gyan.FFmpeg）", 2)
    if max_frames < 2:
        die("--max 至少 2")
    if interval <= 0:
        die("--interval 必須大於 0")
    media = download(src, "video")
    d = cache_dir(src)
    frames = d / "frames"
    frames.mkdir(exist_ok=True)
    for f in frames.glob("*.jpg"):
        f.unlink()
    duration = info_cached(src).get("duration") or media_duration(media) or 0

    def run(vf: str) -> list[float]:
        r = subprocess.run([ff, "-y", "-loglevel", "info", "-i", str(media), "-vf", vf + ",showinfo", "-fps_mode", "vfr", "-q:v", "3",
                            str(frames / "frame_%04d.jpg")], capture_output=True, text=True, encoding="utf-8", errors="replace")
        return [float(x) for x in re.findall(r"pts_time:\s*([0-9.]+)", r.stderr)]

    times: list[float] = []
    if mode == "scene":
        times = run(f"select='gt(scene,{CFG['sceneThreshold']})'")
        if len(times) < 3:
            for f in frames.glob("*.jpg"):
                f.unlink()
            mode = "interval"
    if mode == "interval":
        if duration and duration / interval > max_frames:
            interval = duration / max_frames
        times = run(f"fps=1/{interval}")
    files = sorted(frames.glob("frame_*.jpg"))
    if len(files) > max_frames:  # 場景太多：等距抽樣到上限
        keep = {files[int(i * (len(files) - 1) / (max_frames - 1))] for i in range(max_frames)}
        for f in files:
            if f not in keep:
                f.unlink()
        pairs = [(f.name, times[i] if i < len(times) else 0.0) for i, f in enumerate(files) if f in keep]
    else:
        pairs = [(f.name, times[i] if i < len(times) else 0.0) for i, f in enumerate(files)]
    (frames / "index.txt").write_text("".join(f"{n}\t{hms(t)}\n" for n, t in pairs), encoding="utf-8")
    return frames, pairs


# ---------- YouTube Data API ----------

def yt_api(path: str, params: dict) -> dict:
    key = KEYS.get("youtube")
    if not key:
        die("沒有 `youtube` 金鑰（YouTube Data API）：`py -3 installer/install.py web --key youtube=…`；或改用免金鑰的 search／info", 2)
    url = "https://www.googleapis.com/youtube/v3/" + path + "?" + urllib.parse.urlencode({**params, "key": key})
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        if isinstance(e, urllib.error.HTTPError):
            raise
        die(f"連不上 YouTube Data API（網路或逾時）：{getattr(e, 'reason', e)}", 3)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            msg = json.loads(body)["error"]["message"]
        except Exception:  # noqa: BLE001
            msg = body[:200]
        if e.code == 403 and "quota" in msg.lower():
            die("YouTube Data API 今日配額用完（太平洋時間午夜重置）；改用免金鑰的 search／info。原文：" + msg, 3)
        die(f"YouTube Data API {e.code}：{msg}", 3)


def iso_duration(s: str) -> str:
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return s or "?"
    h, mi, se = (int(x or 0) for x in m.groups())
    return hms(h * 3600 + mi * 60 + se)


# ---------- Gemini ----------

GEMINI = "https://generativelanguage.googleapis.com"


def gemini_req(method: str, url: str, data: bytes | None = None, headers: dict | None = None) -> tuple[dict, dict]:
    key = KEYS.get("gemini")
    if not key:
        die("沒有 `gemini` 金鑰：https://aistudio.google.com/api-keys 建立後 `py -3 installer/install.py web --key gemini=…`", 2)
    h = {"x-goog-api-key": key, **(headers or {})}
    for attempt in range(3):
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                raw = r.read()
                return (json.loads(raw.decode("utf-8")) if raw else {}), dict(r.headers)
        except (TimeoutError, urllib.error.URLError, OSError) as e:
            if isinstance(e, urllib.error.HTTPError):
                err = e
            else:
                if attempt < 2:
                    warn(f"連 Gemini 失敗（{getattr(e, 'reason', e)}），{5 * (attempt + 1)} 秒後重試")
                    time.sleep(5 * (attempt + 1))
                    continue
                raise GeminiError(0, f"網路或逾時：{getattr(e, 'reason', e)}（大檔上傳可改先用 --clip 或縮短影片）")
            e = err
            body = e.read().decode("utf-8", "replace")  # 以下處理 HTTPError
            try:
                msg = json.loads(body)["error"]["message"]
            except Exception:  # noqa: BLE001
                msg = body[:300]
            if e.code in (503, 500) and attempt < 2:
                warn(f"Gemini {e.code}（{msg[:60]}），{5 * (attempt + 1)} 秒後重試")
                time.sleep(5 * (attempt + 1))
                continue
            if e.code == 429:
                raise GeminiError(429, "額度或速率用完（免費層依模型：3.8 Flash 每天 20 次、每分鐘 5 次；3.5 Flash Lite 每天 500 次）：" + msg[:120])
            raise GeminiError(e.code, msg)
    raise GeminiError(0, "重試用盡")


class GeminiError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(f"Gemini {code}：{msg}")
        self.code = code


def gemini_upload(path: Path) -> dict:
    """Files API 可續傳上傳：回 file 物件（uri、state）。等到 ACTIVE 才能用。"""
    mime = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".m4a": "audio/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav",
            ".mkv": "video/x-matroska", ".avi": "video/x-msvideo"}.get(path.suffix.lower(), "video/mp4")
    size = path.stat().st_size
    meta = json.dumps({"file": {"display_name": path.name}}).encode("utf-8")
    _, hdrs = gemini_req("POST", f"{GEMINI}/upload/v1beta/files", meta, {
        "X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start",
        "X-Goog-Upload-Header-Content-Length": str(size), "X-Goog-Upload-Header-Content-Type": mime, "Content-Type": "application/json"})
    up = next((v for k, v in hdrs.items() if k.lower() == "x-goog-upload-url"), None)
    if not up:
        die("Gemini 上傳：拿不到 upload URL", 3)
    body, _ = gemini_req("POST", up, path.read_bytes(), {"X-Goog-Upload-Offset": "0", "X-Goog-Upload-Command": "upload, finalize", "Content-Length": str(size)})
    f = body.get("file") or {}
    name = f.get("name")
    for _ in range(120):
        if f.get("state") == "ACTIVE":
            break
        if f.get("state") == "FAILED":
            die("Gemini 處理檔案失敗", 3)
        time.sleep(5)
        f, _ = gemini_req("GET", f"{GEMINI}/v1beta/{name}")
    f["mime"] = mime
    return f


def gemini_ask(src: str, question: str, model: str, clip: tuple[str, str] | None) -> str:
    vid = youtube_id(src) if is_url(src) else None
    if vid:
        part = {"file_data": {"file_uri": canonical(src)}}
    else:
        path = download(src, "video") if is_url(src) else Path(src).resolve()
        if not path.exists():
            die(f"找不到檔案：{path}")
        f = gemini_upload(path)
        part = {"file_data": {"file_uri": f["uri"], "mime_type": f["mime"]}}
    if clip:
        part["video_metadata"] = {"start_offset": f"{int(parse_time(clip[0]))}s", "end_offset": f"{int(parse_time(clip[1]))}s"}
    body = {"contents": [{"parts": [part, {"text": question}]}]}
    models = [model] + [m for m in CFG.get("geminiFallbackModels", []) if m != model]
    out = None
    for i, m in enumerate(models):
        try:
            out, _ = gemini_req("POST", f"{GEMINI}/v1beta/models/{m}:generateContent", json.dumps(body).encode("utf-8"), {"Content-Type": "application/json"})
            if i:
                warn(f"改用備用模型 {m}")
            break
        except GeminiError as e:
            if e.code in (503, 500, 404, 429) and i < len(models) - 1:
                warn(f"{m} 失敗（{e}），換下一個模型")
                continue
            die(str(e) + ("；等明天（太平洋時間午夜重置）或換 --model" if e.code == 429 else ""), 3)
    try:
        return "".join(p.get("text", "") for p in out["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError, TypeError):
        die("Gemini 沒有回答內容：" + json.dumps(out, ensure_ascii=False)[:400], 3)


# ---------- 子命令 ----------

def cmd_setup(_a) -> int:
    rows = []
    ff = find_ffmpeg()
    rows.append(("ffmpeg", bool(ff), ff or "缺（winget install Gyan.FFmpeg）"))
    try:
        import yt_dlp
        rows.append(("yt-dlp", True, yt_dlp.version.__version__ + "（舊了會抓不到；更新：py -3 -m pip install -U yt-dlp）"))
    except ImportError:
        rows.append(("yt-dlp", False, "缺（install.py update --with-video）"))
    rows.append(("youtube-transcript-api", have("youtube_transcript_api"), "字幕第一優先來源" if have("youtube_transcript_api") else "缺（install.py update --with-video）"))
    rows.append(("curl_cffi", have("curl_cffi"), "yt-dlp 瀏覽器指紋模擬（選用）" if have("curl_cffi") else "缺（選用；少了偶爾會被擋）"))
    if have("faster_whisper"):
        import faster_whisper
        rows.append(("faster-whisper", True, f"{faster_whisper.__version__}（沒字幕時的語音辨識，模型 {CFG['whisperModel']}）"))
    else:
        rows.append(("faster-whisper", None, "未裝：沒字幕的影片無法轉逐字稿（py -3 -m pip install faster-whisper）"))
    rows.append(("金鑰 youtube", bool(KEYS.get("youtube")), "有（stats／comments／search --api 可用）" if KEYS.get("youtube") else "無（選用；stats／comments 不可用）"))
    rows.append(("金鑰 gemini", bool(KEYS.get("gemini")), "有（ask 可用）" if KEYS.get("gemini") else "無（選用；ask 不可用）"))
    rows.append(("快取", True, str(cache_root())))
    for name, ok, msg in rows:
        print(f"{'✅' if ok else ('⚠️' if ok is None else '❌')} {name}：{msg}")
    return 0 if all(ok is not False for _, ok, _ in rows[:3]) else 2


def cmd_search(a) -> int:
    if a.api:
        params = {"part": "snippet", "q": a.query, "type": "video", "maxResults": min(a.n, 50), "regionCode": "TW", "relevanceLanguage": "zh-Hant"}
        if a.date:
            import datetime as dt
            days = {"hour": 1 / 24, "today": 1, "week": 7, "month": 31, "year": 365}[a.date]
            params["publishedAfter"] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        res = yt_api("search", params)
        print(f"來源：YouTube Data API search.list（每天 100 次；這次用 1 次）")
        for it in res.get("items", []):
            s, vid = it["snippet"], it["id"]["videoId"]
            print(f"{vid} | {s['title']} | {s['channelTitle']} | {s['publishedAt'][:10]} | https://www.youtube.com/watch?v={vid}")
        return 0
    yt_dlp = need_ytdlp()
    if a.date:
        warn("--date 只在 --api 模式生效（yt-dlp 的 ytsearch 沒有日期篩選）")
    try:
        with yt_dlp.YoutubeDL(ydl_opts({"extract_flat": True, "skip_download": True})) as y:
            res = y.extract_info(f"ytsearch{a.n}:{a.query}", download=False)
    except Exception as e:  # noqa: BLE001
        _ydl_error(e)
    print("來源：yt-dlp ytsearch（免金鑰；相關度排序；要日期篩選或數據用 --api）")
    for e in res.get("entries") or []:
        dur = hms(e["duration"]) if e.get("duration") else "直播/未知"
        views = f"{e['view_count']:,}" if e.get("view_count") else "?"
        print(f"{e.get('id')} | {e.get('title')} | {dur} | {e.get('channel') or e.get('uploader') or '?'} | 觀看 {views} | {e.get('url') or e.get('webpage_url')}")
    return 0


def cmd_info(a) -> int:
    info = info_cached(a.src)
    print(f"標題：{info.get('title')}")
    print(f"頻道：{info.get('channel') or info.get('uploader') or '?'}；長度：{hms(info['duration']) if info.get('duration') else '?'}；上傳：{info.get('upload_date') or '?'}；觀看：{info.get('view_count') or '?'}；語言欄：{info.get('language') or '?'}")
    print(f"網址：{info.get('webpage_url')}；來源站：{info.get('extractor')}；直播狀態：{info.get('live_status') or '非直播'}" + ("（進行中：用 --live 秒數 錄一段）" if info.get("live_status") == "is_live" else ""))
    print(f"手動字幕：{', '.join(info.get('subtitles') or []) or '無'}")
    auto = info.get("automatic_captions") or []
    print(f"自動字幕：{', '.join(auto[:12]) + ('…' if len(auto) > 12 else '') if auto else '無'}")
    ch = info.get("chapters") or []
    if ch:
        print("章節：")
        for c in ch[:40]:
            print(f"  [{hms(c.get('start_time', 0))}] {c.get('title')}")
    desc = (info.get("description") or "").strip()
    if desc:
        print("說明（前 600 字）：" + desc[:600].replace("\n", " ⏎ "))
    print(f"快取：{cache_dir(a.src)}")
    return 0


def cmd_transcript(a) -> int:
    prefer = [x.strip() for x in a.lang.split(",")] if a.lang else list(CFG["preferLangs"])
    asr_lang = a.asr_lang
    if a.live:
        a.src = str(capture_live(a.src, a.live))
    p, tag, lang = get_transcript(a.src, prefer, a.asr, a.model, asr_lang, lang_explicit=bool(a.lang))
    lines = p.read_text(encoding="utf-8").splitlines()
    kind = {"youtube_manual": "YouTube 手動字幕", "youtube_auto": "YouTube 自動字幕（機器產生，可能有錯）", "subs_manual": "站方字幕",
            "subs_auto": "站方自動字幕（機器產生，可能有錯）"}.get(tag, f"本機語音辨識 {tag}（機器產生，專有名詞可能錯）")
    print(f"來源：{kind}；語言：{lang}；共 {len(lines)} 行；檔案：{p}")
    base = canonical(a.src) if youtube_id(a.src) else None
    if a.grep:
        pat = re.compile(a.grep, re.I)
        n = 0
        for ln in lines:
            if pat.search(ln):
                n += 1
                t = re.match(r"\[(\d+:\d+(?::\d+)?)\]", ln)
                link = f"  {base}&t={int(parse_time(t.group(1)))}s" if base and t else ""
                print(ln + link)
        print(f"命中 {n} 行")
        return 0
    if a.start or a.end:
        s0, e0 = parse_time(a.start) if a.start else 0, parse_time(a.end) if a.end else float("inf")
        for ln in lines:
            t = re.match(r"\[(\d+:\d+(?::\d+)?)\]", ln)
            if t and s0 <= parse_time(t.group(1)) <= e0:
                print(ln)
        return 0
    show = lines if a.full else lines[:CFG["previewLines"]]
    print("\n".join(show))
    if not a.full and len(lines) > len(show):
        print(f"…（還有 {len(lines) - len(show)} 行；用 --full 全印、--grep 關鍵字、--start/--end 取區段，或直接 Read 檔案）")
    return 0


def cmd_frames(a) -> int:
    src = str(capture_live(a.src, a.live)) if a.live else a.src
    if a.at:
        times = sorted({parse_time(x.strip()) for x in a.at.split(",") if x.strip()})
        frames, pairs = frames_at(src, times)
        print(f"指定時間點截圖 {len(pairs)} 張 → {frames}（用 Read 看圖）")
        for n, t in pairs:
            print(f"  {n}\t[{hms(t)}]")
        return 0
    frames, pairs = extract_frames(src, a.mode, a.interval, a.max)
    print(f"截圖 {len(pairs)} 張 → {frames}（index.txt 有每張時間點；用 Read 看圖）")
    for n, t in pairs:
        print(f"  {n}\t[{hms(t)}]")
    return 0


def cmd_stats(a) -> int:
    vid = youtube_id(a.src)
    if not vid:
        die("stats 只支援 YouTube 網址")
    res = yt_api("videos", {"part": "snippet,statistics,contentDetails", "id": vid})
    items = res.get("items") or []
    if not items:
        die("查無此影片", 3)
    it = items[0]
    s, st, cd = it["snippet"], it.get("statistics", {}), it.get("contentDetails", {})
    print("來源：YouTube Data API videos.list（官方數據，1 配額單位）")
    print(f"標題：{s['title']}\n頻道：{s['channelTitle']}（{s['channelId']}）\n發布：{s['publishedAt']}\n長度：{iso_duration(cd.get('duration'))}")
    print(f"觀看：{st.get('viewCount', '?')}；按讚：{st.get('likeCount', '隱藏')}；留言：{st.get('commentCount', '關閉或隱藏')}")
    if s.get("tags"):
        print("標籤：" + ", ".join(s["tags"][:20]))
    print(f"網址：https://www.youtube.com/watch?v={vid}")
    return 0


def cmd_comments(a) -> int:
    vid = youtube_id(a.src)
    if not vid:
        die("comments 只支援 YouTube 網址")
    res = yt_api("commentThreads", {"part": "snippet", "videoId": vid, "maxResults": min(a.n, 100), "order": a.order, "textFormat": "plainText"})
    print(f"來源：YouTube Data API commentThreads.list（{a.order}；1 配額單位）；留言是網友說法，不是事實")
    for it in res.get("items") or []:
        c = it["snippet"]["topLevelComment"]["snippet"]
        txt = c["textDisplay"].replace("\n", " ")
        print(f"- {c['authorDisplayName']}（👍{c.get('likeCount', 0)}，{c['publishedAt'][:10]}）：{txt[:400]}")
    return 0


def cmd_ask(a) -> int:
    clip = tuple(a.clip) if a.clip else None
    src = str(capture_live(a.src, a.live)) if a.live else a.src
    try:
        ans = gemini_ask(src, a.question, a.model, clip)
    except GeminiError as e:
        die(str(e), 3)
    print(f"〔以下是 Gemini（{a.model}）看影片後的回答，不是 Claude 親眼所見；關鍵事實請對回逐字稿或截圖〕")
    print(ans)
    return 0


def _dir_age_days(d: Path, now: float) -> float:
    return (now - max((p.stat().st_mtime for p in d.rglob("*") if p.is_file()), default=d.stat().st_mtime)) / 86400


def clean_cache(media_days: float | None, all_days: float | None, force_all: bool = False, media_only: bool = False) -> tuple[int, int]:
    """刪快取：影音檔（video.*／audio*）超過 media_days 沒用就刪；整個資料夾超過 all_days 沒用就刪。回 (資料夾數, 位元組)。"""
    root = cache_root()
    now = time.time()
    freed, n = 0, 0
    for d in root.iterdir():
        if not d.is_dir():
            continue
        age = _dir_age_days(d, now)
        if not media_only and (force_all or (all_days is not None and age > all_days)):
            freed += sum(p.stat().st_size for p in d.rglob("*") if p.is_file())
            shutil.rmtree(d, ignore_errors=True)
            n += 1
            continue
        if media_days is not None and (force_all or age > media_days):
            media = list(d.glob("video.*")) + list(d.glob("audio*")) + list(d.glob("live_*.mp4"))
            if media:
                freed += sum(p.stat().st_size for p in media)
                for p in media:
                    p.unlink(missing_ok=True)
                n += 1
    return n, freed


def auto_clean() -> None:
    """每次執行時順手清：超過 autoCleanMediaDays 沒用的影音檔、超過 autoCleanAllDays 沒用的整個資料夾（逐字稿很小，留久一點）。"""
    try:
        n, freed = clean_cache(CFG.get("autoCleanMediaDays"), CFG.get("autoCleanAllDays"))
        if freed > 50e6:
            warn(f"自動清理舊快取 {n} 個資料夾，釋放 {freed / 1e6:.0f} MB")
    except Exception:  # noqa: BLE001
        pass


def cmd_download(a) -> int:
    """使用者明說要「下載／存檔」時才用：最高畫質影像＋最佳音訊合併 mp4，存到 --out（預設 download_dir()）。分析用途不走這裡（走快取）。"""
    yt_dlp = need_ytdlp()
    out_dir = download_dir(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    h = f"[height<={a.max_height}]" if a.max_height else ""
    fmt = "bestaudio/best" if a.audio_only else f"bestvideo{h}+bestaudio/best{h}/best"
    opts = ydl_opts({"format": fmt, "outtmpl": str(out_dir / "%(title).120B [%(id)s].%(ext)s"), "noprogress": False, "quiet": False,
                     "merge_output_format": None if a.audio_only else "mp4", "windowsfilenames": sys.platform == "win32",
                     "writethumbnail": False, "noplaylist": True})
    if a.audio_only:
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}]
    ff = find_ffmpeg()
    if ff:
        opts["ffmpeg_location"] = str(Path(ff).parent)
    if a.cookies_from_browser:
        if sys.platform == "win32" and a.cookies_from_browser.lower() in ("chrome", "edge", "brave", "chromium", "opera", "vivaldi"):
            warn("Windows 上 Chrome 127+ 系列瀏覽器的 cookie 用程序綁定加密，yt-dlp 解不開（yt-dlp issue #10927、#15401）；通常會失敗，改用 --cookies-from-browser firefox 或用擴充套件匯出 cookies.txt 後 --cookies 檔案")
        opts["cookiesfrombrowser"] = (a.cookies_from_browser,)
    if a.cookies:
        opts["cookiefile"] = str(Path(a.cookies).expanduser())
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(a.src, download=True)
            info = y.sanitize_info(info)
            path = Path(info.get("requested_downloads", [{}])[0].get("filepath") or y.prepare_filename(info))
    except Exception as e:  # noqa: BLE001
        s = str(e)
        if "DRM" in s or "drm" in s:
            die("這個影片有 DRM 保護（串流平台），無法下載。", 3)
        if "login" in s.lower() or "cookies" in s.lower() or "需要登录" in s or "大会员" in s:
            die("這個網站要登入或要瀏覽器 cookie 才給下載／高畫質：用 Firefox 登入過該站後加 `--cookies-from-browser firefox`，或用「Get cookies.txt LOCALLY」類擴充套件在該站匯出 cookies.txt 後加 `--cookies 檔案`（Windows 的 Chrome cookie yt-dlp 解不開）。原文：" + s[:200], 3)
        if "Unable to extract initial state" in s:
            die("這個站的抓取器目前壞了（Bilibili 2026-10-21 起，yt-dlp issue #17879／PR #17898）：先 `python -m pip install -U yt-dlp` 看有沒有修好；沒有就等新版，或用 BV 網址加 cookies 再試。原文：" + s[:150], 3)
        _ydl_error(e)
    size = path.stat().st_size / 1e6 if path.exists() else 0
    res = f"{info.get('width')}x{info.get('height')}" if info.get("height") else (info.get("resolution") or "?")
    print(f"已下載：{path}")
    print(f"來源站：{info.get('extractor')}；標題：{info.get('title')}；畫質：{res}；長度：{hms(info['duration']) if info.get('duration') else '?'}；大小：{size:.0f} MB")
    print("提醒：只供個人使用；再散布或商用須取得著作權人授權。")
    return 0


def cmd_clean(a) -> int:
    n, freed = clean_cache(a.older_than, None if a.media_only else a.older_than, force_all=a.all, media_only=a.media_only)
    print(f"清理 {n} 個快取資料夾，釋放 {freed / 1e6:.0f} MB（{cache_root()}）")
    return 0


def main(argv=None) -> int:
    if sys.platform == "win32":
        for s in (sys.stdout, sys.stderr):
            try:
                s.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass
    ap = argparse.ArgumentParser(prog="video.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("setup", help="檢查依賴與金鑰")
    p.set_defaults(fn=cmd_setup)
    p = sub.add_parser("search", help="找影片")
    p.add_argument("query")
    p.add_argument("-n", type=int, default=5)
    p.add_argument("--date", choices=["hour", "today", "week", "month", "year"], help="只在 --api 生效")
    p.add_argument("--api", action="store_true", help="用 YouTube Data API（需 youtube 金鑰；每天 100 次）")
    p.set_defaults(fn=cmd_search)
    p = sub.add_parser("info", help="影片基本資料與字幕語言")
    p.add_argument("src")
    p.set_defaults(fn=cmd_info)
    p = sub.add_parser("transcript", help="逐字稿（字幕優先，沒有才語音辨識）")
    p.add_argument("src")
    p.add_argument("--lang", help="字幕語言偏好序，逗號分隔（預設 video.json preferLangs）")
    p.add_argument("--asr", action="store_true", help="略過字幕，直接本機語音辨識")
    p.add_argument("--asr-lang", help="語音辨識語言碼（zh、en、ja…；預設自動偵測）")
    p.add_argument("--model", default=CFG["whisperModel"], help="whisper 模型（tiny/base/small/medium/large-v3）")
    p.add_argument("--grep", help="只印符合的行（正規表達式，不分大小寫），附 &t= 連結")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--full", action="store_true", help="全部印出（預設只印前幾行）")
    p.add_argument("--live", type=int, metavar="秒", help="直播：先錄 N 秒（10–900）再轉逐字稿")
    p.set_defaults(fn=cmd_transcript)
    p = sub.add_parser("frames", help="關鍵畫面截圖")
    p.add_argument("src")
    p.add_argument("--mode", choices=["scene", "interval"], default="scene")
    p.add_argument("--interval", type=float, default=10.0)
    p.add_argument("--max", type=int, default=CFG["maxFrames"])
    p.add_argument("--at", help="只截這些時間點，逗號分隔，例如 12:30,14:05（逐字稿說「這個／這裡」時用）")
    p.add_argument("--live", type=int, metavar="秒", help="直播：先錄 N 秒再截圖")
    p.set_defaults(fn=cmd_frames)
    p = sub.add_parser("stats", help="官方數據（需 youtube 金鑰）")
    p.add_argument("src")
    p.set_defaults(fn=cmd_stats)
    p = sub.add_parser("comments", help="留言（需 youtube 金鑰）")
    p.add_argument("src")
    p.add_argument("-n", type=int, default=20)
    p.add_argument("--order", choices=["relevance", "time"], default="relevance")
    p.set_defaults(fn=cmd_comments)
    p = sub.add_parser("ask", help="Gemini 真的看影片（需 gemini 金鑰）")
    p.add_argument("src")
    p.add_argument("question")
    p.add_argument("--model", default=CFG["geminiModel"])
    p.add_argument("--clip", nargs=2, metavar=("開始", "結束"), help="只看這段，例如 --clip 1:20 3:00")
    p.add_argument("--live", type=int, metavar="秒", help="直播：先錄 N 秒再給 Gemini 看")
    p.set_defaults(fn=cmd_ask)
    p = sub.add_parser("download", help="使用者要存檔時：最高畫質下載到資料夾（預設 local.json video.downloadDir，未設為 ~/Downloads）")
    p.add_argument("src")
    p.add_argument("--out", help="輸出資料夾")
    p.add_argument("--max-height", type=int, help="畫質上限，例如 1080；不給＝最高")
    p.add_argument("--audio-only", action="store_true", help="只要聲音（m4a）")
    p.add_argument("--cookies-from-browser", metavar="firefox", help="需要登入的站（Bilibili 高畫質、抖音等）用你瀏覽器的登入狀態；Windows 的 Chrome 系列解不開，用 firefox")
    p.add_argument("--cookies", metavar="cookies.txt", help="用擴充套件匯出的 Netscape 格式 cookies.txt（任何瀏覽器都可）")
    p.set_defaults(fn=cmd_download)
    p = sub.add_parser("clean", help="清快取（預設只清 30 天沒動的；--media-only 只刪影音檔留逐字稿）")
    p.add_argument("--older-than", type=float, default=30, metavar="天")
    p.add_argument("--all", action="store_true")
    p.add_argument("--media-only", action="store_true")
    p.set_defaults(fn=cmd_clean)
    a = ap.parse_args(argv)
    if a.cmd not in ("clean", "setup"):
        auto_clean()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
