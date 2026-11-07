"""發版衛生（0.15.0）：VERSION 已經打過 tag，之後又有改到發布內容的 commit，就必須先把 VERSION 往上加。

起因：2026-11-04 兩場對話同時改這個 repo——18:27 發了 v0.14.2，18:32 另一場（AI-Search&Fetch）又提交了 project-scan 修正，
版本仍標 0.14.2、不在任何 Release，其他裝置「檢查更新」看版本相同就拿不到。
只算會進 payload 或 exe 的路徑；PROGRESS.md、docs 這類不影響使用者安裝的不算。沒有 git、沒有這個 tag（CI 淺層 checkout）就略過。
"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SHIPPED = ("rules", "tools", "hooks", "skills", "config", "installer", "CHANGELOG.md", "README.md")


def _git(*args):
    r = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, timeout=30)
    return r.returncode, r.stdout.decode("utf-8", "replace").strip()


class ReleaseHygiene(unittest.TestCase):
    def test_no_shipped_commits_after_current_version_tag(self):
        ver = (REPO / "config" / "VERSION").read_text(encoding="utf-8").strip()
        code, _ = _git("rev-parse", "--verify", "--quiet", f"refs/tags/v{ver}")
        if code != 0:
            self.skipTest(f"沒有 v{ver} tag（還沒發布或淺層 checkout）")
        code, out = _git("log", "--format=%h %s", f"v{ver}..HEAD", "--", *SHIPPED)
        if code != 0:
            self.skipTest("git log 失敗")
        self.assertEqual(out, "", f"v{ver} 已發布，之後又有改到發布內容的 commit，要先把 config/VERSION 往上加再發 Release：" + chr(10) + out)


if __name__ == "__main__":
    unittest.main()
