"""selftest（無頭 claude -p 重跑題目、比對工具呼叫）測試：用假 runner 餵 stream-json，不真的跑 claude。"""
from __future__ import annotations

import json
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
        self.assertEqual(st.run(list_only=True, log=logs.append), 0)
        self.assertEqual(st.run(which=lambda n: None, log=logs.append), 2)


if __name__ == "__main__":
    unittest.main()
