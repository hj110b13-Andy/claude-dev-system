"""selftest（無頭 claude -p 重跑題目、比對工具呼叫）測試：用假 runner 餵 stream-json，不真的跑 claude。"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "installer"))

from cds import selftest as st  # noqa: E402


def stream(*tool_uses, cost=0.42, text="答案"):
    lines = []
    for name, inp in tool_uses:
        lines.append(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}))
    lines.append(json.dumps({"type": "result", "total_cost_usd": cost, "result": text}))
    return "\n".join(lines) + "\n"


class SelfTest(unittest.TestCase):
    def test_cases_file_is_valid(self):
        cfg = st.load_cases()
        self.assertEqual(len(cfg["cases"]), 9)
        ids = [c["id"] for c in cfg["cases"]]
        self.assertEqual(len(ids), len(set(ids)))
        for c in cfg["cases"]:
            self.assertTrue(c["prompt"] and c["expect"], c["id"])
            for pat in c["expect"] + c.get("forbid", []):
                __import__("re").compile(pat)
        self.assertIn("mcp__parallel__web_search", cfg["allowed"])
        for k in ("parallel-key", "exa-key", "context7-key", "firecrawl-key", "tavily-key"):
            self.assertIn(f"mcp__{k}__", cfg["allowed"], "免費優先的 -key 版也要在無頭權限清單")
        ok, notes = st.judge({"expect": []}, ["Bash :: x"])
        self.assertFalse(ok)

    def test_parse_and_judge(self):
        raw = stream(("Bash", {"command": "py -3 C:/Users/x/.claude/claude-dev-system/tools/video.py transcript https://youtu.be/a"}),
                     ("mcp__parallel__web_search", {"objective": "o", "search_queries": ["q1", "q2"]}))
        calls, res = st.parse_stream(raw)
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0].startswith("Bash :: py -3"))
        self.assertIn("q1 q2", calls[1])
        self.assertEqual(res["total_cost_usd"], 0.42)
        ok, notes = st.judge({"expect": [r"(?i)^(Bash|PowerShell) ::.*video\.py.*transcript", "^mcp__parallel__"], "forbid": ["^mcp__firecrawl__"]}, calls)
        self.assertTrue(ok, notes)
        ok, notes = st.judge({"expect": ["^mcp__mslearn__"], "forbid": ["^mcp__parallel__"]}, calls)
        self.assertFalse(ok)
        self.assertEqual(sum(n.startswith("❌") for n in notes), 2)

    def test_warn_and_write_content_and_mask(self):
        calls = ["Write :: C:/tmp/q.py import requests; requests.get('https://data.moenv.gov.tw/api?api_key=SECRET-KEY-1')",
                 "mcp__firecrawl__firecrawl_scrape :: https://rate.bot.com.tw"]
        ok, notes = st.judge({"expect": [r"(?i)^(Bash|PowerShell|WebFetch|Write) ::.*moenv"], "warn": ["^mcp__firecrawl__firecrawl_scrape"]}, calls)
        self.assertTrue(ok, "warn 命中不算失敗")
        self.assertTrue(any(n.startswith("⚠️") for n in notes))
        raw = stream(("Write", {"file_path": "q.py", "content": "key=SECRET-KEY-1"}))
        c, _ = st.parse_stream(raw)
        self.assertIn("SECRET-KEY-1", c[0], "Write 的 content 要進摘要才比對得到")
        import tempfile
        from cds import web
        from cds.paths import Layout
        with tempfile.TemporaryDirectory() as td:
            lay = Layout(Path(td))
            web.save_local(lay, {"keys": {"moenv": "SECRET-KEY-1"}, "enable": [], "disable": [], "env": {}})
            old_env = os.environ.get("CLAUDE_CONFIG_DIR")
            os.environ["CLAUDE_CONFIG_DIR"] = td
            try:
                logs = []
                code = st.run(only=["live-data"], runner=lambda cmd, cwd, t: (0, raw, ""), which=lambda n: "claude", log=logs.append, report_dir=Path(td) / "rep")
            finally:
                if old_env is None:
                    os.environ.pop("CLAUDE_CONFIG_DIR", None)
                else:
                    os.environ["CLAUDE_CONFIG_DIR"] = old_env
            rep = next((Path(td) / "rep").glob("*.json")).read_text(encoding="utf-8")
            self.assertNotIn("SECRET-KEY-1", rep, "報告不可含金鑰")
            self.assertNotIn("SECRET-KEY-1", chr(10).join(logs), "紀錄不可含金鑰")
            self.assertIn("***", rep)

    def test_long_write_content_is_matched(self):
        raw = stream(("Write", {"file_path": "q.py", "content": ("x = 1" + chr(10)) * 200 + "u = 'https://opendata.cwa.gov.tw/api'"}))
        calls, _ = st.parse_stream(raw)
        ok, notes = st.judge({"expect": [r"(?i)^Write ::.*cwa\.gov\.tw"]}, calls)
        self.assertTrue(ok, "第 300 字之後的內容也要比對得到（2026-11-01 實跑誤判 ❌ 的原因）")

    def test_run_with_fake_runner_and_report(self):
        import tempfile
        seen = []

        def runner(cmd, cwd, timeout):
            seen.append(cmd)
            prompt = cmd[cmd.index("-p") + 1]
            if "PowerShell 7" in prompt:
                return 0, stream(("mcp__mslearn__microsoft_docs_search", {"query": "Get-Content encoding"})), ""
            return 0, stream(("WebSearch", {"query": "x"})), ""
        logs = []
        with tempfile.TemporaryDirectory() as td:
            code = st.run(only=["pwsh", "openaq"], runner=runner, which=lambda n: "claude", log=logs.append, report_dir=Path(td))
            reports = list(Path(td).glob("selftest-*.json"))
            self.assertEqual(len(reports), 1)
            data = json.loads(reports[0].read_text(encoding="utf-8"))
        self.assertEqual(code, 1, "openaq 題應 ❌")
        self.assertEqual([r["ok"] for r in data], [True, False])
        self.assertEqual(len(seen), 2)
        self.assertIn("--no-chrome", seen[0])
        self.assertIn("--allowedTools", seen[0])
        self.assertTrue(any("1/2 題通過" in x for x in logs))
        self.assertEqual(st.run(only=["nope"], which=lambda n: "claude", log=logs.append), 2)
        logs.clear()
        self.assertEqual(st.run(only=["chrome"], which=lambda n: "claude", log=logs.append, dry_run=True, runner=lambda *a: self.fail("dry-run 不可執行")), 0)
        self.assertTrue(any("--chrome" in x and "example.com" in x for x in logs), logs)
        self.assertEqual(st.run(list_only=True, log=logs.append), 0)
        self.assertEqual(st.run(which=lambda n: None, log=logs.append), 2)


if __name__ == "__main__":
    unittest.main()
