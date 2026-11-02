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


if __name__ == "__main__":
    unittest.main()
