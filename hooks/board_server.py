"""任務看板網頁伺服器（給 Tailscale Funnel 對外，手機／平板／其他電腦用瀏覽器看）。
- 讀 ~/.claude/state/task-board.md（任務看板 mod 每 15 秒寫的 HTML），包成完整網頁，瀏覽器每 15 秒自動刷新（2026-10-13 使用者改 15 秒）。
- 密碼保護：密碼放 ~/.claude/state/board-server.json（本機檔、不進 git），登入後發 HttpOnly cookie。
- 只聽 127.0.0.1，對外由 `tailscale funnel` 轉發；不呼叫任何 AI、不耗額度。
用法：pythonw board_server.py（開機自動啟動見 docs/SETUP-NEW-DEVICE.md）
"""
import hashlib
import hmac
import html
import json
import os
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOME = os.path.expanduser("~")
CFG = json.load(open(os.path.join(HOME, ".claude", "state", "board-server.json"), encoding="utf-8"))
BOARD = os.path.join(HOME, ".claude", "state", "task-board.md")
PW = str(CFG["password"])
PORT = int(CFG.get("port", 8765))
TOKEN = hmac.new(PW.encode(), b"task-board-cookie-v1", hashlib.sha256).hexdigest()
fails = {}

BASE_CSS = "body{background:#111316;color:#e6e6e6;font-family:-apple-system,'Segoe UI','Microsoft JhengHei',sans-serif;margin:0;padding:8px}a{color:#4c9ffe}"
LOGIN = """<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>任務看板登入</title><style>{css}form{{max-width:280px;margin:20vh auto;display:flex;flex-direction:column;gap:10px}}
input,button{{font-size:16px;padding:10px;border-radius:6px;border:1px solid #444;background:#1c1f24;color:#eee}}button{{background:#4c9ffe;border:0;color:#fff}}</style></head>
<body><form method="post" action="/login"><b>📋 任務看板</b><input type="password" name="p" placeholder="密碼" autofocus>{err}<button>進入</button></form></body></html>"""
PAGE = """<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="15"><title>任務看板</title><style>{css}</style></head><body>{body}<style>{web}</style></body></html>"""
# 網頁版專用（2026-10-12 使用者：字再大、留白多一點）：放在看板內容之後，蓋過 md 檔內給 VSCode 預覽的較小字級；VSCode 預覽不受影響。
WEB_CSS = "body,body.scrollBeyondLastLine{padding:16px!important;zoom:1.25;max-width:900px!important;margin:0 auto!important}.card{padding:8px 12px!important;margin:10px 0!important}.sec{margin:20px 0 8px!important}.r{margin:6px 0!important}"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def authed(self):
        c = self.headers.get("Cookie", "")
        return any(part.strip() == f"tb={TOKEN}" for part in c.split(";"))

    def send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Robots-Tag", "noindex")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self.authed():
            return self.send(200, LOGIN.format(css=BASE_CSS, err=""))
        try:
            body = open(BOARD, encoding="utf-8").read()
        except Exception:
            body = "<p>看板檔還沒產生（Claude Code 的任務看板 mod 沒有在執行）。</p>"
        self.send(200, PAGE.format(css=BASE_CSS, body=body, web=WEB_CSS))

    def do_POST(self):
        ip = self.headers.get("X-Forwarded-For", self.client_address[0]).split(",")[0].strip()
        n, t = fails.get(ip, (0, 0.0))
        if n >= 5 and time.time() - t < 600:
            return self.send(429, LOGIN.format(css=BASE_CSS, err="<span>嘗試太多次，10 分鐘後再試</span>"))
        length = int(self.headers.get("Content-Length", "0") or 0)
        form = urllib.parse.parse_qs(self.rfile.read(min(length, 4096)).decode("utf-8", "replace"))
        if hmac.compare_digest(form.get("p", [""])[0], PW):
            fails.pop(ip, None)
            return self.send(303, "", extra={"Location": "/", "Set-Cookie": f"tb={TOKEN}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=2592000"})
        fails[ip] = (n + 1, time.time())
        self.send(401, LOGIN.format(css=BASE_CSS, err="<span>密碼錯誤</span>"))


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
