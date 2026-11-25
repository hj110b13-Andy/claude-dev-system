"""coding-eval（裝與不裝本系統的寫程式對照評測）測試：不連網、不呼叫 claude，用假 runner 餵 stream-json。

起因：2026-11-25 使用者問「在寫程式上，有無安裝該專案的優化系統會有甚麼差異?」，repo 沒有任何對照數據；
選了「做小規模版：先寫 5 題，裝與不裝各跑 1 輪，主要量 token 和耗時」。
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "installer"))

from cds import codingeval as ce  # noqa: E402


def stream(*tool_uses, text="完成", usage=None, subtype="success", init=None):
    lines = []
    if init is not None:
        lines.append(json.dumps({"type": "system", "subtype": "init", **init}))
    for name, inp in tool_uses:
        lines.append(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}))
    lines.append(json.dumps({"type": "result", "subtype": subtype, "is_error": subtype != "success", "result": text, "num_turns": 3,
                             "duration_ms": 1000, "total_cost_usd": 0.1,
                             "usage": usage or {"input_tokens": 10, "output_tokens": 20, "cache_creation_input_tokens": 300, "cache_read_input_tokens": 4000}}))
    return "\n".join(lines) + "\n"


class Config(unittest.TestCase):
    def test_five_cases_with_hidden_tests_and_required_kinds(self):
        cfg = ce.load_eval()
        ids = [c["id"] for c in cfg["cases"]]
        self.assertEqual(ids, ["bugfix", "shared-fn", "refactor", "feature", "tiny"])
        self.assertEqual(len(set(ids)), 5)
        for c in cfg["cases"]:
            self.assertTrue(c["prompt"].strip())
            self.assertTrue(c["hidden"], c["id"])
            for name, src in c["hidden"].items():
                self.assertTrue(name.startswith("test_") and name.endswith(".py"))
                compile(src, name, "exec")
        for rel, src in cfg["seed"].items():
            if rel.endswith(".py"):
                compile(src, rel, "exec")
        self.assertIn("shop/pricing.py", cfg["seed"])
        self.assertNotIn("coupon", " ".join(cfg["seed"]), "feature 題的 shop/coupon.py 不能先放在 seed")

    def test_hidden_tests_never_in_seed(self):
        cfg = ce.load_eval()
        for c in cfg["cases"]:
            for name in c["hidden"]:
                self.assertFalse(any(rel.endswith(name) for rel in cfg["seed"]), f"{name} 不可出現在 seed（模型會看到）")

    def test_shared_function_has_at_least_three_caller_modules(self):
        seed = ce.load_eval()["seed"]
        callers = [rel for rel, src in seed.items() if rel.startswith("shop/") and rel != "shop/pricing.py" and "format_price(" in src]
        self.assertGreaterEqual(len(callers), 3, callers)

    def test_seed_is_not_a_project_for_auto_init(self):
        """seed 原始碼 <10 檔、沒有 git：with 條件不會被「專案自動化」拉去跑 cds-project-init，量到的是寫程式本身。"""
        seed = ce.load_eval()["seed"]
        self.assertLess(sum(1 for r in seed if r.endswith(".py")), 10)
        self.assertFalse(any(r.startswith(".git") or r.endswith("CLAUDE.md") for r in seed))


class Selection(unittest.TestCase):
    def test_only_commas_unknown_and_conditions(self):
        cfg = ce.load_eval()
        cases, unknown = ce.select_cases(cfg, ["tiny,bugfix"])
        self.assertEqual([c["id"] for c in cases], ["bugfix", "tiny"])
        self.assertEqual(unknown, [])
        self.assertEqual(ce.select_cases(cfg, ["nope"])[1], ["nope"])
        self.assertEqual(ce.conditions_for("both"), ["with", "without"])
        self.assertEqual(ce.conditions_for("without"), ["without"])
        with self.assertRaises(ValueError):
            ce.conditions_for("maybe")

    def test_cmd_same_model_effort_and_safe_mode_only_without(self):
        cfg = ce.load_eval()
        case = cfg["cases"][0]
        w = ce.build_eval_cmd("claude", case, cfg, "with")
        wo = ce.build_eval_cmd("claude", case, cfg, "without")
        self.assertNotIn("--safe-mode", w)
        self.assertIn("--safe-mode", wo)
        self.assertEqual([x for x in wo if x != "--safe-mode"], w, "兩條件除了 --safe-mode 之外指令要完全一樣")
        for flag in ("--model", "--effort", "--no-session-persistence", "--allowedTools"):
            self.assertIn(flag, w)
        self.assertEqual(w[w.index("-p") + 1], case["prompt"])

    def test_clean_env_drops_outer_session_vars(self):
        env = ce.clean_env({"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "x", "CLAUDE_EFFORT": "high", "CLAUDE_CONFIG_DIR": "d", "PATH": "p"})
        self.assertEqual(env, {"CLAUDE_CONFIG_DIR": "d", "PATH": "p"})


class Judging(unittest.TestCase):
    def test_parse_unittest(self):
        self.assertEqual(ce.parse_unittest("....\nRan 4 tests in 0.1s\n\nOK\n"), {"ran": 4, "failures": 0, "errors": 0})
        self.assertEqual(ce.parse_unittest("Ran 8 tests in 0s\n\nFAILED (failures=5, errors=3)"), {"ran": 8, "failures": 5, "errors": 3})
        self.assertEqual(ce.parse_unittest("Ran 1 test in 0s\n\nFAILED (errors=1)")["errors"], 1)
        self.assertEqual(ce.parse_unittest("garbage")["ran"], 0)

    def test_hidden_test_fails_on_seed_and_passes_after_fix(self):
        cfg = ce.load_eval()
        case = next(c for c in cfg["cases"] if c["id"] == "tiny")
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            ce.write_files(d, cfg["seed"])
            self.assertFalse(ce.judge_hidden(d, case, 60)["ok"])
            p = d / "shop" / "cli.py"
            p.write_text(p.read_text(encoding="utf-8").replace("quantitiy", "quantity"), encoding="utf-8")
            r = ce.judge_hidden(d, case, 60)
            self.assertTrue(r["ok"], r["tail"])
            self.assertEqual(r["ran"], 2)
            self.assertTrue(ce.run_unittest(d, "tests", 60)["ok"], "seed 自己的可見測試要能跑")

    def test_missing_module_counts_as_fail(self):
        cfg = ce.load_eval()
        case = next(c for c in cfg["cases"] if c["id"] == "feature")
        with tempfile.TemporaryDirectory() as t:
            ce.write_files(Path(t), cfg["seed"])
            r = ce.judge_hidden(Path(t), case, 60)
            self.assertFalse(r["ok"])
            self.assertEqual(r["errors"], 1)

    def test_diff_and_ran_tests_and_tool_counts(self):
        self.assertEqual(ce.diff_files({"a": "1", "b": "2"}, {"a": "1", "b": "3", "c": "4"}),
                         {"added": ["c"], "deleted": [], "modified": ["b"]})
        pat = ce.load_eval()["ranTestsPattern"]
        self.assertTrue(ce.ran_tests(["Bash :: python -m unittest discover -s tests"], pat))
        self.assertTrue(ce.ran_tests(["PowerShell :: py -3 -m pytest -q"], pat))
        self.assertFalse(ce.ran_tests(["Read :: tests/test_cart.py", "Bash :: ls"], pat))
        self.assertEqual(ce.tool_counts(["Read :: a", "Edit :: b", "Read :: c"]), {"Read": 2, "Edit": 1})

    def test_stream_info_reads_init_and_hooks(self):
        raw = stream(init={"tools": ["Bash", "Read"], "mcp_servers": [{"name": "exa"}], "skills": ["cds-blast-radius", "other"], "model": "m"})
        raw += json.dumps({"type": "system", "subtype": "hook_response"}) + "\n"
        info = ce.stream_info(raw)
        self.assertEqual((info["tools"], info["mcp_servers"], info["cds_skills"], info["hook_events"]), (2, ["exa"], ["cds-blast-radius"], 1))

    def test_all_models_usage(self):
        res = {"modelUsage": {"a": {"inputTokens": 1, "outputTokens": 2, "cacheReadInputTokens": 3, "cacheCreationInputTokens": 4},
                              "b": {"inputTokens": 10}}}
        u = ce.all_models_usage(res)
        self.assertEqual((u["input_tokens"], u["total"], u["models"]), (11, 20, ["a", "b"]))
        self.assertEqual(ce.all_models_usage({}), {})


def _row(cid, cond, total, secs, calls, ok=True, error=""):
    return {"id": cid, "condition": cond, "hidden_ok": ok, "hidden": {"ran": 2, "failures": 0 if ok else 1, "errors": 0, "exit": 0},
            "visible_ok": True, "ran_tests": cond == "with", "tool_calls": calls, "seconds": secs,
            "usage": {"input_tokens": 1, "output_tokens": 2, "cache_creation_input_tokens": 3, "cache_read_input_tokens": total - 6, "total": total},
            "cost_usd": 0.5, "error": error}


class Summary(unittest.TestCase):
    def test_summary_numbers_and_ratios(self):
        rows = [_row("a", "with", 3000, 60, 10), _row("a", "without", 1000, 30, 4),
                _row("b", "with", 2000, 40, 6, ok=False), _row("b", "without", 2000, 40, 6),
                _row("c", "with", 500, 10, 1), _row("c", "without", 500, 10, 1, error="沒有 result 事件")]
        s = ce.summarize(rows)
        w, wo = s["per_condition"]["with"], s["per_condition"]["without"]
        self.assertEqual((w["runs"], w["hidden_pass"], w["tokens_total"], w["tokens_median"], w["seconds_total"], w["tool_calls_total"]),
                         (3, 2, 5500, 2000, 110, 17))
        self.assertEqual((wo["ran_tests"], wo["errors"]), (0, 1))
        self.assertEqual([x["id"] for x in s["with_vs_without"]], ["a", "b"], "有 error 的題不算倍數")
        self.assertEqual(s["with_vs_without"][0], {"id": "a", "tokens_x": 3.0, "seconds_x": 2.0, "tool_calls_diff": 6})
        table = "\n".join(ce.format_table(rows, s))
        self.assertIn("| a | with | ✅ 2/2 |", table)
        self.assertIn("| b | with | ❌ 1/2 |", table)
        self.assertIn("只當參考", table)
        self.assertIn("| a | 3.0 | 2.0 | +6 |", table)


class EndToEnd(unittest.TestCase):
    def test_run_with_fake_claude(self):
        """假 claude：with 條件修好拼字並跑測試；without 條件什麼都沒改。檢查每場一列、隱藏測試判定、報告 JSON。"""
        seen = []

        def runner(cmd, cwd, timeout, env=None):
            seen.append((cmd, env))
            if cmd[1:] == ["--version"]:
                return 0, "9.9.9 (Claude Code)\n", ""
            if "--safe-mode" not in cmd:
                p = Path(cwd) / "shop" / "cli.py"
                p.write_text(p.read_text(encoding="utf-8").replace("quantitiy", "quantity"), encoding="utf-8")
                return 0, stream(("Edit", {"file_path": "shop/cli.py"}), ("Bash", {"command": "python -m unittest discover -s tests"})), ""
            return 0, stream(("Read", {"file_path": "shop/cli.py"})), ""

        with tempfile.TemporaryDirectory() as t:
            logs = []
            code = ce.run(only=["tiny"], condition="both", runner=runner, which=lambda _: "claude", log=logs.append,
                          report_dir=Path(t) / "rep", work_dir=Path(t) / "work")
            self.assertEqual(code, 0, "\n".join(logs))
            rep = json.loads(next((Path(t) / "rep").glob("coding-eval-*.json")).read_text(encoding="utf-8"))
        rows = {r["condition"]: r for r in rep["rows"]}
        self.assertEqual(set(rows), {"with", "without"})
        self.assertTrue(rows["with"]["hidden_ok"])
        self.assertTrue(rows["with"]["ran_tests"])
        self.assertEqual(rows["with"]["changed"]["modified"], ["shop/cli.py"])
        self.assertFalse(rows["without"]["hidden_ok"])
        self.assertFalse(rows["without"]["ran_tests"])
        self.assertEqual(rows["with"]["usage"]["total"], 4330)
        self.assertEqual(rep["meta"]["claude_version"], "9.9.9 (Claude Code)")
        for cmd, env in seen:
            self.assertFalse(any(k.startswith("CLAUDE") and k != "CLAUDE_CONFIG_DIR" for k in env or {}), "外層 session 變數要拿掉")
        self.assertTrue(any("token 倍數" in x for x in logs))

    def test_error_result_returns_1_and_records_reason(self):
        def runner(cmd, cwd, timeout, env=None):
            if cmd[1:] == ["--version"]:
                return 0, "x", ""
            return 1, "", "boom"

        logs = []
        self.assertEqual(ce.run(only=["tiny"], condition="without", runner=runner, which=lambda _: "claude", log=logs.append), 1)
        self.assertTrue(any("沒有 result 事件" in x and "boom" in x for x in logs), logs)

    def test_list_dry_run_and_usage_errors(self):
        logs = []
        self.assertEqual(ce.run(list_only=True, log=logs.append), 0)
        self.assertEqual(len(logs), 5)
        logs = []
        self.assertEqual(ce.run(dry_run=True, only=["bugfix"], which=lambda _: "claude", log=logs.append), 0)
        text = "\n".join(logs)
        cmd_lines = [x for x in logs if x.startswith("   ")]
        self.assertEqual(len(cmd_lines), 2)
        self.assertEqual(sum(" --safe-mode" in x for x in cmd_lines), 1)
        self.assertIn("2 場", text)
        self.assertEqual(ce.run(only=["nope"], log=lambda _: None), 2)
        self.assertEqual(ce.run(condition="x", log=lambda _: None), 2)
        self.assertEqual(ce.run(which=lambda _: None, log=lambda _: None), 2)

    def test_cli_subcommand(self):
        import install  # noqa: PLC0415
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = install.main(["coding-eval", "--list"])
        self.assertEqual(code, 0)
        self.assertEqual(len(buf.getvalue().strip().splitlines()), 5)


if __name__ == "__main__":
    unittest.main()
