"""hooks/usage_guard.py 的查證守門（Stop）：假逐字稿，不打網路。"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("usage_guard", REPO / "hooks" / "usage_guard.py")
ug = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ug)  # type: ignore[union-attr]


def transcript(path: Path, turns):
    lines = []
    for role, text in turns:
        if role == "user":
            lines.append({"type": "user", "message": {"role": "user", "content": text}})
        elif role == "tool":
            lines.append({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": text}]}})
        else:
            lines.append({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}})
    path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n", encoding="utf-8")


LONG = "AI 會出現幻覺的原因有三層。" * 12


class SourceGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cds-hook-"))
        self.tp = self.tmp / "t.jsonl"
        # 不可寫到使用者真實的 ~/.claude/state（0.11.8～0.11.16 的測試把「AI 幻覺的原因是什麼？」寫進了真實 source-guard.log）
        self._saved = (ug.STATE_DIR, ug.PA_STATE)
        ug.STATE_DIR = str(self.tmp / "state")
        ug.PA_STATE = str(self.tmp / "state" / "project-auto.json")

    def tearDown(self):
        ug.STATE_DIR, ug.PA_STATE = self._saved

    def run_hook(self, active=False):
        return ug.source_guard({"hook_event_name": "Stop", "transcript_path": str(self.tp), "stop_hook_active": active})

    def test_blocks_question_with_numbers_and_no_source(self):
        transcript(self.tp, [("user", "AI 幻覺的原因是什麼？"), ("tool", "x"),
                             ("assistant", LONG + "2024 年 Google AI 摘要建議披薩加膠水，OpenAI 2025 年發表論文。")])
        out = self.run_hook()
        self.assertIsNotNone(out)
        self.assertEqual(out["decision"], "block")
        self.assertIn("來源", out["reason"])
        self.assertIsNone(self.run_hook(active=True), "stop_hook_active 不再擋，避免迴圈")

    def test_passes_with_source_or_marker_or_code_or_statement(self):
        transcript(self.tp, [("user", "AI 幻覺的原因是什麼？"), ("assistant", LONG + "2024 年事件。來源：https://www.bbc.com/x（2026-11-02 查）")])
        self.assertIsNone(self.run_hook(), "有來源段放行")
        transcript(self.tp, [("user", "AI 幻覺的原因是什麼？"), ("assistant", LONG + "例如 2024 年。〔不含待查證事實〕")])
        self.assertIsNone(self.run_hook(), "標記放行")
        transcript(self.tp, [("user", "幫我看這段怎麼改？"), ("assistant", LONG + "改了 2024 年的欄位：```py\nx=1\n```")])
        self.assertIsNone(self.run_hook(), "程式碼區塊不擋")
        transcript(self.tp, [("user", "把報告整理成三段"), ("assistant", LONG + "2024 年營收 120 億元。")])
        self.assertIsNone(self.run_hook(), "不是問句不擋")
        transcript(self.tp, [("user", "幾點開門？"), ("assistant", "早上 9 點，來源見官網")])
        self.assertIsNone(self.run_hook(), "短回覆不擋")
        transcript(self.tp, [("user", "AI 幻覺的原因是什麼？"), ("assistant", LONG + "它只是在接著寫最像的字。")])
        self.assertIsNone(self.run_hook(), "沒有數字不擋")

    def test_last_turn_only_and_disabled(self):
        transcript(self.tp, [("user", "台北 101 幾公尺？"), ("assistant", LONG + "508 公尺。"),
                             ("user", "謝謝，再整理一下重點"), ("assistant", LONG + "重點是 508 公尺。")])
        self.assertIsNone(self.run_hook(), "只看最後一輪，最後一句不是問句")
        old = ug.SG_LOCAL
        ug.SG_LOCAL = str(self.tmp / "local.json")
        (self.tmp / "local.json").write_text(json.dumps({"sourceGuard": False}), encoding="utf-8")
        try:
            transcript(self.tp, [("user", "台北 101 幾公尺？"), ("assistant", LONG + "508 公尺。")])
            self.assertIsNone(self.run_hook(), "local.json sourceGuard=false 關閉")
        finally:
            ug.SG_LOCAL = old
        self.assertEqual(ug.sg_judge(None, None), None)


class Health(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cds-health-"))
        self._saved = (ug.STATE_DIR, ug.PA_STATE, ug.CONFIG)
        ug.STATE_DIR = str(self.tmp / "state")
        ug.PA_STATE = str(self.tmp / "state" / "project-auto.json")
        ug.CONFIG = str(self.tmp / "no-global.json")
        self.proj = self.tmp / "proj"
        (self.proj / ".claude").mkdir(parents=True)
        (self.proj / ".git").mkdir()

    def tearDown(self):
        ug.STATE_DIR, ug.PA_STATE, ug.CONFIG = self._saved

    def test_stale_index_big_docs_and_daily_once(self):
        import os
        import time
        idx = self.proj / ".claude" / "project-scan.json"
        idx.write_text("{}", encoding="utf-8")
        old = time.time() - 3600
        os.utime(idx, (old, old))
        for i in range(25):
            (self.proj / f"m{i}.py").write_text("x=1", encoding="utf-8")
        (self.proj / "CLAUDE.md").write_text("規則" + chr(10) * 200, encoding="utf-8")
        (self.proj / "PROGRESS.md").write_text("x" + chr(10) * 650, encoding="utf-8")
        probs = ug.project_health(str(self.proj))
        self.assertEqual(len(probs), 3, probs)
        self.assertIn("改過 2", probs[0])
        m = ug.health_msg(str(self.proj))
        self.assertIn("專案健康檢查", m)
        self.assertIsNone(ug.health_msg(str(self.proj)), "同一天只提醒一次")
        self.assertIn("專案健康檢查", ug.health_msg(str(self.proj), force=True), "壓縮後每次都看")
        (self.proj / ".claude" / "dispatch-config.json").write_text(json.dumps({"projectAutomation": {"claudeMdMaxLines": 0, "staleFiles": 0, "progressMaxLines": 0}}), encoding="utf-8")
        self.assertEqual(ug.project_health(str(self.proj)), [], "專案可改門檻或設 0 關閉；剩 KB 檢查，200 行 < 20 KB")

    def test_compact_reinjects_and_suggests_new_session(self):
        msgs = [ug.compact_msg(str(self.proj), "sess-1") for _ in range(3)]
        self.assertTrue(all("壓縮後重新開工" in m for m in msgs))
        self.assertNotIn("建議開新對話", msgs[1])
        self.assertIn("已被壓縮 3 次", msgs[2])
        self.assertIn("壓縮後重新開工", ug.compact_msg(None, None), "沒有 cwd 也給開工清單")


if __name__ == "__main__":
    unittest.main()
