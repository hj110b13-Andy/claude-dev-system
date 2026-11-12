"""這個 repo 自己的結構閘門（skill cds-project-audit 第 5 步：盤點後把目前的循環數當閘門裝進測試，只准降不准升）。

2026-11-12 全方位健檢盤點結果：循環依賴 0 組。之後任何改動讓 installer／hooks／tools 之間出現循環匯入，這個測試就會失敗。
工具就在這個 repo 的 tools/ 底下，所以不需要「工具不在就 skip」。
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MAX_CYCLES = 0  # 2026-11-12 的數字；只准降（已經是 0）


class DependencyGate(unittest.TestCase):
    def test_no_new_dependency_cycles(self):
        r = subprocess.run([sys.executable, str(REPO / "tools" / "project-scan.py"), str(REPO), "--max-cycles", str(MAX_CYCLES)],
                           capture_output=True, timeout=120)
        out = (r.stdout + r.stderr).decode("utf-8", "replace")
        self.assertEqual(r.returncode, 0, "循環依賴超過門檻 " + str(MAX_CYCLES) + "：" + out)

    def test_gate_does_not_write_into_repo(self):
        idx = REPO / ".claude" / "project-scan.json"
        before = idx.stat().st_mtime_ns if idx.exists() else None
        subprocess.run([sys.executable, str(REPO / "tools" / "project-scan.py"), str(REPO), "--max-cycles", str(MAX_CYCLES)],
                       capture_output=True, timeout=120)
        after = idx.stat().st_mtime_ns if idx.exists() else None
        self.assertEqual(before, after, "--max-cycles 是閘門，不可寫索引檔")


if __name__ == "__main__":
    unittest.main()
