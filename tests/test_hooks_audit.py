"""健檢 fix-hook（2026-11-12）：hooks/usage_guard.py 的回歸測試，類別名對應稽核條目 A～N（HK-01～HK-13、TB-14）。
每個測試都用新載入的模組＋暫存 CLAUDE_CONFIG_DIR（setUp 建、addCleanup 刪），不碰真實 ~/.claude、不打網路（fetch 一律換成假的）。"""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import inspect
import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "hooks" / "usage_guard.py"
FUTURE = "2999-01-01T00:00:00+00:00"
PAST = "2026-11-01T00:00:00+00:00"


def load_hook(home):
    """以 home 為 CLAUDE_CONFIG_DIR 載入一份新的模組（模組層常數都在 import 時依它算好）。"""
    with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(home)}):
        spec = importlib.util.spec_from_file_location("ug_audit_%d" % random.randrange(1 << 30), HOOK)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)  # type: ignore[union-attr]
    return m


class HookCase(unittest.TestCase):
    """共用：暫存 home（關掉會碰真實系統的殘留程序與暫存量測）、新模組、跑 main 的工具。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cds-audit-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        cfgd = self.home / "claude-dev-system" / "config"
        cfgd.mkdir(parents=True)
        (cfgd / "dispatch-config.json").write_text(json.dumps({"procCheck": {"enabled": False}, "cleanup": {"claudeTempWarnGB": 0}}),
                                                   encoding="utf-8")
        (self.home / "state").mkdir()
        (self.home / "settings.json").write_text(json.dumps({"language": "chinese"}), encoding="utf-8")
        self.ug = load_hook(self.home)
        self.fetch_calls = []
        self.fetch_result = None

        def fake_fetch():
            self.fetch_calls.append(1)
            return self.fetch_result
        self.ug.fetch = fake_fetch
        self.proj = self.tmp / "proj"
        (self.proj / ".claude").mkdir(parents=True)
        (self.proj / ".git").mkdir()
        (self.proj / "CLAUDE.md").write_text("x", encoding="utf-8")
        (self.proj / ".claude" / "project-scan.json").write_text(json.dumps({"version": 2, "problems": []}), encoding="utf-8")

    def usage(self, **kw):
        d = {"five_hour_pct": 10.0, "five_hour_resets_at": FUTURE, "seven_day_pct": 10.0, "seven_day_resets_at": FUTURE, "fetched_at": time.time()}
        d.update(kw)
        Path(self.ug.USAGE).write_text(json.dumps(d), encoding="utf-8")

    def run_main(self, payload):
        buf = io.StringIO()
        saved = sys.stdin
        sys.stdin = io.StringIO(json.dumps(payload, ensure_ascii=False))
        try:
            with contextlib.redirect_stdout(buf):
                self.ug.main()
        finally:
            sys.stdin = saved
        out = buf.getvalue().strip()
        return json.loads(out) if out else None

    def ctx(self, out):
        return ((out or {}).get("hookSpecificOutput") or {}).get("additionalContext") or ""


# ---------------- A：HK-01／HK-02 狀態檔寫入 ----------------
class A_AtomicStateWrite(HookCase):
    def test_atomic_write_permission_error_retries_then_false_without_leftover(self):
        p = os.path.join(self.ug.STATE_DIR, "x.json")
        self.ug.REPLACE_SLEEP = 0
        with mock.patch.object(self.ug.os, "replace", side_effect=PermissionError("held")) as rp:
            self.assertFalse(self.ug._atomic_write_json(p, {"a": 1}), "失敗回 False、不丟例外")
        self.assertEqual(rp.call_count, self.ug.REPLACE_TRIES, "PermissionError 要重試")
        self.assertEqual([n for n in os.listdir(self.ug.STATE_DIR) if n.endswith(".tmp")], [], "暫存檔要刪掉")
        self.assertTrue(self.ug._atomic_write_json(p, {"a": 1}))
        self.assertEqual(json.loads(Path(p).read_text(encoding="utf-8")), {"a": 1})

    def test_temp_name_carries_pid(self):
        seen = []
        real = os.replace

        def spy(a, b):
            seen.append(os.path.basename(a))
            return real(a, b)
        with mock.patch.object(self.ug.os, "replace", side_effect=spy):
            self.ug._atomic_write_json(os.path.join(self.ug.STATE_DIR, "y.json"), {})
        self.assertIn(str(os.getpid()), seen[0])

    def test_corrupt_file_not_overwritten_with_empty(self):
        pa = Path(self.ug.PA_STATE)
        pa.write_text('{"align|c:/p": "0.26.0", "remind": {', encoding="utf-8")  # 半份 JSON
        st = self.ug._pa_load()
        self.assertEqual(dict(st), {})
        self.assertTrue(st._bad, "呼叫端要知道是壞檔不是空檔")
        st["x"] = 1
        self.assertFalse(self.ug._pa_save(st), "這一輪不寫")
        self.assertEqual(Path(str(pa) + ".corrupt").read_text(encoding="utf-8"), '{"align|c:/p": "0.26.0", "remind": {', "壞檔留一份")
        self.assertFalse(pa.exists(), "沒有拿空內容蓋掉")

    def test_concurrent_read_modify_write_keeps_both_keys(self):
        # 兩個程序先後讀到同一份，各加自己的鍵再寫：原本後寫的蓋掉先寫的（e1 期望 320 鍵只留 12）
        self.ug._pa_save({"base": 1})
        a, b = self.ug._pa_load(), self.ug._pa_load()
        a["from_a"] = 1
        b["from_b"] = 1
        b.pop("base")
        self.assertTrue(self.ug._pa_save(a))
        self.assertTrue(self.ug._pa_save(b))
        self.assertEqual(json.loads(Path(self.ug.PA_STATE).read_text(encoding="utf-8")), {"from_b": 1, "from_a": 1}, "兩邊加的都在、刪的照刪")

    def test_nested_remind_sessions_merge(self):
        self.ug._pa_save({"remind": {"s1": {}, "s2": {}}})
        a, b = self.ug._pa_load(), self.ug._pa_load()
        a["remind"]["s1"]["git|x"] = 1
        b["remind"]["s2"]["inst|y"] = 1
        self.ug._pa_save(a)
        self.ug._pa_save(b)
        rem = json.loads(Path(self.ug.PA_STATE).read_text(encoding="utf-8"))["remind"]
        self.assertEqual(rem, {"s1": {"git|x": 1}, "s2": {"inst|y": 1}})

    def test_os_level_lock_times_out_quickly(self):
        p = os.path.join(self.ug.STATE_DIR, "z.json")
        fd1, ok1 = self.ug._acquire_lock(p)
        try:
            t0 = time.monotonic()
            fd2, ok2 = self.ug._acquire_lock(p, wait=0.1)
            spent = time.monotonic() - t0
            self.ug._release_lock(fd2, ok2)
        finally:
            self.ug._release_lock(fd1, ok1)
        self.assertTrue(ok1)
        self.assertFalse(ok2, "別人拿著鎖：拿不到")
        self.assertLess(spent, 0.5, "等待有上限，hook 不可被卡住")
        fd3, ok3 = self.ug._acquire_lock(p, wait=0.1)
        self.ug._release_lock(fd3, ok3)
        self.assertTrue(ok3, "釋放後拿得到")
        self.assertEqual(self.ug.LOCK_WAIT, 0.3)

    def test_save_without_lock_still_writes(self):
        with mock.patch.object(self.ug, "_acquire_lock", return_value=(None, False)):
            self.assertTrue(self.ug._pa_save({"k": 1}), "拿不到鎖照舊不帶鎖寫")
        self.assertEqual(json.loads(Path(self.ug.PA_STATE).read_text(encoding="utf-8")), {"k": 1})

    def test_main_still_outputs_when_state_write_fails(self):
        self.usage(five_hour_pct=90.0)
        self.ug.REPLACE_SLEEP = 0
        with mock.patch.object(self.ug.os, "replace", side_effect=PermissionError("held")):
            out = self.run_main({"hook_event_name": "UserPromptSubmit", "session_id": "s", "cwd": str(self.proj)})
        self.assertIn("【用量守門（自動）】", self.ctx(out), "存狀態失敗不可讓提醒消失")

    def test_main_outputs_when_usage_json_held_open(self):
        self.usage(five_hour_pct=90.0)
        self.ug.REPLACE_SLEEP = 0
        with open(self.ug.USAGE, encoding="utf-8"):
            out = self.run_main({"hook_event_name": "UserPromptSubmit", "session_id": "s", "cwd": str(self.proj)})
        self.assertIn("【用量守門（自動）】", self.ctx(out))

    def test_all_state_files_go_through_atomic_writer(self):
        src = HOOK.read_text(encoding="utf-8")
        self.assertNotRegex(src, r'open\([^)]*,\s*"w"', "狀態檔不可再直接 open('w')（只有 append 的 log 例外）")
        self.assertNotIn('USAGE + ".tmp"', src)

    def test_tool_reminders_writes_only_on_change(self):
        calls = []
        real = self.ug._atomic_write_json

        def spy(*a, **k):
            calls.append(a[0])
            return real(*a, **k)
        self.ug._atomic_write_json = spy
        p = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "session_id": "s1", "cwd": str(self.proj)}
        self.ug.tool_reminders(p)
        n = len(calls)
        self.ug.tool_reminders(p)
        self.ug.tool_reminders(p)
        self.assertEqual(len(calls), n, "內容沒變不寫檔")


# ---------------- B：HK-03 過期用量 ----------------
class B_StaleUsage(HookCase):
    def p(self):
        return {"hook_event_name": "UserPromptSubmit", "session_id": "s", "cwd": str(self.proj)}

    def test_failed_fetch_with_past_reset_does_not_alert(self):
        self.usage(five_hour_pct=90.0, five_hour_resets_at=PAST, fetched_at=0)
        out = self.run_main(self.p())
        self.assertEqual(len(self.fetch_calls), 1)
        self.assertNotIn("用量守門", self.ctx(out))

    def test_failed_fetch_with_future_reset_still_alerts(self):
        self.usage(five_hour_pct=90.0, five_hour_resets_at=FUTURE, fetched_at=0)
        self.assertIn("【用量守門（自動）】5 小時用量 90%", self.ctx(self.run_main(self.p())))

    def test_current_pct_rules(self):
        now = time.time()
        cp = self.ug.current_pct
        self.assertEqual(cp({"p": 90.0, "r": FUTURE}, "p", "r", now), 90.0)
        self.assertIsNone(cp({"p": 90.0, "r": PAST}, "p", "r", now), "重置時間已過")
        self.assertIsNone(cp({"p": 90.0, "r": "壞", "fetched_at": 5, "fetch_failed_at": 5}, "p", "r", now), "抓取失敗＋解析不了")
        self.assertEqual(cp({"p": 90.0, "r": None, "fetched_at": 9, "fetch_failed_at": 5}, "p", "r", now), 90.0, "剛抓成功但沒有重置時間：照用")
        self.assertIsNone(cp({"r": FUTURE}, "p", "r", now))

    def test_seven_day_past_reset_ignored(self):
        self.usage(seven_day_pct=99.0, seven_day_resets_at=PAST, fetched_at=0)
        self.assertNotIn("7 天用量", self.ctx(self.run_main(self.p())))


# ---------------- C：HK-04 路徑大小寫 ----------------
class C_PathCase(HookCase):
    @unittest.skipUnless(os.name == "nt", "Windows 才不分大小寫")
    def test_lowercase_drive_home_is_skipped(self):
        fake_home = self.tmp / "UserHome"
        fake_home.mkdir()
        (fake_home / "a.py").write_text("x", encoding="utf-8")
        low = str(fake_home)
        low = low[0].swapcase() + low[1:].lower()
        with mock.patch.object(self.ug.os.path, "expanduser", return_value=str(fake_home)):
            self.assertIsNone(self.ug._pa_skip(low), "小寫磁碟代號的家目錄也是家目錄")
            self.assertIsNone(self.ug._pa_skip(str(fake_home)))
            sub = fake_home / "work"
            sub.mkdir()
            self.assertEqual(self.ug._pa_skip(str(sub)), str(sub), "回傳值維持原樣")

    def test_installed_copy_changelog_any_case(self):
        fp = os.path.join(self.ug.HOME, "claude-dev-system", "CHANGELOG.md")
        self.assertEqual(self.ug._installed_copy(fp), "claude-dev-system/" + ("changelog.md" if os.name == "nt" else "CHANGELOG.md"))

    @unittest.skipUnless(os.name == "nt", "Windows 才不分大小寫")
    def test_memory_read_case_insensitive(self):
        mem = self.tmp / "projects" / "c--Users-X-proj" / "memory"
        mem.mkdir(parents=True)
        (mem / "MEMORY.md").write_text("x", encoding="utf-8")
        (mem / "feedback-a.md").write_text("x", encoding="utf-8")
        self.assertTrue(self.ug.sub_memory_read("C:/U/.claude/projects/C--USERS-X-PROJ/MEMORY/Feedback-A.md", str(mem)))


# ---------------- D：HK-05 stdin 一律 UTF-8 ----------------
class D_StdinUtf8(HookCase):
    def test_read_payload_ignores_system_codepage(self):
        raw = json.dumps({"hook_event_name": "X", "cwd": "C:/專案"}, ensure_ascii=False).encode("utf-8")
        saved = sys.stdin
        sys.stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="cp950", errors="replace")
        try:
            self.assertEqual(self.ug._read_payload()["cwd"], "C:/專案")
        finally:
            sys.stdin = saved

    def test_subprocess_without_pythonutf8_sees_chinese_cwd(self):
        zh = self.tmp / "中文專案"
        (zh / ".git").mkdir(parents=True)
        self.usage()
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.home))
        env.pop("PYTHONUTF8", None)
        env.pop("PYTHONIOENCODING", None)
        payload = {"hook_event_name": "UserPromptSubmit", "session_id": "s", "cwd": str(zh), "prompt": "嗨"}
        r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                           capture_output=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0)
        self.assertIn("【專案自動化（hook）】", json.loads(r.stdout.decode("ascii"))["hookSpecificOutput"]["additionalContext"])

    def test_no_text_open_without_encoding(self):
        tree = ast.parse(HOOK.read_text(encoding="utf-8"))
        bad = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "open":
                mode = n.args[1].value if len(n.args) > 1 and isinstance(n.args[1], ast.Constant) else "r"
                if "b" not in mode and not any(k.arg == "encoding" for k in n.keywords):
                    bad.append(n.lineno)
        self.assertEqual(bad, [], "文字模式 open 都要指定 encoding")


# ---------------- E：HK-06 系統合成訊息 ----------------
SYN = {"type": "assistant", "isApiErrorMessage": True, "error": "rate_limit",
       "message": {"role": "assistant", "model": "<synthetic>", "content": [{"type": "text", "text": "You've hit your 5-hour limit · resets 1:10am (Asia/Taipei) and this is long"}]}}


class E_SyntheticMessages(HookCase):
    def write_agent(self, rows):
        sub = self.tmp / "projects" / "slug" / "sess" / "subagents"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / "agent-a1.jsonl").write_text(chr(10).join(json.dumps(r, ensure_ascii=False) for r in rows) + chr(10), encoding="utf-8")

    def nudge(self):
        return self.ug.subagent_lang_nudge({"tool_name": "Bash", "agent_id": "a1", "agent_type": "general-purpose", "session_id": "sess",
                                            "cwd": str(self.tmp), "transcript_path": str(self.tmp / "projects" / "slug" / "sess.jsonl")})

    def test_lang_nudge_ignores_rate_limit_message(self):
        self.write_agent([{"type": "user", "message": {"role": "user", "content": "做事"}},
                          {"type": "assistant", "message": {"role": "assistant", "model": "claude-opus-5-5", "content": [{"type": "text", "text": "我先看檔案結構，再跑測試確認沒有壞掉的地方。"}]}},
                          SYN])
        self.assertIsNone(self.nudge(), "用量上限的系統訊息不是 agent 寫的英文")

    def test_lang_nudge_model_lt_prefix_without_flag(self):
        syn = json.loads(json.dumps(SYN))
        syn.pop("isApiErrorMessage")
        self.write_agent([{"type": "user", "message": {"role": "user", "content": "做事"}}, syn])
        self.assertIsNone(self.nudge())

    def test_sg_last_turn_skips_synthetic(self):
        tp = self.tmp / "t.jsonl"
        rows = [{"type": "user", "message": {"role": "user", "content": "問題？"}},
                {"type": "assistant", "message": {"role": "assistant", "model": "m", "content": [{"type": "text", "text": "回答"}]}}, SYN]
        tp.write_text(chr(10).join(json.dumps(r, ensure_ascii=False) for r in rows) + chr(10), encoding="utf-8")
        self.assertEqual(self.ug.sg_last_turn(str(tp)), ("問題？", "回答"))

    def test_is_synthetic_is_single_source(self):
        self.assertTrue(self.ug._is_synthetic(SYN))
        self.assertFalse(self.ug._is_synthetic({"type": "assistant", "message": {"model": "claude-opus-5-5"}}))
        src = HOOK.read_text(encoding="utf-8")
        self.assertEqual(src.count('.startswith("<")'), 1, "判斷只寫在 _is_synthetic 一處")


# ---------------- F：HK-07 少做白工 ----------------
class F_LessWork(HookCase):
    # 用計數不用丟例外：被測函式會吞掉例外，丟例外測不出有沒有被呼叫
    def test_no_source_count_when_claude_md_and_index_exist(self):
        with mock.patch.object(self.ug, "_pa_count_sources", return_value=(0, False)) as cnt:
            self.assertIsNone(self.ug.project_auto_msg(str(self.proj), "s1"))
        self.assertEqual(cnt.call_count, 0, "有 CLAUDE.md 也有索引：不數檔")

    def test_no_source_count_when_already_seen(self):
        (self.proj / "CLAUDE.md").unlink()
        self.assertIn("cds-project-init", self.ug.project_auto_msg(str(self.proj), "s1"))
        with mock.patch.object(self.ug, "_pa_count_sources", return_value=(0, False)) as cnt:
            self.assertIsNone(self.ug.project_auto_msg(str(self.proj), "s1"))
        self.assertEqual(cnt.call_count, 0, "去重命中就不數檔")

    def test_deferred_throttle_before_loading_resgate(self):
        Path(self.ug.DEFERRED).write_text(json.dumps({"items": [{"id": 1, "project": str(self.proj), "desc": "x"}]}), encoding="utf-8")
        st = {"deferred|s1": 10_000.0}
        with mock.patch.object(self.ug, "_tool_mod") as tm:
            self.assertIsNone(self.ug.deferred_msg(str(self.proj), "s1", st, now=10_100.0))
        self.assertEqual(tm.call_count, 0, "節流中不該載入 resgate")

    def test_same_decisions_as_before(self):
        p2 = self.tmp / "p2"
        p2.mkdir()
        for i in range(12):
            (p2 / f"m{i}.py").write_text("x", encoding="utf-8")
        self.assertIn("cds-project-init", self.ug.project_auto_msg(str(p2), "a"), "非 git、原始碼 ≥ 10 → init")
        (p2 / "CLAUDE.md").write_text("x", encoding="utf-8")
        self.assertIn("cds-project-audit", self.ug.project_auto_msg(str(p2), "b"), "有 CLAUDE.md 沒索引 → audit")
        p3 = self.tmp / "p3"
        p3.mkdir()
        (p3 / "a.py").write_text("x", encoding="utf-8")
        self.assertIsNone(self.ug.project_auto_msg(str(p3), "c"), "不算專案")


# ---------------- G：HK-08 去重記多場對話 ----------------
class G_DedupeSessions(HookCase):
    def setUp(self):
        super().setUp()
        (self.proj / "CLAUDE.md").unlink()
        (self.proj / "PROGRESS.md").write_text("x" + chr(10) * 700, encoding="utf-8")

    def test_alternating_sessions_inject_once_each(self):
        got = [bool(self.ug.project_auto_msg(str(self.proj), s)) for s in ("A", "B", "A", "B", "A")]
        self.assertEqual(got, [True, True, False, False, False])
        got = [bool(self.ug.health_msg(str(self.proj), session_id=s)) for s in ("A", "B", "A", "B")]
        self.assertEqual(got, [True, True, False, False])

    def test_compact_injects_then_next_prompt_does_not_repeat(self):
        self.assertTrue(self.ug.project_auto_msg(str(self.proj), "S"))
        self.assertTrue(self.ug.health_msg(str(self.proj), session_id="S"))
        c = self.ug.compact_msg(str(self.proj), "S")
        self.assertIn("專案自動化", c, "壓縮後照樣重新注入")
        self.assertIn("專案健康檢查", c)
        self.assertIsNone(self.ug.project_auto_msg(str(self.proj), "S"), "壓縮後下一則不重複")
        self.assertIsNone(self.ug.health_msg(str(self.proj), session_id="S"))

    def test_old_format_state_is_read(self):
        key = os.path.abspath(str(self.proj)).lower()
        day = time.strftime("%Y-%m-%d")
        Path(self.ug.PA_STATE).write_text(json.dumps({key: {"session": "OLD", "what": "init", "at": "x"},
                                                      "health|" + key: day + "|OLD"}), encoding="utf-8")
        self.assertIsNone(self.ug.project_auto_msg(str(self.proj), "OLD"), "舊格式 session 字串：不重新注入")
        self.assertIsNone(self.ug.health_msg(str(self.proj), session_id="OLD"), "舊格式「日期|session」：不重新注入")
        self.assertTrue(self.ug.project_auto_msg(str(self.proj), "NEW"))
        rec = json.loads(Path(self.ug.PA_STATE).read_text(encoding="utf-8"))[key]
        self.assertEqual(rec["sessions"], ["OLD", "NEW"])
        self.assertEqual(rec["session"], "NEW", "保留 session 欄位：舊版讀得懂")

    def test_session_list_capped(self):
        for i in range(40):
            self.ug.project_auto_msg(str(self.proj), f"s{i}")
        rec = json.loads(Path(self.ug.PA_STATE).read_text(encoding="utf-8"))[os.path.abspath(str(self.proj)).lower()]
        self.assertEqual(len(rec["sessions"]), 30)
        self.assertEqual(rec["sessions"][-1], "s39")


# ---------------- H：HK-09 修剪 ----------------
class H_Prune(HookCase):
    def test_per_session_keys_pruned_keep_recent(self):
        st = {f"compactions|s{i}": 1 for i in range(250)}
        st.update({f"procs|s{i}": {"at": i, "seen": []} for i in range(210)})
        st["deferred|x"] = 1.0
        st["align|c:/p"] = "0.26.0"
        self.ug._pa_save(st)
        d = json.loads(Path(self.ug.PA_STATE).read_text(encoding="utf-8"))
        comp = [k for k in d if k.startswith("compactions|")]
        self.assertEqual(len(comp), 200)
        self.assertIn("compactions|s249", d)
        self.assertNotIn("compactions|s0", d)
        self.assertEqual(len([k for k in d if k.startswith("procs|")]), 200)
        self.assertIn("deferred|x", d)
        self.assertIn("align|c:/p", d, "其他鍵不動")

    def test_compaction_update_moves_key_to_end(self):
        st = {f"compactions|s{i}": 1 for i in range(200)}
        self.ug._pa_save(st)
        self.ug.compact_msg(None, "s0")  # s0 是最舊的，更新後要變成最新
        self.ug.compact_msg(None, "new")
        d = json.loads(Path(self.ug.PA_STATE).read_text(encoding="utf-8"))
        self.assertEqual(d.get("compactions|s0"), 2)
        self.assertIn("compactions|new", d)
        self.assertNotIn("compactions|s1", d, "最久沒寫的被修掉")


# ---------------- I：HK-11 測試檔 ----------------
class I_TestFileLayout(unittest.TestCase):
    def test_main_guard_at_end_and_direct_run_count_matches(self):
        src = (REPO / "tests" / "test_hooks.py").read_text(encoding="utf-8").rstrip().splitlines()
        self.assertEqual(src[-2:], ['if __name__ == "__main__":', "    unittest.main()"])
        tree = ast.parse("\n".join(src))
        guards = [n for n in tree.body if isinstance(n, ast.If) and "__main__" in ast.dump(n.test)]
        self.assertEqual(len(guards), 1)
        self.assertIs(tree.body[-1], guards[0], "unittest.main() 之後不可再有測試類別")
        n_mod = unittest.defaultTestLoader.loadTestsFromName("tests.test_hooks").countTestCases()
        r = subprocess.run([sys.executable, str(REPO / "tests" / "test_hooks.py")], capture_output=True, cwd=str(REPO), timeout=300)
        m = re.search(rb"Ran (\d+) test", r.stderr)
        self.assertEqual(int(m.group(1)), n_mod, "直接執行與 -m unittest 項數相同")

    def test_setups_clean_their_temp_dirs(self):
        src = (REPO / "tests" / "test_hooks.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("self.tmp = Path(tempfile.mkdtemp("), src.count("self.addCleanup(shutil.rmtree, self.tmp, True)"))


# ---------------- J：HK-12 文件 ----------------
class J_Docs(unittest.TestCase):
    def test_docstring_lists_all_events_and_tags(self):
        sys.path.insert(0, str(REPO / "installer"))
        try:
            from cds import settings_ops
        finally:
            sys.path.pop(0)
        src = HOOK.read_text(encoding="utf-8")
        doc = ast.get_docstring(ast.parse(src))
        for ev, _m in settings_ops.HOOK_SPECS:
            self.assertIn(ev, doc, ev)
        body = src.split('"""', 2)[2]
        tags = set(re.findall(r"【[^】]{1,20}（(?:hook|自動)）】", body))
        self.assertTrue(tags)
        for t in tags:
            self.assertIn(t, doc, "docstring 要列出實際會注入的提醒：" + t)
        self.assertNotIn("本腳本安靜失效", doc, "與 HK-03 的實際行為矛盾的舊說法要改掉")
        self.assertNotIn("只在 agent 裡、只一次", src)


# ---------------- K：HK-13 Stop 從檔尾讀 ----------------
def ref_last_turn(ug, tp):
    """0.27.0 以前的從頭掃描（加上 HK-06 的合成訊息過濾），當作行為基準。"""
    prompt, answer = None, []
    try:
        with open(tp, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"type":"user"' in line or '"type": "user"' in line:
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    if d.get("type") != "user" or d.get("isSidechain"):
                        continue
                    t = ug._sg_text((d.get("message") or {}).get("content"))
                    if t is not None and t.strip():
                        prompt, answer = t, []
                elif '"type":"assistant"' in line or '"type": "assistant"' in line:
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    if d.get("type") != "assistant" or d.get("isSidechain") or ug._is_synthetic(d):
                        continue
                    for b in (d.get("message") or {}).get("content") or []:
                        if isinstance(b, dict) and b.get("type") == "text" and b.get("text"):
                            answer.append(b["text"])
    except Exception:
        return None, None
    return prompt, "\n".join(answer)


def ref_last_human(ug, tp, crons):
    last = None
    try:
        with open(tp, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"type":"user"' not in line and '"type": "user"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("type") != "user" or d.get("isSidechain"):
                    continue
                t = ug._sg_text((d.get("message") or {}).get("content"))
                if t is not None and t.strip() and not ug.sg_is_auto(t, crons):
                    last = t
    except Exception:
        return None
    return last


class K_TailRead(HookCase):
    def rand_rows(self, rng):
        rows = []
        for _ in range(rng.randrange(0, 40)):
            k = rng.randrange(9)
            txt = rng.choice(["問題？", "好", "  ", "長" * rng.randrange(1, 300), "<task-notification>x", "巡檢：列出所有進行中的背景任務"])
            if k == 0:
                rows.append(json.dumps({"type": "user", "message": {"role": "user", "content": txt}}, ensure_ascii=False))
            elif k == 1:
                rows.append(json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "r"}]}}))
            elif k == 2:
                rows.append(json.dumps({"type": "assistant", "message": {"role": "assistant", "model": "m", "content": [{"type": "text", "text": txt}, {"type": "text", "text": "二"}]}}, ensure_ascii=False))
            elif k == 3:
                rows.append(json.dumps({"type": "assistant", "isSidechain": True, "message": {"content": [{"type": "text", "text": "旁"}]}}, ensure_ascii=False))
            elif k == 4:
                rows.append(json.dumps(SYN))
            elif k == 5:
                rows.append('{"type":"user", 壞掉的行')
            elif k == 6:
                rows.append(json.dumps({"type": "attachment", "x": "y" * rng.randrange(50)}))
            elif k == 7:
                rows.append(json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": txt}]}}, ensure_ascii=False))
            else:
                rows.append("")
        nl = rng.choice(["\n", "\r\n"])
        return nl.join(rows) + rng.choice(["", nl])

    def test_same_result_as_full_scan_random(self):
        rng = random.Random(20261112)
        tp = self.tmp / "t.jsonl"
        crons = [{"prompt": "巡檢：列出所有進行中的背景任務"}]
        for chunk in (7, 64, 1 << 20):
            self.ug.SG_CHUNK = chunk
            for _ in range(150):
                tp.write_bytes(self.rand_rows(rng).encode("utf-8"))
                self.assertEqual(self.ug.sg_last_turn(str(tp)), ref_last_turn(self.ug, str(tp)))
                self.assertEqual(self.ug.sg_last_human(str(tp), crons), ref_last_human(self.ug, str(tp), crons))

    def test_missing_file(self):
        self.assertEqual(self.ug.sg_last_turn(str(self.tmp / "none.jsonl")), (None, None))
        self.assertIsNone(self.ug.sg_last_human(str(self.tmp / "none.jsonl")))
        self.assertEqual(self.ug.sg_last_turn(""), (None, None))

    def test_stops_early(self):
        tp = self.tmp / "big.jsonl"
        filler = json.dumps({"type": "attachment", "x": "y" * 1000}) + "\n"
        with open(tp, "w", encoding="utf-8") as f:
            for _ in range(3000):
                f.write(filler)
            f.write(json.dumps({"type": "user", "message": {"content": "最後的問題？"}}, ensure_ascii=False) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"model": "m", "content": [{"type": "text", "text": "答"}]}}, ensure_ascii=False) + "\n")
        self.ug.SG_CHUNK = 4096
        reads = []
        real = self.ug._rev_lines

        def counting(p):
            for x in real(p):
                reads.append(1)
                yield x
        self.ug._rev_lines = counting
        self.assertEqual(self.ug.sg_last_turn(str(tp)), ("最後的問題？", "答"))
        self.assertLess(len(reads), 10, "找到最後一則提示就停，不讀整份")


# ---------------- L：TB-14 _sub_scan 半行 ----------------
class L_SubScanPartialLine(HookCase):
    def test_truncated_multibyte_last_line(self):
        p = self.tmp / "agent-x.jsonl"
        good = [{"type": "user", "message": {"role": "user", "content": "派工"}},
                {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "m/a.md"}}]}}]
        data = (chr(10).join(json.dumps(r, ensure_ascii=False) for r in good) + chr(10)).encode("utf-8")
        data += json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "寫到一半"}]}}, ensure_ascii=False).encode("utf-8")[:-13]  # 切在「到」字的 3 個位元組中間
        p.write_bytes(data)
        scan = self.ug._sub_scan(str(p))
        self.assertIsNotNone(scan, "最後一行寫到一半不可讓整份回 None")
        self.assertEqual(scan["prompt"], "派工")
        self.assertEqual(scan["tools"], ["Read"])
        self.assertEqual(scan["reads"], ["m/a.md"])
        self.assertEqual(set(scan), {"prompt", "tools", "reads", "cmds"}, "tools/agent-audit.py 依賴的鍵不變")


# ---------------- M：靜態分析 ----------------
class M_Static(unittest.TestCase):
    def test_no_placeholderless_fstring_and_no_unused_poll(self):
        tree = ast.parse(HOOK.read_text(encoding="utf-8"))
        specs = {id(n.format_spec) for n in ast.walk(tree) if isinstance(n, ast.FormattedValue) and n.format_spec is not None}
        bad = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) and id(n) not in specs
               and not any(isinstance(v, ast.FormattedValue) for v in n.values)]
        self.assertEqual(bad, [], "沒有佔位符的 f-string")
        fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "compact_from_subagent"][0]
        self.assertNotIn("poll", [a.arg for a in fn.args.args])

    def test_agent_audit_contract_names(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        ug = load_hook(tmp)
        for name in ("SUB_WEB_TOOL", "SUB_COMMIT", "SUB_LANG_MIN_RATIO", "_sub_cjk_ratio", "_sub_scan", "_command_segments", "sub_memory_read"):
            self.assertTrue(hasattr(ug, name), name)
        self.assertEqual(list(inspect.signature(ug._sub_scan).parameters), ["path"])
        self.assertEqual(list(inspect.signature(ug.sub_memory_read).parameters), ["blob", "mem_dir"])


# ---------------- N：main 端到端與測試缺口 ----------------
class N_MainPaths(HookCase):
    def ups(self, **kw):
        return dict({"hook_event_name": "UserPromptSubmit", "session_id": "s", "cwd": str(self.proj)}, **kw)

    def post(self, **kw):
        return dict({"hook_event_name": "PostToolUse", "session_id": "s", "cwd": str(self.proj), "tool_name": "Bash",
                     "tool_input": {"command": "ls"}}, **kw)

    def test_threshold_injection_shape(self):
        self.usage(five_hour_pct=90.0, seven_day_pct=98.0)
        out = self.run_main(self.ups())
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        c = self.ctx(out)
        self.assertIn("【用量守門（自動）】5 小時用量 90%（門檻 85%）", c)
        self.assertIn("7 天用量 98%（門檻 97%", c)
        self.assertEqual(self.fetch_calls, [], "TTL 內不抓")

    def test_below_threshold_silent(self):
        self.usage(five_hour_pct=50.0)
        self.assertIsNone(self.run_main(self.ups()))

    def test_post_tool_use_alert_repeat_throttle(self):
        self.usage(five_hour_pct=90.0, alerted_at=time.time() - 10)
        self.assertIsNone(self.run_main(self.post()), "PostToolUse 600 秒內不重複")
        self.assertIn("用量守門", self.ctx(self.run_main(self.ups())), "UserPromptSubmit 每次都提醒")
        self.usage(five_hour_pct=90.0, alerted_at=time.time() - 700)
        self.assertIn("用量守門", self.ctx(self.run_main(self.post())))

    def test_near_threshold_ttl_60(self):
        self.usage(five_hour_pct=75.0, fetched_at=time.time() - 100)
        self.fetch_result = {"five_hour_pct": 76.0, "five_hour_resets_at": FUTURE, "seven_day_pct": 10.0, "seven_day_resets_at": FUTURE}
        self.run_main(self.ups())
        self.assertEqual(len(self.fetch_calls), 1, "接近門檻：60 秒就重抓")
        self.assertEqual(json.loads(Path(self.ug.USAGE).read_text(encoding="utf-8"))["five_hour_pct"], 76.0)
        self.usage(five_hour_pct=10.0, fetched_at=time.time() - 100)
        self.run_main(self.ups())
        self.assertEqual(len(self.fetch_calls), 1, "離門檻遠：300 秒內不抓")

    def test_stop_shape(self):
        tp = self.tmp / "t.jsonl"
        rows = [{"type": "user", "message": {"content": "台北 101 幾公尺？"}},
                {"type": "assistant", "message": {"model": "m", "content": [{"type": "text", "text": "說明" * 120 + "2004 年完工，508 公尺。"}]}}]
        tp.write_text(chr(10).join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
        out = self.run_main({"hook_event_name": "Stop", "session_id": "s", "transcript_path": str(tp), "stop_hook_active": False})
        self.assertEqual(set(out), {"decision", "reason"})
        self.assertEqual(out["decision"], "block")
        self.assertIn("【查證守門（hook）】", out["reason"])
        self.assertIsNone(self.run_main({"hook_event_name": "Stop", "transcript_path": str(tp), "stop_hook_active": True}))

    def agent_files(self, aid="a1", prompt="do it", tools=()):
        sub = self.tmp / "projects" / "slug" / "sess" / "subagents"
        sub.mkdir(parents=True, exist_ok=True)
        rows = [{"type": "user", "message": {"content": prompt}}] + [
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": n, "input": {}}]}} for n in tools]
        (sub / f"agent-{aid}.jsonl").write_text(chr(10).join(json.dumps(r) for r in rows), encoding="utf-8")
        (sub / f"agent-{aid}.meta.json").write_text("{}", encoding="utf-8")
        return {"session_id": "sess", "agent_id": aid, "agent_type": "general-purpose", "cwd": str(self.tmp),
                "transcript_path": str(self.tmp / "projects" / "slug" / "sess.jsonl"), "agent_transcript_path": str(sub / f"agent-{aid}.jsonl")}

    def test_pretooluse_handback_shape(self):
        p = self.agent_files()
        en = "All modules were refactored and every test passes; details follow below. " * 4
        out = self.run_main(dict(p, hook_event_name="PreToolUse", tool_name="SubagentHandback", tool_input={"message": en}))
        h = out["hookSpecificOutput"]
        self.assertEqual((h["hookEventName"], h["permissionDecision"]), ("PreToolUse", "deny"))
        self.assertIn("【報告守門（hook）】", h["permissionDecisionReason"])
        self.assertIsNone(self.run_main(dict(p, hook_event_name="PreToolUse", tool_name="Bash", tool_input={})), "其他工具不管")

    def test_subagent_stop_shape(self):
        p = self.agent_files("a2")
        en = "All modules were refactored and every test passes; details follow below. " * 4
        out = self.run_main(dict(p, hook_event_name="SubagentStop", stop_hook_active=False, last_assistant_message=en))
        self.assertEqual(set(out), {"decision", "reason"})
        self.assertEqual(out["decision"], "block")

    def test_subagent_start_shape(self):
        out = self.run_main({"hook_event_name": "SubagentStart", "cwd": str(self.tmp), "agent_type": "Explore", "transcript_path": str(self.tmp / "x.jsonl")})
        h = out["hookSpecificOutput"]
        self.assertEqual(h["hookEventName"], "SubagentStart")
        self.assertIn("【派工補充（hook）】", h["additionalContext"])

    def test_session_start_shape(self):
        out = self.run_main({"hook_event_name": "SessionStart", "source": "resume", "session_id": "s", "cwd": str(self.proj)})
        h = out["hookSpecificOutput"]
        self.assertEqual(h["hookEventName"], "SessionStart")
        self.assertIn("【壓縮後重新開工（hook）】", h["additionalContext"])
        self.assertIsNone(self.run_main({"hook_event_name": "SessionStart", "source": "startup", "session_id": "s", "cwd": str(self.proj)}))

    def test_output_is_ascii_json(self):
        self.usage(five_hour_pct=90.0)
        buf = io.StringIO()
        saved = sys.stdin
        sys.stdin = io.StringIO(json.dumps(self.ups()))
        try:
            with contextlib.redirect_stdout(buf):
                self.ug.main()
        finally:
            sys.stdin = saved
        buf.getvalue().encode("ascii")  # ensure_ascii：不可有非 ASCII 字元

    def test_stale_agents(self):
        Path(self.ug.BOARD_FILE).write_text('<div class="ct">🟡 agent-x 修 hook</div><div class="cm">8 分鐘前｜該追問</div>'
                                            '<div class="ct">🟢 主對話 協調</div><div class="cm">該追問</div>'
                                            '<div class="ct">🟢 agent-y</div><div class="cm">2 分鐘前</div>', encoding="utf-8")
        self.assertEqual(self.ug.stale_agents(), ["agent-x 修 hook"])
        self.usage()
        c = self.ctx(self.run_main(self.ups()))
        self.assertIn("【看板逾時提醒（自動）】", c)
        self.assertIn("agent-x 修 hook", c)
        self.assertIsNone(self.run_main(self.ups()), "同一批 10 分鐘內不重複")

    def test_hook_debug_only_when_enabled_and_no_token(self):
        cred = {"claudeAiOauth": {"accessToken": "sk-ant-oat-SECRET-TOKEN"}}
        Path(self.ug.CRED).write_text(json.dumps(cred), encoding="utf-8")
        dbg = os.path.join(self.ug.STATE_DIR, "hook-debug.jsonl")
        self.ug._hook_debug("t", {"transcript_path": str(self.tmp / "none.jsonl"), "session_id": "s"})
        self.assertFalse(os.path.exists(dbg), "沒有 hook-debug.on 什麼都不寫")
        Path(self.ug.STATE_DIR, "hook-debug.on").write_text("", encoding="utf-8")
        self.ug._hook_debug("t", {"transcript_path": str(self.tmp / "none.jsonl"), "session_id": "s", "long": "z" * 500})
        rec = json.loads(Path(dbg).read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(rec["tag"], "t")
        self.assertEqual(len(rec["payload"]["long"]), 300, "長字串截斷")
        for f in os.listdir(self.ug.STATE_DIR):
            if f != "hook-debug.on" and os.path.isfile(os.path.join(self.ug.STATE_DIR, f)):
                self.assertNotIn("SECRET-TOKEN", Path(self.ug.STATE_DIR, f).read_text(encoding="utf-8"), f)

    def test_token_never_in_outputs_or_state(self):
        Path(self.ug.CRED).write_text(json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oat-SECRET-TOKEN"}}), encoding="utf-8")
        self.usage(five_hour_pct=90.0, fetched_at=0)

        def boom():
            raise OSError("network down")
        self.ug.fetch = boom
        out = self.run_main(self.ups())
        self.assertNotIn("SECRET-TOKEN", json.dumps(out))
        for f in os.listdir(self.ug.STATE_DIR):
            self.assertNotIn("SECRET-TOKEN", Path(self.ug.STATE_DIR, f).read_text(encoding="utf-8", errors="replace"), f)


if __name__ == "__main__":
    unittest.main()
