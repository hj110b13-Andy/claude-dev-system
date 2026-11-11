"""文件與程式一致性（0.27.0 全方位健檢新增）。

起因：2026-11-12 健檢逐項對照「文件說的」與「程式做的」，查到 22 處對不上——README 寫「目前 0.9.5」（實際 0.26.1）、
安裝說明寫 skill「七個」（實際 10 個）、自我測試「九題」（實際 11 題）、hook 事件只列 2 個（實際 7 個）、
firecrawl 一處寫預設關一處寫預設開、巡檢固定 prompt 有三份副本。這些數字與清單都會隨版本變，
所以這裡用測試守住：文件不可再寫死會漂移的數字，寫了清單就要與程式的唯一來源一致。
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "installer"))

from cds import MANIFEST_SCHEMA, manifest, payload, settings_ops  # noqa: E402


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


DOCS = ["README.md", "CLAUDE.md"] + sorted(p.relative_to(REPO).as_posix() for p in (REPO / "docs").glob("*.md")
                                             if p.name not in ("PROJECT-INVENTORY.md",))


class NoDriftingNumbers(unittest.TestCase):
    def test_readme_does_not_hardcode_current_version(self):
        self.assertIsNone(re.search(r"目前\s*\d+\.\d+\.\d+）", read("README.md")), "README 不寫死目前版本，版本只看 config/VERSION")

    def test_selftest_count_matches_wherever_a_number_is_written(self):
        n = len(json.loads(read("config/selftest.json"))["cases"])
        zh = "零一二三四五六七八九十"
        for rel in DOCS + ["installer/install.py", "installer/cds/selftest.py"]:
            for m in re.finditer(r"(?<![原寫「])([0-9]+|[一二三四五六七八九十]+)\s*題(?!目)", read(rel)):
                tok = m.group(1)
                val = int(tok) if tok.isdigit() else (zh.index(tok) if len(tok) == 1 else None)
                ctx = read(rel)[max(0, m.start() - 30):m.end() + 5].replace(chr(10), " ")
                if "原寫" in ctx or "smoke" in ctx or "三題" in ctx or "幾題" in ctx or "多題" in ctx:
                    continue  # 「原寫九題」是更正紀錄；smoke 三題是另一個清單
                self.assertEqual(val, n, f"{rel} 寫了題數「{tok} 題」，config/selftest.json 實際 {n} 題：…{ctx}…")

    def test_skill_list_in_readme_matches_repo(self):
        names = payload.skill_names(REPO)
        readme = read("README.md")
        for s in names:
            self.assertIn(f"`{s}`", readme, f"README「內容與分層」沒列 skill {s}")
        listed = set(re.findall(r"`(cds-[a-z-]+)`", readme))
        self.assertEqual(listed - set(names), set(), "README 列了不存在的 skill")

    def test_hook_events_documented(self):
        events = [e for e, _ in settings_ops.HOOK_SPECS]
        for rel in ("README.md", "docs/compatibility.md"):
            t = read(rel)
            for e in events:
                self.assertIn(e, t, f"{rel} 沒提到 hook 事件 {e}（唯一來源 settings_ops.HOOK_SPECS）")

    def test_manifest_schema_documented(self):
        self.assertEqual(sorted(manifest.MIGRATIONS), list(range(MANIFEST_SCHEMA)), "每一版 schema 都要有遷移函式")
        chain = "→".join(str(i) for i in range(MANIFEST_SCHEMA + 1))
        self.assertIn(chain, read("docs/compatibility.md"), f"docs/compatibility.md 的遷移鏈要寫 {chain}")
        self.assertIn(chain, read("docs/update.md"), f"docs/update.md 的遷移鏈要寫 {chain}")


class DefaultsMatchConfig(unittest.TestCase):
    def test_firecrawl_default_wording(self):
        default_on = bool(json.loads(read("config/web-sources.json"))["mcpServers"]["firecrawl"].get("default"))
        self.assertTrue(default_on, "這個測試假設 firecrawl 預設開；改了預設要一起改文件")
        for rel in ("README.md", "docs/web-sources.md"):
            for line in read(rel).splitlines():
                if "firecrawl" in line and "預設關" in line and "原寫" not in line:
                    self.fail(f"{rel} 把 firecrawl 寫成預設關，config/web-sources.json 是 default: true：{line[:80]}")

    def test_usage_threshold_defaults(self):
        cfg = json.loads(read("config/dispatch-config.json"))["usageThresholdPct"]
        five, seven = int(cfg["fiveHour"]), int(cfg["sevenDay"])
        t = read("rules/workflow.md")
        for m in re.finditer(r"預設[^\n。；]{0,12}?(\d+)\s*%?\s*[／/]\s*(\d+)\s*%", t):
            ctx = t[max(0, m.start() - 25):m.end() + 5]
            if "原寫" in ctx:
                continue
            self.assertEqual((int(m.group(1)), int(m.group(2))), (five, seven),
                             f"rules/workflow.md 寫的預設門檻與 config/dispatch-config.json（{five}／{seven}）不同：{ctx}")

    def test_key_modes_listed(self):
        from cds import web
        note = json.loads(read("config/web-sources.json"))["localKeys"]["_keyMode"]
        for mode in web.KEY_MODES:
            self.assertIn(mode, note, f"web-sources.json 的 _keyMode 說明漏了 {mode}")


class RulesStayInSync(unittest.TestCase):
    """core.md（每次請求都載入的短版）與細則之間。"""

    PATROL = re.compile(r"prompt 固定為「(巡檢：.+?)」")

    def test_patrol_prompt_identical_in_all_copies(self):
        found = {}
        for rel in ("rules/core.md", "rules/core-detail.md", "rules/web-sources.md"):
            m = self.PATROL.search(read(rel))
            self.assertIsNotNone(m, f"{rel} 找不到巡檢的固定 prompt")
            found[rel] = m.group(1)
        self.assertEqual(len(set(found.values())), 1, "巡檢固定 prompt 三處必須逐字相同（改一處要三處一起改）：" + "、".join(found))

    def test_every_detail_section_has_a_core_bullet(self):
        core = read("rules/core.md")
        bullets = re.findall(r"^- \*\*(.+?)\*\*", core, flags=re.M)
        for title in re.findall(r"^## (.+)$", read("rules/core-detail.md"), flags=re.M):
            self.assertTrue(any(b.startswith(title) or title.startswith(b.split("（")[0]) for b in bullets),
                            f"core-detail.md 的〈{title}〉在 core.md 找不到對應的條文")

    def test_referenced_rule_files_exist(self):
        names = {p.name for p in (REPO / "rules").glob("*.md")}
        for rel in ["rules/" + n for n in sorted(names)] + ["README.md"] + [p.relative_to(REPO).as_posix() for p in (REPO / "skills").glob("*/SKILL.md")]:
            for ref in re.findall(r"`(?:[\w~./-]*/)?rules/([\w-]+\.md)`", read(rel)):
                self.assertIn(ref, names, f"{rel} 提到 rules/{ref}，這個檔不存在")

    def test_core_md_stays_short(self):
        core = read("rules/core.md")
        self.assertLessEqual(len(core.splitlines()), 40, "core.md 目標 40 行內（rules/README.md）")


class HookTagsDocumented(unittest.TestCase):
    def test_every_tag_in_hook_is_in_workflow_table(self):
        tags = sorted(set(re.findall(r"【[^】\n]{2,20}】", read("hooks/usage_guard.py"))))
        self.assertGreaterEqual(len(tags), 15)
        table = read("rules/workflow.md")
        missing = [t for t in tags if t not in table]
        self.assertEqual(missing, [], "hook 會輸出、但 rules/workflow.md〈hook 標籤對照〉沒列的標籤")

    def test_tags_named_in_core_exist_in_hook(self):
        hook = read("hooks/usage_guard.py")
        for t in re.findall(r"【[^】\n]{2,20}】", read("rules/core.md")):
            base = t.strip("【】").split("（")[0]
            self.assertIn("【" + base, hook, f"core.md 提到 {t}，hook 裡沒有這個標籤")


class WorkflowsAreSane(unittest.TestCase):
    def test_release_only_on_semver_tags_and_checks_version(self):
        y = read(".github/workflows/release.yml")
        self.assertIn('"v[0-9]+.[0-9]+.[0-9]+"', y, "發布只認 v主.次.修 的 tag")
        self.assertNotIn('tags: ["v*"]', y)
        self.assertIn("config/VERSION", y, "發布前要比對 tag 與 config/VERSION")
        self.assertIn("python -m unittest discover -s tests", y, "發布前要跑測試")
        for line in y.splitlines():
            m = re.match(r"\s*(?:- )?uses:\s*([\w.-]+)/([\w.-]+)@(\S+)", line)
            if m and m.group(1) != "actions":
                self.assertRegex(m.group(3), r"^[0-9a-f]{40}$", f"第三方 action 要釘在 commit SHA：{line.strip()}")

    def test_tests_workflow_runs_on_push(self):
        y = read(".github/workflows/tests.yml")
        self.assertIn("python -m unittest discover -s tests", y)
        self.assertIn("master", y)
        self.assertIn('"3.10"', y, "要在宣稱的最低 Python 版本上跑")


if __name__ == "__main__":
    unittest.main()
