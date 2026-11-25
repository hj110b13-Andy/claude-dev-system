"""tools/websearch.py（0.29.0）：回應解析、限流判斷與換家順序、大結果存檔、安裝器寫的伺服器清單。不連網。"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "installer"))
spec = importlib.util.spec_from_file_location("websearch", REPO / "tools" / "websearch.py")
ws = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ws)  # type: ignore[union-attr]

from cds import web  # noqa: E402
from cds.paths import Layout  # noqa: E402


def ok_text(text, is_error=False):
    return {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": text}], "isError": is_error}}


class FakeServers:
    """依網址決定每個伺服器的行為：'ok:文字'、'limit'（HTTP 429）、'cap'（200 但內容是額度用完）、'down'（連不上）。"""

    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = []

    def __call__(self, url, body, headers, sid=None, timeout=60):
        if body.get("method") == "initialize":
            return {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": url}}}, "sid"
        if body.get("method", "").startswith("notifications/"):
            return None, sid
        self.calls.append((url, body["params"].get("name")))
        b = self.behaviour[url]
        if b == "limit":
            raise ws.LimitError("HTTP 429")
        if b == "down":
            raise ws.CallError("連線失敗")
        if b == "cap":
            return ok_text('{"code":"daily_cap_reached","message":"You reached the daily keyless Tavily limit."}'), sid
        return ok_text(b[3:]), sid


REG = {n: {"url": n, "headers": {}} for n in ("parallel", "parallel-key", "exa", "exa-key", "tavily", "firecrawl")}


class Chain(unittest.TestCase):
    def run_with(self, behaviour, order=None, kind="search"):
        fake = FakeServers(behaviour)
        saved = ws._post
        ws._post = fake
        self.addCleanup(setattr, ws, "_post", saved)
        logs = []
        build = (lambda s: ws.search_args(s, "q", 3)) if kind == "search" else (lambda s: ws.fetch_args(s, "https://x", None))
        return ws.run_chain(REG, order or ws.SEARCH_ORDER, build, log=logs.append), fake, logs

    def test_free_version_first(self):
        (name, text), fake, _ = self.run_with({"parallel": "ok:A"})
        self.assertEqual((name, text), ("parallel", "A"))
        self.assertEqual(fake.calls, [("parallel", "web_search")])

    def test_limit_switches_to_key_version_same_service(self):
        (name, text), fake, logs = self.run_with({"parallel": "limit", "parallel-key": "ok:K"})
        self.assertEqual(name, "parallel-key")
        self.assertIn("限流", logs[0])

    def test_cap_text_counts_as_limit(self):
        (name, _), fake, _ = self.run_with({"tavily": "cap", "firecrawl": "ok:F"}, order=["tavily", "firecrawl"])
        self.assertEqual(name, "firecrawl")  # tavily 沒有 -key 版就換下一家

    def test_other_error_skips_to_next_service_not_key(self):
        (name, _), fake, _ = self.run_with({"parallel": "down", "parallel-key": "ok:K", "exa": "ok:E"})
        self.assertEqual(name, "exa")
        self.assertNotIn(("parallel-key", "web_search"), fake.calls)

    def test_all_fail_raises(self):
        with self.assertRaises(ws.CallError):
            self.run_with({"parallel": "limit", "parallel-key": "limit", "exa": "down", "tavily": "cap", "firecrawl": "down"})

    def test_fetch_tool_names(self):
        (_, _), fake, _ = self.run_with({"parallel": "ok:P"}, order=ws.FETCH_ORDER, kind="fetch")
        self.assertEqual(fake.calls, [("parallel", "web_fetch")])
        self.assertEqual(ws.fetch_args("firecrawl", "u", None)[0], "firecrawl_scrape")


class Parsing(unittest.TestCase):
    def test_sse_picks_matching_id(self):
        raw = 'event: message\ndata: {"jsonrpc":"2.0","method":"notify"}\n\nevent: message\ndata: {"jsonrpc":"2.0","id":2,"result":{"x":1}}\n\n'
        self.assertEqual(ws.parse_response(raw, "text/event-stream", 2)["result"], {"x": 1})

    def test_json_and_empty(self):
        self.assertEqual(ws.parse_response('{"id":2,"result":{}}', "application/json", 2)["id"], 2)
        self.assertIsNone(ws.parse_response("", "application/json", 2))

    def test_is_error_raises_call_error(self):
        saved = ws._post
        ws._post = lambda url, body, h, sid=None, timeout=60: (
            ({"id": 1, "result": {}}, "s") if body.get("method") == "initialize" else (ok_text("bad args", True), "s"))
        self.addCleanup(setattr, ws, "_post", saved)
        with self.assertRaises(ws.CallError):
            ws.call_tool({"url": "u", "headers": {}}, "t", {})


class SaveAndRegistry(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cds-ws-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_long_result_saved_and_truncated(self):
        out = []
        p = ws.save_and_print("search", "exa", "字" * 100, 10, home=self.tmp, emit=out.append)
        self.assertEqual(p.read_text(encoding="utf-8"), "字" * 100)
        self.assertIn("只印前 10 字", out[1])
        self.assertTrue(str(p).startswith(str(self.tmp / "state" / "websearch")))

    def test_installer_registry_roundtrip_and_removal(self):
        lay = Layout(self.tmp)
        want = {"exa": {"url": "https://mcp.exa.ai/mcp", "headers": {}},
                "exa-key": {"url": "https://mcp.exa.ai/mcp", "headers": {"x-api-key": "SECRET"}}}
        web.write_registry(lay, want)
        self.assertEqual(ws.load_registry(self.tmp), want)
        self.assertEqual(ws.registry_path(self.tmp), web.registry_path(lay))  # 兩邊路徑同一個
        web.write_registry(lay, {})
        self.assertEqual(ws.load_registry(self.tmp), {})

    def test_main_without_registry_exits_2(self):
        import os
        saved = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.tmp)
        self.addCleanup(lambda: os.environ.__setitem__("CLAUDE_CONFIG_DIR", saved) if saved else os.environ.pop("CLAUDE_CONFIG_DIR", None))
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            self.assertEqual(ws.main(["search", "x"]), 2)
        self.assertIn("install.py web", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
