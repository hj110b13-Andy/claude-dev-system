#!/usr/bin/env python3
"""用到才呼叫的搜尋／抓頁工具（0.29.0）：直接當 MCP 客戶端呼叫本系統註冊的 HTTP MCP 伺服器，不靠 Claude Code 常駐載入。只用標準庫。

起因（使用者 2026-11-25）：「擋掉搜尋類 MCP這部分，有辦法不要看專案擋掉，而是要用到搜尋類時再呼叫嗎?」。實測 /context：
搜尋類 MCP 的伺服器說明每個請求都送（約 4.5k token），擋掉 8 個伺服器每請求省 7,760。改成這支腳本＋skill `cds-websearch`，
說明只在用到時才載入。第一階段與現有 MCP 並存，比較過品質再決定是否拿掉 MCP。

伺服器清單（唯一來源）：安裝器 `installer/cds/web.py` 的 desired_servers() 在同步 MCP 時寫出
`<CLAUDE_HOME>/claude-dev-system/config/websearch-servers.json`（{名稱: {url, headers}}，含金鑰，不進 repo、不印出）。

協定：MCP Streamable HTTP（initialize → notifications/initialized → tools/list／tools/call；回應可能是 JSON 或 SSE）。
2026-11-25 實測 12 個伺服器全部可用（tavily 免金鑰要 header X-Tavily-Access-Mode: keyless，registry 已含）。

用法：
  python websearch.py servers                         # 列出可用的伺服器
  python websearch.py tools exa                       # 列某個伺服器的工具與參數（用到才查）
  python websearch.py search "查詢字" [--via exa] [--n 5]
  python websearch.py fetch https://… [--via firecrawl] [--objective "要找什麼"]
  python websearch.py call context7 resolve-library-id '{"libraryName":"requests","query":"timeout"}'
  共用：--max 6000（印出的最多字數；完整結果一律存檔並印路徑）
免費優先：search／fetch 依 SEARCH_ORDER／FETCH_ORDER，每家先用免金鑰版，回限流／額度用完（HTTP 429／402／5xx，或內容含
daily_cap_reached、rate limit 等）就改用同一家的 `-key` 版，再不行換下一家。結束碼：0 成功、2 用法錯誤、3 全部失敗。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROTO = "2025-06-18"
UA = "cds-websearch/0.29"
TIMEOUT = 60
SEARCH_ORDER = ["parallel", "exa", "tavily", "firecrawl"]
FETCH_ORDER = ["parallel", "exa", "tavily", "firecrawl"]
LIMIT_HTTP = {402, 429, 500, 502, 503, 504}
# 伺服器回 200 但內容是「額度用完／限流」的說法（tavily keyless 2026-11-25 實測回 daily_cap_reached，isError 沒設）
LIMIT_TEXT = re.compile(r"daily_cap_reached|rate.?limit|too many requests|quota (?:exceeded|reached)|credits? (?:exhausted|insufficient)"
                        r"|insufficient credits|payment required|upgrade your plan", re.I)
KEEP_DAYS = 7  # 自己定的：存檔結果保留 7 天


def claude_home() -> Path:
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env) if env else Path.home() / ".claude"


def registry_path(home: Path | None = None) -> Path:
    return (home or claude_home()) / "claude-dev-system" / "config" / "websearch-servers.json"


def load_registry(home: Path | None = None) -> dict:
    p = registry_path(home)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in (d.get("servers") or {}).items() if isinstance(v, dict) and v.get("url")}


class LimitError(Exception):
    """限流或額度用完：可以換金鑰版或下一家。"""


class CallError(Exception):
    """其他錯誤（連不上、參數錯）。"""


def _post(url: str, body: dict, headers: dict, sid: str | None = None, timeout: int = TIMEOUT):
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
         "MCP-Protocol-Version": PROTO, "User-Agent": UA, **headers}
    if sid:
        h["Mcp-Session-Id"] = sid
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ctype = r.headers.get("Content-Type", "")
            new_sid = r.headers.get("Mcp-Session-Id") or sid
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in LIMIT_HTTP:
            raise LimitError(f"HTTP {e.code}") from None
        raise CallError(f"HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise CallError(f"連線失敗：{type(e).__name__}") from None
    return parse_response(raw, ctype, body.get("id")), new_sid


def parse_response(raw: str, ctype: str, want_id=None):
    """JSON 或 SSE（data: 行）都解；SSE 取 id 相符的那則，沒有就取最後一則。"""
    if "event-stream" in ctype:
        msgs = []
        for block in raw.replace("\r\n", "\n").split("\n\n"):
            data = "\n".join(ln[5:].lstrip() for ln in block.splitlines() if ln.startswith("data:"))
            if data:
                try:
                    msgs.append(json.loads(data))
                except ValueError:
                    pass
        return next((m for m in msgs if m.get("id") == want_id), msgs[-1] if msgs else None)
    return json.loads(raw) if raw.strip() else None


def _session(spec: dict):
    headers = dict(spec.get("headers") or {})
    res, sid = _post(spec["url"], {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                   "params": {"protocolVersion": PROTO, "capabilities": {},
                                              "clientInfo": {"name": "cds-websearch", "version": "0.29"}}}, headers)
    if not res or "error" in res:
        raise CallError(f"initialize 失敗：{(res or {}).get('error')}")
    try:
        _post(spec["url"], {"jsonrpc": "2.0", "method": "notifications/initialized"}, headers, sid)
    except (CallError, LimitError):
        pass  # 有些伺服器對通知回 202 空內容或非 200
    return headers, sid


def rpc(spec: dict, method: str, params: dict):
    """開一個 session 打一次 method；回 result dict。"""
    headers, sid = _session(spec)
    res, _ = _post(spec["url"], {"jsonrpc": "2.0", "id": 2, "method": method, "params": params}, headers, sid)
    if not res:
        raise CallError("沒有回應")
    if "error" in res:
        msg = json.dumps(res["error"], ensure_ascii=False)
        if LIMIT_TEXT.search(msg):
            raise LimitError(msg[:200])
        raise CallError(msg[:300])
    return res.get("result") or {}


def result_text(result: dict) -> str:
    parts = []
    for c in result.get("content") or []:
        if isinstance(c, dict):
            if c.get("type") == "text":
                parts.append(c.get("text", ""))
            elif c.get("type") == "resource":
                parts.append(str((c.get("resource") or {}).get("text", "")))
    if not parts and result.get("structuredContent") is not None:
        parts.append(json.dumps(result["structuredContent"], ensure_ascii=False, indent=1))
    return "\n".join(parts)


def call_tool(spec: dict, tool: str, args: dict) -> str:
    r = rpc(spec, "tools/call", {"name": tool, "arguments": args})
    text = result_text(r)
    if LIMIT_TEXT.search(text[:2000]):
        raise LimitError(text[:200].replace("\n", " "))
    if r.get("isError"):
        raise CallError(text[:300].replace("\n", " "))
    return text


# 各家搜尋／抓頁工具與參數（2026-11-25 用 tools/list 對過名稱；參數只放必要的，細節用 `tools <伺服器>` 查）
def search_args(svc: str, query: str, n: int):
    return {
        "parallel": ("web_search", {"objective": query, "search_queries": [query]}),
        "exa": ("web_search_exa", {"query": query, "numResults": n}),
        "tavily": ("tavily_search", {"query": query, "max_results": n}),
        "firecrawl": ("firecrawl_search", {"query": query, "limit": n}),
    }[svc]


def fetch_args(svc: str, url: str, objective: str | None):
    return {
        "parallel": ("web_fetch", {"urls": [url], **({"objective": objective} if objective else {})}),
        "exa": ("web_fetch_exa", {"urls": [url]}),
        "tavily": ("tavily_extract", {"urls": [url]}),
        "firecrawl": ("firecrawl_scrape", {"url": url, "formats": ["markdown"]}),
    }[svc]


def run_chain(reg: dict, order: list, build, log=print):
    """依序試每家：免金鑰版 → 同家 -key 版（限流時）→ 下一家。回 (伺服器名稱, 文字)；全部失敗丟 CallError。"""
    tried = []
    for svc in order:
        for name in (svc, svc + "-key"):
            spec = reg.get(name)
            if not spec:
                continue
            tool, args = build(svc)
            try:
                return name, call_tool(spec, tool, args)
            except LimitError as e:
                tried.append(f"{name}：限流／額度用完（{e}）")
                log(f"〔{name} 限流或額度用完，改用下一個〕")
                continue
            except CallError as e:
                tried.append(f"{name}：{e}")
                log(f"〔{name} 失敗：{e}，改用下一家〕")
                break  # 非限流錯誤：同家金鑰版大概也一樣，直接換下一家
    raise CallError("全部失敗：" + "；".join(tried) if tried else "沒有可用的伺服器（先跑 install.py web 啟用聯網來源）")


def out_dir(home: Path | None = None) -> Path:
    d = (home or claude_home()) / "state" / "websearch"
    d.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - KEEP_DAYS * 86400
    for p in d.glob("*.md"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass
    return d


def save_and_print(kind: str, name: str, text: str, max_chars: int, home: Path | None = None, emit=print) -> Path:
    path = out_dir(home) / f"{time.strftime('%Y%m%d-%H%M%S')}-{kind}-{name}.md"
    path.write_text(text, encoding="utf-8")
    emit(f"〔來源伺服器：{name}｜全文 {len(text):,} 字已存：{path}〕")
    emit(text if len(text) <= max_chars else text[:max_chars] + f"\n…〔只印前 {max_chars:,} 字；其餘用 Read 讀上面的檔案（可帶 offset）〕")
    return path


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="用到才呼叫的搜尋／抓頁（MCP over HTTP）")
    ap.add_argument("cmd", choices=["servers", "tools", "search", "fetch", "call"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--via", help="只用這一家（例如 exa、exa-key）")
    ap.add_argument("--n", type=int, default=5, help="search：結果數")
    ap.add_argument("--objective", help="fetch：要在頁面裡找什麼（parallel 會依此摘錄）")
    ap.add_argument("--max", type=int, default=6000, help="最多印出幾個字（完整結果一律存檔）")
    a = ap.parse_args(argv)
    reg = load_registry()
    if not reg:
        print(f"找不到伺服器清單 {registry_path()}：先跑 `install.py web`（或 update）啟用聯網來源")
        return 2
    if a.cmd == "servers":
        for n, s in sorted(reg.items()):
            print(f"{n}{'（金鑰版）' if n.endswith('-key') else ''}")
        return 0
    try:
        if a.cmd == "tools":
            if not a.args or a.args[0] not in reg:
                print("用法：tools <伺服器>；可用：" + "、".join(sorted(reg)))
                return 2
            r = rpc(reg[a.args[0]], "tools/list", {})
            for t in r.get("tools") or []:
                props = ((t.get("inputSchema") or {}).get("properties") or {})
                req = set((t.get("inputSchema") or {}).get("required") or [])
                ps = ", ".join(f"{k}{'*' if k in req else ''}:{(v or {}).get('type', '?')}" for k, v in props.items())
                desc = re.sub(r"\s+", " ", t.get("description") or "")[:200]
                print(f"- {t['name']}({ps})\n  {desc}")
            print("（* ＝必填）")
            return 0
        if a.cmd == "call":
            if len(a.args) < 2 or a.args[0] not in reg:
                print("用法：call <伺服器> <工具> '<JSON 參數>'；可用：" + "、".join(sorted(reg)))
                return 2
            args = json.loads(a.args[2]) if len(a.args) > 2 else {}
            text = call_tool(reg[a.args[0]], a.args[1], args)
            save_and_print("call", a.args[0], text, a.max)
            return 0
        if not a.args:
            print(f"用法：{a.cmd} <{'查詢字' if a.cmd == 'search' else '網址'}>")
            return 2
        q = " ".join(a.args)
        order = SEARCH_ORDER if a.cmd == "search" else FETCH_ORDER
        if a.via:  # 指定一家：「exa」＝免金鑰、限流時換 exa-key；「exa-key」＝只用金鑰版
            base = a.via[:-4] if a.via.endswith("-key") else a.via
            if base not in order or a.via not in reg:
                print(f"--via 只能是 {'、'.join(order)}（或加 -key）而且要已啟用；目前可用：{'、'.join(sorted(reg))}")
                return 2
            order = [base]
            reg = {k: v for k, v in reg.items() if k == a.via or (not a.via.endswith("-key") and k == base + "-key")}
        build = (lambda s: search_args(s, q, a.n)) if a.cmd == "search" else (lambda s: fetch_args(s, q, a.objective))
        name, text = run_chain(reg, order, build)
        save_and_print(a.cmd, name, text, a.max)
        return 0
    except (CallError, LimitError) as e:
        print(f"❌ {e}")
        return 3
    except ValueError as e:
        print(f"❌ 參數不是合法 JSON：{e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
