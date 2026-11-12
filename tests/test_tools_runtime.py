"""tools/resgate.py、procs.py、cleanup.py、video.py 的健檢（0.27.0 fix-tools-a）回歸測試。

類別名對應稽核條目（TA-xx）與派工項目（A～T）；每一條都是「修之前會失敗、修之後通過」。
只用標準庫、不連網、不下載影片、不碰真實的 ~/.claude（resgate 一律設 CLAUDE_CONFIG_DIR 到暫存資料夾）。
"""
from __future__ import annotations

import builtins
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def load_tool(name: str, alias: str):
    """用唯一的模組名載入 tools/<name>.py（不污染 sys.modules 裡別的測試載入的同名模組）。"""
    spec = importlib.util.spec_from_file_location(alias, TOOLS / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失敗：{r.stderr}")
    return r.stdout.strip()


class _RgBase(unittest.TestCase):
    """resgate：CLAUDE_CONFIG_DIR 指到暫存資料夾，絕不寫到真實的 ~/.claude/state/。"""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="cds-rgrt-"))
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self._env = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.home)
        self.rg = load_tool("resgate.py", "cds_resgate_rt")

    def tearDown(self):
        if self._env is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = self._env

    def jobs_file(self) -> Path:
        return Path(self.rg.deferred_path())


class DeferredJobsConcurrency(_RgBase):
    """A／TA-01：多程序同時寫延後清單會丟工作、檔案損毀 → 檔案鎖＋唯一暫存檔＋壞檔改名保留。"""

    def test_concurrent_defer_processes_keep_every_job(self):
        n = 8
        procs = [subprocess.Popen([sys.executable, str(TOOLS / "resgate.py"), "defer", "--project", str(self.home), "--desc", f"c{i}"],
                                  env={**ENV, "CLAUDE_CONFIG_DIR": str(self.home)}, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                 for i in range(n)]
        rcs = []
        for p in procs:
            _out, err = p.communicate(timeout=120)
            rcs.append(p.returncode)
            self.assertEqual(p.returncode, 0, err.decode("utf-8", "replace")[-300:])
        self.assertEqual(rcs, [0] * n)
        d = json.loads(self.jobs_file().read_text(encoding="utf-8"))
        self.assertEqual(sorted(x["id"] for x in d["items"]), list(range(1, n + 1)), "每筆都在、編號不重複")
        self.assertEqual(d["nextId"], n + 1)
        leftovers = [p.name for p in self.jobs_file().parent.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [], "不留暫存檔")

    def test_corrupt_file_is_renamed_not_silently_wiped(self):
        self.rg.defer(str(self.home), "job1", "x")
        self.rg.defer(str(self.home), "job2", "y")
        p = self.jobs_file()
        p.write_text(p.read_text(encoding="utf-8")[:-5], encoding="utf-8")  # 寫到一半被中斷
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            it = self.rg.defer(str(self.home), "job3", "z")
        bad = [q for q in p.parent.iterdir() if ".bad-" in q.name]
        self.assertEqual(len(bad), 1, "壞檔要改名保留")
        self.assertIn("job2", bad[0].read_text(encoding="utf-8"), "保留的是原檔內容")
        self.assertIn("deferred-jobs.json.bad-", err.getvalue(), "要印一行說明")
        self.assertGreater(it["id"], 2, "編號不可與壞檔裡看得出的舊編號重複（免得 done 舊編號刪到新的一筆）")
        self.assertEqual([x["desc"] for x in self.rg.load_jobs()["items"]], ["job3"])

    def test_load_jobs_does_not_modify_corrupt_file(self):
        p = self.jobs_file()
        p.parent.mkdir(parents=True)
        p.write_text("{broken", encoding="utf-8")
        self.assertEqual(self.rg.load_jobs()["items"], [])
        self.assertEqual(p.read_text(encoding="utf-8"), "{broken", "只讀的函式（hook 也在讀）不改檔")

    def test_lock_times_out_when_held(self):
        p = str(self.jobs_file())
        self.rg.LOCK_TIMEOUT = 0.3
        with self.rg._locked(p):
            t0 = time.monotonic()
            with self.assertRaises(self.rg.JobsLockError):
                with self.rg._locked(p):
                    pass
            self.assertLess(time.monotonic() - t0, 3.0)
        with self.rg._locked(p):  # 釋放後又拿得到
            pass

    def test_replace_permission_error_is_retried(self):
        real = os.replace
        calls = {"n": 0}

        def flaky(a, b):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise PermissionError("busy")
            return real(a, b)
        self.rg.LOCK_POLL = 0.001
        with mock.patch.object(self.rg.os, "replace", flaky):
            self.rg.defer(str(self.home), "j", "r")
        self.assertEqual(calls["n"], 3)
        self.assertEqual(len(self.rg.load_jobs()["items"]), 1)

    def test_run_prints_insufficient_even_if_write_fails(self):
        self.rg.wait = lambda cfg: (False, 1.9, 585.0)
        out = io.StringIO()
        with mock.patch.object(self.rg, "defer", side_effect=PermissionError("locked")), contextlib.redirect_stdout(out):
            rc = self.rg.main(["run", "--desc", "t", "--project", str(self.home), "--", sys.executable, "-c", "pass"])
        self.assertEqual(rc, 1)
        self.assertIn("記憶體不足、沒有執行", out.getvalue(), "寫檔失敗也不可變成 traceback")

    def test_lock_failure_in_run_is_not_a_traceback(self):
        self.rg.wait = lambda cfg: (False, 1.9, 585.0)
        self.rg.LOCK_TIMEOUT = 0.2
        out = io.StringIO()
        with self.rg._locked(str(self.jobs_file())), contextlib.redirect_stdout(out):
            rc = self.rg.main(["run", "--desc", "t", "--project", str(self.home), "--", sys.executable, "-c", "pass"])
        self.assertEqual(rc, 1)
        self.assertIn("記憶體不足、沒有執行", out.getvalue())

    def test_old_file_format_still_readable(self):
        p = self.jobs_file()
        p.parent.mkdir(parents=True)
        old = {"version": 1, "nextId": 4, "items": [{"id": 3, "project": "C:/p", "desc": "d", "rerun": "r", "agent": "",
                                                       "registeredAt": "2026-11-11T00:00:00", "freeGB": 1.0, "needGB": 3.0}]}
        p.write_text(json.dumps(old), encoding="utf-8")
        self.assertEqual(self.rg.load_jobs()["items"][0]["id"], 3)
        it = self.rg.defer("C:/p", "d2", "")
        self.assertEqual(it["id"], 4)


class RunResolvesCmdShims(_RgBase):
    """B／TA-02：`run -- npm` 在 Windows 回 127（CreateProcess 不照 PATHEXT 找 .cmd）→ 先用 shutil.which 換完整路徑。"""

    def _tool_dir(self):
        d = self.home / "bin"
        d.mkdir()
        if os.name == "nt":
            (d / "hellotool.cmd").write_text("@echo off" + chr(13) + chr(10) + "echo hello-from-shim %1" + chr(13) + chr(10) + "exit /b 3" + chr(13) + chr(10), encoding="utf-8")
        else:
            f = d / "hellotool"
            f.write_text("#!/bin/sh" + chr(10) + 'echo hello-from-shim "$1"' + chr(10) + "exit 3" + chr(10), encoding="utf-8")
            f.chmod(0o755)
        return d

    def test_run_finds_cmd_shim_on_path_and_passes_exit_code(self):
        d = self._tool_dir()
        self.rg.wait = lambda cfg: (True, 8.0, 0.0)
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"PATH": str(d) + os.pathsep + os.environ.get("PATH", "")}), contextlib.redirect_stdout(out):
            rc = self.rg.main(["run", "--desc", "t", "--project", str(self.home), "--", "hellotool", "arg1"])
        self.assertEqual(rc, 3, "找得到 .cmd 並把它的 exit code 透傳（修之前回 127）")

    def test_run_never_uses_shell(self):
        self.rg.wait = lambda cfg: (True, 8.0, 0.0)
        seen = {}

        def fake_call(cmd, **kw):
            seen["cmd"], seen["kw"] = cmd, kw
            return 0
        with mock.patch.object(self.rg.subprocess, "call", fake_call), contextlib.redirect_stdout(io.StringIO()):
            self.rg.main(["run", "--desc", "t", "--project", str(self.home), "--", sys.executable, "-c", "a b", 'q"x', "中文 參數", ""])
        self.assertFalse(seen["kw"].get("shell"), "不可改成 shell=True")
        self.assertEqual(seen["cmd"][1:], ["-c", "a b", 'q"x', "中文 參數", ""], "參數原樣透傳")

    def test_unknown_command_still_reports_127(self):
        self.rg.wait = lambda cfg: (True, 8.0, 0.0)
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = self.rg.main(["run", "--desc", "t", "--project", str(self.home), "--", "no-such-tool-zzz-12345"])
        self.assertEqual(rc, 127)
        self.assertIn("指令無法啟動", err.getvalue())

    def test_docstring_states_no_shell_and_wait_limit(self):
        doc = self.rg.__doc__
        self.assertIn("指令不經 shell", doc)
        self.assertIn("bash -c", doc)
        self.assertIn("可能先等最多", doc, "C／TA-03：run 可能先等最多 waitMinutes 分鐘")


class FreeGbFallback(_RgBase):
    """D／TA-04：沒有 /proc/meminfo 的 posix（macOS）原本回 None，sysconf 後備走不到。mock 驗證，未在 macOS 實跑。"""

    def test_sysconf_fallback_reachable_without_proc_meminfo(self):
        fake_os = SimpleNamespace(name="posix", sysconf=lambda k: 1024 * 1024)
        real_open = builtins.open

        def fake_open(f, *a, **k):
            if f == "/proc/meminfo":
                raise FileNotFoundError(f)
            return real_open(f, *a, **k)
        with mock.patch.object(self.rg, "os", fake_os), mock.patch.object(builtins, "open", fake_open):
            got = self.rg.free_gb()
        self.assertEqual(got, 1024.0, "sysconf 後備：頁數 × 頁大小 = 2^40 位元組 = 1024 GB")

    def test_proc_meminfo_still_preferred(self):
        fake_os = SimpleNamespace(name="posix", sysconf=lambda k: 1)
        real_open = builtins.open

        def fake_open(f, *a, **k):
            if f == "/proc/meminfo":
                return io.StringIO("MemTotal: 1 kB" + chr(10) + "MemAvailable: 2097152 kB" + chr(10))
            return real_open(f, *a, **k)
        with mock.patch.object(self.rg, "os", fake_os), mock.patch.object(builtins, "open", fake_open):
            self.assertEqual(self.rg.free_gb(), 2.0)

    def test_none_when_nothing_available(self):
        def boom(k):
            raise ValueError(k)
        fake_os = SimpleNamespace(name="posix", sysconf=boom)
        with mock.patch.object(self.rg, "os", fake_os), mock.patch.object(builtins, "open", mock.Mock(side_effect=FileNotFoundError())):
            self.assertIsNone(self.rg.free_gb())


class SameProjectScope(_RgBase):
    """E／TA-05：「上層資料夾」不再被當成同專案；只認同一個專案根或 worktree。F／TA-06：--project 名稱改記專案根。"""

    def setUp(self):
        super().setUp()
        self.top = self.home / "Documents"
        self.proj = self.top / "proj"
        (self.proj / ".git").mkdir(parents=True)
        (self.proj / "sub" / "deeper").mkdir(parents=True)
        self.wt = self.proj / ".claude" / "worktrees" / "w1"
        self.wt.mkdir(parents=True)
        (self.wt / ".git").write_text("gitdir: x", encoding="utf-8")
        self.other = self.top / "other"
        (self.other / ".git").mkdir(parents=True)

    def test_parent_folder_is_not_same_project(self):
        sp = self.rg.same_project
        self.assertFalse(sp(str(self.home), str(self.proj)), "家目錄登記的工作不該在每個專案被叫去跑")
        self.assertFalse(sp(str(self.top), str(self.proj)), "上層資料夾登記的不算")
        self.assertFalse(sp(str(self.proj), str(self.top)), "反過來也不算（Stock-web 的工作從上層資料夾）")
        self.assertFalse(sp(str(self.other), str(self.proj)))

    def test_same_root_and_worktree_count(self):
        sp = self.rg.same_project
        self.assertTrue(sp(str(self.proj), str(self.proj)))
        self.assertTrue(sp(str(self.proj), str(self.proj / "sub" / "deeper")), "子資料夾：專案根相同")
        self.assertTrue(sp(str(self.proj / "sub"), str(self.proj)))
        self.assertTrue(sp(str(self.proj), str(self.wt)), "worktree 看得到主 repo 登記的工作")
        self.assertTrue(sp(str(self.wt), str(self.proj)), "主 repo 看得到 worktree 登記的工作")
        self.assertFalse(sp(str(self.other), str(self.wt)))

    def test_unrecorded_project_counts_as_same(self):
        self.assertTrue(self.rg.same_project("", str(self.proj)))
        self.assertTrue(self.rg.same_project(None, str(self.proj)))

    def test_legacy_name_record_still_matches(self):
        """0.26.1 的 `--project claude-dev-system` 被記成「cwd＼名稱」（不存在的路徑）。"""
        legacy = str(self.proj / "claude-dev-system")
        self.assertFalse(os.path.exists(legacy))
        self.assertTrue(self.rg.same_project(legacy, str(self.proj)))
        self.assertFalse(self.rg.same_project(legacy, str(self.other)))

    def test_project_name_records_project_root(self):
        """F：不是現存路徑的 --project 名稱改記專案根，不記「cwd＼名稱」。"""
        pp = self.rg.project_path
        self.assertEqual(os.path.normcase(pp("proj-name", cwd=str(self.proj / "sub"))), os.path.normcase(str(self.proj)))
        self.assertEqual(os.path.normcase(pp(str(self.other))), os.path.normcase(str(self.other)), "現存路徑照原樣（絕對化）")
        self.assertEqual(pp(""), "")
        absent = str(self.home / "nope" / "x")
        self.assertEqual(os.path.normcase(pp(absent)), os.path.normcase(absent), "明確給的不存在絕對路徑照原樣")

    def test_defer_by_name_lists_correct_project(self):
        old = os.getcwd()
        os.chdir(self.proj / "sub")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = self.rg.main(["defer", "--project", "claude-dev-system", "--desc", "x"])
        finally:
            os.chdir(old)
        self.assertEqual(rc, 0)
        item = self.rg.load_jobs()["items"][0]
        self.assertEqual(os.path.normcase(os.path.realpath(item["project"])), os.path.normcase(os.path.realpath(str(self.proj))),
                         "比 realpath：macOS 的暫存資料夾 /var 是 /private/var 的連結")
        self.assertTrue(self.rg.same_project(item["project"], str(self.proj)))
        self.assertFalse(self.rg.same_project(item["project"], str(self.other)))


class GateOutputAndDone(_RgBase):
    """G／TA-07：等待結果訊息 flush（經管線時不排在子程序輸出後面）；done 找不到編號回 exit 1。"""

    def test_gate_messages_are_flushed(self):
        seen = []
        real_print = builtins.print

        def spy(*a, **k):
            seen.append(k.get("flush"))
            real_print(*a, **k)
        self.rg.wait = lambda cfg: (True, 8.0, 0.0)
        with mock.patch.object(builtins, "print", spy), contextlib.redirect_stdout(io.StringIO()):
            self.rg.gate(SimpleNamespace(desc="t", project=str(self.home), rerun="", agent=""), self.rg.load_cfg())
        self.assertEqual(seen, [True])
        seen.clear()
        self.rg.wait = lambda cfg: (False, 1.0, 1.0)
        with mock.patch.object(builtins, "print", spy), contextlib.redirect_stdout(io.StringIO()):
            self.rg.gate(SimpleNamespace(desc="t", project=str(self.home), rerun="", agent=""), self.rg.load_cfg())
        self.assertTrue(seen and all(seen))

    def test_done_missing_id_exits_1_and_existing_exits_0(self):
        it = self.rg.defer(str(self.home), "d", "r")
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            self.assertEqual(self.rg.main(["done", "999"]), 1)
        self.assertIn("清單裡沒有 #999", err.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.rg.main(["done", str(it["id"])]), 0)
        self.assertEqual(self.rg.load_jobs()["items"], [])


class CleanupWorktreeSafety(unittest.TestCase):
    """H／TA-08：剛建好、還在用的 worktree（含被忽略的輸出、.env）不可判成可刪；I／TA-09：--apply --json 有錯也回 1；J／TA-10：temp 說明。"""

    def setUp(self):
        self.cl = load_tool("cleanup.py", "cds_cleanup_rt")
        self.tmp = Path(tempfile.mkdtemp(prefix="cds-clrt-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.g("init", "-q", "-b", "main")
        (self.repo / "a.txt").write_text("a" + chr(10), encoding="utf-8")
        (self.repo / ".gitignore").write_text("out/" + chr(10) + ".env" + chr(10) + "node_modules/" + chr(10), encoding="utf-8")
        self.g("add", ".")
        self.g("commit", "-qm", "init")

    def g(self, *args, cwd=None):
        return git(cwd or self.repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args)

    def wt(self, name, commit=False, merge=None):
        w = self.repo / ".claude" / "worktrees" / name
        self.g("worktree", "add", "-q", "-b", name, str(w))
        if commit:
            (w / (name + ".txt")).write_text(name + chr(10), encoding="utf-8")
            self.g("add", ".", cwd=w)
            self.g("commit", "-qm", name, cwd=w)
        if merge == "ff":
            self.g("merge", "-q", "--ff-only", name)
        elif merge == "noff":
            self.g("merge", "-q", "--no-ff", "-m", "m", name)
        return w

    def plan(self, name, **kw):
        return {Path(i["path"]).name: i for i in self.cl.plan_worktrees(self.repo, **kw)}[name]

    def test_fresh_worktree_with_ignored_files_is_kept_and_survives_apply(self):
        w = self.wt("fresh")
        (w / "out").mkdir()
        (w / "out" / "result.csv").write_text("x" * 1000, encoding="utf-8")
        (w / ".env").write_text("SECRET=1" + chr(10), encoding="utf-8")
        it = self.plan("fresh")
        self.assertEqual(it["action"], "keep", it)
        self.assertIn("被 git 忽略", it["why"])
        self.assertIn(".env", it["why"], "原因欄列出是哪些檔")
        _freed, errors = self.cl.apply_plan([it], self.repo)
        self.assertEqual(errors, [])
        self.assertTrue((w / "out" / "result.csv").exists() and (w / ".env").exists())

    def test_branch_without_own_commit_is_kept_even_when_clean(self):
        self.wt("noyet")
        it = self.plan("noyet")
        self.assertEqual(it["action"], "keep")
        self.assertIn("未開始或進行中", it["why"])

    def test_rebuildable_ignored_dirs_do_not_block_deletion(self):
        w = self.wt("done1", commit=True, merge="noff")
        (w / "node_modules" / "pkg").mkdir(parents=True)
        (w / "node_modules" / "pkg" / "i.js").write_text("x", encoding="utf-8")
        it = self.plan("done1")
        self.assertEqual(it["action"], "delete", it)

    def test_fast_forward_merged_branch_with_own_commit_is_deletable(self):
        self.wt("ffdone", commit=True, merge="ff")
        it = self.plan("ffdone")
        self.assertEqual(it["action"], "delete", "同一個 SHA 但分支自己 commit 過（已收工）→ 仍可刪：" + str(it))

    def test_recent_activity_keeps_worktree(self):
        self.wt("recent", commit=True, merge="noff")
        self.assertEqual(self.plan("recent", keep_hours=24.0)["action"], "keep")
        self.assertIn("小時內有檔案變動", self.plan("recent", keep_hours=24.0)["why"])
        self.assertEqual(self.plan("recent")["action"], "delete", "沒給 keep_hours 維持舊行為（只認內容已合併）")
        later = time.time() + 3 * 86400
        self.assertEqual(self.plan("recent", keep_hours=24.0, now=later)["action"], "delete", "超過門檻才可刪")

    def test_cli_passes_keep_hours_to_worktrees(self):
        self.wt("cli1", commit=True, merge="noff")
        r = subprocess.run([sys.executable, str(TOOLS / "cleanup.py"), "--project", str(self.repo), "--only", "worktrees", "--json"],
                           capture_output=True, env=ENV)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = {Path(i["path"]).name: i for i in json.loads(r.stdout.decode("utf-8"))}
        self.assertEqual(got["cli1"]["action"], "keep", "命令列預設 24 小時內有變動不刪")
        r2 = subprocess.run([sys.executable, str(TOOLS / "cleanup.py"), "--project", str(self.repo), "--only", "worktrees", "--json", "--keep-hours", "0"],
                            capture_output=True, env=ENV)
        got2 = {Path(i["path"]).name: i for i in json.loads(r2.stdout.decode("utf-8"))}
        self.assertEqual(got2["cli1"]["action"], "delete")

    def test_json_apply_exit_code_matches_text_mode(self):
        item = {"kind": "cache", "path": str(self.tmp / "x"), "size": 0, "action": "delete", "why": "t"}
        for errs, want in ((["boom"], 1), ([], 0)):
            for as_json in (True, False):
                argv = ["--project", str(self.repo), "--only", "cache", "--apply"] + (["--json"] if as_json else [])
                with mock.patch.object(self.cl, "build_plan", return_value=[dict(item)]),                         mock.patch.object(self.cl, "apply_plan", return_value=(0, errs)), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(self.cl.main(argv), want, (errs, as_json))

    def test_temp_plan_mentions_other_live_sessions(self):
        root = self.tmp / "claude"
        d = root / "f9e626e89eb6038f" / "old-session" / "scratchpad"
        d.mkdir(parents=True)
        (d / "x.md").write_text("x", encoding="utf-8")
        old = time.time() - 5 * 86400
        for q in (d / "x.md", d, d.parent):
            os.utime(q, (old, old))
        it = self.cl.plan_temp(root, 24, current="other")[0]
        self.assertEqual(it["action"], "delete")
        self.assertIn("別場還開著的對話", it["why"])


class ProcsPowerShellTool(unittest.TestCase):
    """K／TA-11：PowerShell 工具的程序鏈 claude.exe → cmd.exe /d /s /c "chcp 65001 & pwsh.exe …" → pwsh.exe 原本完全抓不到；
    L／TA-12：父 PID 被較新的程序重用時孤兒漏判。程序表是 2026-11-12 在本機 PowerShell 工具實測的形狀。"""

    NOW = 1_000_000.0
    LAUNCH = ('C:/WINDOWS/System32/cmd.exe /d /s /c ""C:/WINDOWS/System32/chcp.com" 65001 >nul & "C:/Program Files/PowerShell/7/pwsh.exe" -NoProfile '
              '-NonInteractive -Command "$__claudeCodeScript = $env:CLAUDE_CODE_SHELL_LAUNCHER_SCRIPT; Invoke-Expression -Command $__claudeCodeScript" "')

    def setUp(self):
        self.procs = load_tool("procs.py", "cds_procs_rt")

    def rows(self):
        n = self.NOW
        return [
            {"pid": 1, "ppid": 0, "name": "claude.exe", "start": n - 99999},
            {"pid": 70, "ppid": 1, "name": "cmd.exe", "start": n - 3 * 3600, "cmd": self.LAUNCH},
            {"pid": 71, "ppid": 70, "name": "pwsh.exe", "start": n - 3 * 3600, "cmd": "pwsh.exe -NoProfile -Command $env:CLAUDE_CODE_SHELL_LAUNCHER_SCRIPT"},
            {"pid": 72, "ppid": 71, "name": "node.exe", "start": n - 3 * 3600, "cmd": "node server.js"},
            # 使用者自己開的 cmd（沒有標記）：不可誤收
            {"pid": 90, "ppid": 1, "name": "cmd.exe", "start": n - 3 * 3600, "cmd": "cmd.exe /k dir"},
            {"pid": 91, "ppid": 90, "name": "node.exe", "start": n - 3 * 3600, "cmd": "node mine.js"},
            # Bash 工具（原本就認得）
            {"pid": 10, "ppid": 1, "name": "bash.exe", "start": n - 3 * 3600, "cmd": "bash -c \"source /c/x/shell-snapshots/s.sh && eval 'sleep 9999' < /dev/null\""},
        ]

    def test_cmd_to_pwsh_tree_is_listed_and_plain_cmd_is_not(self):
        g = self.procs.leftovers(self.rows(), lambda r: None, 1, 60, now=self.NOW)
        pids = sorted(x["pid"] for x in g)
        self.assertEqual(pids, [10, 70], "PowerShell 工具的 cmd→pwsh 樹要列出，使用者的 cmd(90) 不收")
        top = [x for x in g if x["pid"] == 70][0]
        self.assertEqual(sorted(c["name"] for c in top["children"]), ["node.exe", "pwsh.exe"], "連同子孫")
        self.assertFalse(top["orphan"])

    def test_cmd_without_marker_never_listed_even_when_orphan(self):
        rows = [{"pid": 80, "ppid": 999, "name": "cmd.exe", "start": self.NOW - 7200, "cmd": "cmd.exe /d /s /c pwsh C:/proj"}]
        self.assertEqual(self.procs.leftovers(rows, lambda r: None, None, 60, now=self.NOW, cwd_hint="C:/proj"), [])

    def test_orphan_launcher_tree_listed_when_cwd_in_cmdline(self):
        rows = [{"pid": 80, "ppid": 999, "name": "cmd.exe", "start": self.NOW - 7200, "cmd": self.LAUNCH + " C:/proj"},
                {"pid": 81, "ppid": 80, "name": "pwsh.exe", "start": self.NOW - 7200, "cmd": "pwsh.exe"}]
        g = self.procs.leftovers(rows, lambda r: None, None, 60, now=self.NOW, cwd_hint="C:/proj")
        self.assertEqual([x["pid"] for x in g], [80])
        self.assertTrue(g[0]["orphan"])
        self.assertEqual(self.procs.leftovers(rows, lambda r: None, None, 60, now=self.NOW, cwd_hint="C:/other"), [], "別的專案不列")

    def test_pid_reuse_makes_orphan_visible(self):
        n = self.NOW
        shell_cmd = "bash -c \"source /c/x/shell-snapshots/s.sh && cd C:/proj && eval 'sleep 9999' < /dev/null\""
        rows = [{"pid": 1, "ppid": 0, "name": "claude.exe", "start": n - 100},
                {"pid": 500, "ppid": 0, "name": "notepad.exe", "start": n - 60},  # 重用了舊 claude 的 PID
                {"pid": 60, "ppid": 500, "name": "bash.exe", "start": n - 7200, "cmd": shell_cmd}]
        g = self.procs.leftovers(rows, lambda r: None, 1, 60, now=n, cwd_hint="C:/proj")
        self.assertEqual([x["pid"] for x in g], [60], "父程序比子程序晚建立 → 父已不在")
        self.assertTrue(g[0]["orphan"])
        # 對照：父程序比子程序早建立（真的父）→ 不是孤兒
        rows[1]["start"] = n - 9000
        self.assertEqual(self.procs.leftovers(rows, lambda r: None, 1, 60, now=n, cwd_hint="C:/proj"), [])

    def test_docstring_describes_cmd_chain_and_unverified_platforms(self):
        doc = self.procs.__doc__
        self.assertIn("cmd.exe", doc)
        self.assertIn("CLAUDE_CODE_SHELL_LAUNCHER_SCRIPT", doc)
        self.assertIn("非 Windows 平台未驗證", doc)

    @unittest.skipUnless(os.name == "nt", "實際程序鏈只在 Windows 驗")
    def test_real_snapshot_marks_own_launcher_cmd_in_chain(self):
        """實測：本測試若是從 Claude 的 PowerShell 工具跑的，祖先裡有帶標記的 cmd.exe；從別處跑就沒有，不判失敗。"""
        rows, details = self.procs.snapshot()
        by = {r["pid"]: r for r in rows}
        cur, seen = by.get(os.getpid()), set()
        while cur and cur["pid"] not in seen:
            seen.add(cur["pid"])
            if cur["name"].lower() == "cmd.exe":
                details(cur)
                if self.procs.LAUNCHER_MARKER in (cur.get("cmd") or ""):
                    self.assertTrue(self.procs._tool_shell(cur, details))
                    return
            cur = by.get(cur["ppid"])
        self.skipTest("不是從 Claude 的 PowerShell 工具跑的，沒有可驗的 cmd.exe")


class _VideoBase(unittest.TestCase):
    """video.py：CLAUDE_CONFIG_DIR 指到暫存資料夾後才載入（HOME 在 import 時決定）；不連網、不下載、不碰真實快取。"""

    _n = 0

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="cds-vidrt-"))
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        _VideoBase._n += 1
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.home)}):
            self.v = load_tool("video.py", f"cds_video_rt_{_VideoBase._n}")
        self.assertEqual(self.v.HOME, self.home)

    def run_cli(self, *args, cwd=None):
        r = subprocess.run([sys.executable, str(TOOLS / "video.py"), *args], capture_output=True, env={**ENV, "CLAUDE_CONFIG_DIR": str(self.home)},
                           cwd=str(cwd) if cwd else None)
        return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


class VideoPureLogic(_VideoBase):
    """T：不需連網的純函式——youtube_id、時間戳換算（超過 1 小時）、_vtt_parse 去重、快取命名。"""

    def test_youtube_id_forms(self):
        yid = "dQw4w9WgXcQ"
        for src in (yid, f"https://www.youtube.com/watch?v={yid}", f"https://youtu.be/{yid}", f"https://www.youtube.com/shorts/{yid}",
                    f"https://www.youtube.com/live/{yid}?feature=share", f"https://www.youtube.com/embed/{yid}"):
            self.assertEqual(self.v.youtube_id(src), yid, src)
        self.assertIsNone(self.v.youtube_id("https://example.com/watch?v=dQw4w9WgXcQ"), "不是 youtube 網域")
        self.assertIsNone(self.v.youtube_id("short"))
        self.assertIsNone(self.v.youtube_id("C:/videos/a.mp4"))
        self.assertEqual(self.v.canonical(yid), f"https://www.youtube.com/watch?v={yid}")
        self.assertEqual(self.v.canonical("https://example.com/a.mp4"), "https://example.com/a.mp4")

    def test_timestamps_over_one_hour(self):
        v = self.v
        self.assertEqual(v.hms(5), "00:05")
        self.assertEqual(v.hms(3725.9), "01:02:05", "超過 1 小時要帶小時")
        self.assertEqual(v.hms(-3), "00:00")
        self.assertEqual(v.parse_time("1:02:05"), 3725)
        self.assertEqual(v.parse_time("12:30"), 750)
        self.assertEqual(v.parse_time("90"), 90)
        self.assertEqual(v.parse_time("0:00:01.5"), 1.5)
        self.assertEqual(v.parse_time(v.hms(7384)), 7384, "hms 與 parse_time 互為反運算")
        for bad in ("abc", "", "1:2:3:4", "1::2", "-5", "1:xx"):
            with self.assertRaises(ValueError, msg=bad):
                v.parse_time(bad)
        self.assertEqual(v.iso_duration("PT1H2M5S"), "01:02:05")

    def test_vtt_parse_dedups_rolling_captions(self):
        nl = chr(10)
        vtt = ("WEBVTT" + nl + nl +
               "00:00:01.000 --> 00:00:03.000" + nl + "hello world" + nl + nl +
               "00:00:02.000 --> 00:00:04.000" + nl + "hello world this is" + nl + nl +
               "00:00:04.000 --> 00:00:05.000" + nl + "hello world this is" + nl + nl +
               "01:00:00.500 --> 01:00:02.000" + nl + "<c>later</c>  text" + nl)
        got = self.v._vtt_parse(vtt)
        self.assertEqual([t for _s, _e, t in got], ["hello world this is", "later text"], "滾動式重複行合併、標籤去掉")
        self.assertEqual(got[0][0], 1.0)
        self.assertEqual(got[0][1], 4.0, "合併後結束時間延長")
        self.assertEqual(got[1][0], 3600.5)

    def test_cache_naming_single_source(self):
        v = self.v
        self.assertEqual(v.source_key("dQw4w9WgXcQ"), "yt_dQw4w9WgXcQ")
        k_url = v.source_key("https://example.com/a.mp4")
        self.assertTrue(k_url.startswith("url_") and v.is_cache_key(k_url), k_url)
        f = self.home / "talk.mp4"
        f.write_bytes(b"x")
        k_file = v.source_key(str(f))
        self.assertTrue(k_file.startswith("file_") and v.is_cache_key(k_file), k_file)
        self.assertTrue(v.is_cache_key("yt_dQw4w9WgXcQ"))
        for name in ("family_photos", "yt_short", "url_XYZ", "file_0123456789abc", "yt_dQw4w9WgXcQx", "cache", "x_0123456789ab", ""):
            self.assertFalse(v.is_cache_key(name), name)
        self.assertTrue(v.is_cache_key(v.cache_dir("dQw4w9WgXcQ").name), "cache_dir 建出來的名稱一定符合")

    def test_no_placeholderless_fstring(self):
        """S／TA-19：沒有佔位符的 f-string（原本第 824 行）。"""
        import ast

        tree = ast.parse((TOOLS / "video.py").read_text(encoding="utf-8"))
        specs = {id(n.format_spec) for n in ast.walk(tree) if isinstance(n, ast.FormattedValue) and n.format_spec is not None}  # {x:02d} 的格式字串也是 JoinedStr，不算
        bad = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) and id(n) not in specs and not any(isinstance(x, ast.FormattedValue) for x in n.values)]
        self.assertEqual(bad, [])

    def test_clean_cache_docstring_matches_behavior(self):
        doc = self.v.clean_cache.__doc__
        self.assertIn("最新", doc, "S／TA-21：比的是資料夾裡最新檔案的修改時間")
        self.assertIn("yt_", doc)


class VideoCaptionChoice(_VideoBase):
    """N／TA-14：兩條取字幕的路（youtube-transcript-api、yt-dlp）共用同一個排序。"""

    PREFER = ["zh-TW", "zh-Hant", "zh", "zh-Hans", "en", "ja"]

    class T:
        def __init__(self, code, gen):
            self.language_code, self.is_generated = code, gen

    def test_order_manual_then_native_auto_then_other_manual(self):
        c = self.v.choose_caption
        self.assertEqual(c(["es"], ["en"], self.PREFER, "en"), (("en", "auto"), None), "英文影片只有西班牙文手動字幕 → 要英文原生自動字幕，不是西班牙文翻譯稿")
        self.assertEqual(c(["zh-TW", "es"], ["en"], self.PREFER, "en"), (("zh-TW", "manual"), None), "偏好語言的手動字幕最優先")
        self.assertEqual(c(["es", "fr"], [], self.PREFER, "en"), (("es", "manual"), None), "沒有自動字幕才退到其他手動字幕（語言碼排序第一個）")
        self.assertEqual(c(["en"], ["ja"], self.PREFER, "en"), (("en", "manual"), None))
        self.assertEqual(c([], [], self.PREFER, "en"), (None, None))
        self.assertEqual(c(["live_chat"], [], self.PREFER, "en"), (None, None), "live_chat 不算字幕")

    def test_auto_language_must_match_video_language(self):
        c = self.v.choose_caption
        choice, note = c([], ["zh-TW"], self.PREFER, "en", asr_available=True)
        self.assertIsNone(choice)
        self.assertIn("語音辨識", note)
        choice, note = c([], ["zh-TW"], self.PREFER, "en", asr_available=False)
        self.assertEqual(choice, ("zh-TW", "auto"))
        self.assertIn("姑且使用", note)
        self.assertEqual(c([], ["en-orig", "de"], self.PREFER, "en")[0], ("en-orig", "auto"))
        self.assertEqual(c([], ["ja"], self.PREFER, None)[0], ("ja", "auto"), "影片語言不明：看偏好語言")

    def test_both_branches_pick_same_caption(self):
        v = self.v
        info = {"language": "en", "subtitles": ["es"], "automatic_captions": ["en"]}
        v.info_cached = lambda src: info
        v._fetch_track = lambda t: [(0.0, 1.0, "text in " + t.language_code)]
        picked = {}

        def fake_subs(src, lang, auto):
            picked["p"] = (lang, auto)
            return [(0.0, 1.0, "x")]
        v._ytdlp_subs = fake_subs
        src = "https://www.youtube.com/watch?v=AAAAAAAAAAA"
        v._yt_tracks = lambda vid: [self.T("es", False), self.T("en", True)]
        _p, tag1, lang1 = v.get_transcript(src, list(self.PREFER), False, "medium", None)
        shutil.rmtree(v.cache_dir(src))
        v._yt_tracks = lambda vid: None  # transcript-api 不可用 → yt-dlp 那條路
        _p, tag2, lang2 = v.get_transcript(src, list(self.PREFER), False, "medium", None)
        self.assertEqual((tag1, lang1), ("youtube_auto", "en"))
        self.assertEqual((tag2, lang2), ("subs_auto", "en"), "兩條路選到同一個字幕（修之前一條 es 手動、一條 en 自動）")
        self.assertEqual(picked["p"], ("en", True))

    def test_manual_preferred_language_in_both_branches(self):
        v = self.v
        info = {"language": "zh", "subtitles": ["zh-TW", "en"], "automatic_captions": ["zh"]}
        v.info_cached = lambda src: info
        v._fetch_track = lambda t: [(0.0, 1.0, "t")]
        v._ytdlp_subs = lambda src, lang, auto: [(0.0, 1.0, "x")]
        src = "https://www.youtube.com/watch?v=BBBBBBBBBBB"
        v._yt_tracks = lambda vid: [self.T("en", False), self.T("zh-TW", False), self.T("zh", True)]
        self.assertEqual(v.get_transcript(src, list(self.PREFER), False, "medium", None)[1:], ("youtube_manual", "zh-TW"))
        shutil.rmtree(v.cache_dir(src))
        v._yt_tracks = lambda vid: None
        self.assertEqual(v.get_transcript(src, list(self.PREFER), False, "medium", None)[1:], ("subs_manual", "zh-TW"))


class VideoCacheCleanScope(_VideoBase):
    """O／TA-15：clean_cache／auto_clean 只動本工具命名的快取資料夾；video.cacheDir 指到一般資料夾時別的資料夾不被刪。"""

    def setUp(self):
        super().setUp()
        self.shared = self.home / "shared"
        self.shared.mkdir()
        self.v.CFG["cacheDir"] = str(self.shared)
        old = time.time() - 40 * 86400
        self.names = ["family_photos", "yt_dQw4w9WgXcQ", "url_0123456789ab", "file_0123456789ab", "notes_2020"]
        for name in self.names:
            d = self.shared / name
            d.mkdir()
            (d / "video.mp4").write_bytes(b"x" * 100)
            (d / "a.txt").write_text("t", encoding="utf-8")
            for q in (d / "video.mp4", d / "a.txt", d):
                os.utime(q, (old, old))
        (self.shared / "loose.txt").write_text("x", encoding="utf-8")

    def left(self):
        return sorted(p.name for p in self.shared.iterdir())

    def test_clean_cache_only_touches_cache_named_dirs(self):
        n, freed = self.v.clean_cache(7, 30)
        self.assertEqual(n, 3, "只有 yt_／url_／file_ 三個")
        self.assertGreater(freed, 0)
        self.assertEqual(self.left(), ["family_photos", "loose.txt", "notes_2020"])

    def test_force_all_and_media_only_also_scoped(self):
        self.v.clean_cache(0, None, force_all=True, media_only=True)
        self.assertTrue((self.shared / "family_photos" / "video.mp4").exists(), "media_only 也不碰別的資料夾")
        self.assertFalse((self.shared / "yt_dQw4w9WgXcQ" / "video.mp4").exists())
        self.assertTrue((self.shared / "yt_dQw4w9WgXcQ" / "a.txt").exists(), "media_only 留逐字稿")
        self.v.clean_cache(None, None, force_all=True)
        self.assertEqual(self.left(), ["family_photos", "loose.txt", "notes_2020"])

    def test_auto_clean_scoped_via_cli(self):
        cfgd = self.home / "claude-dev-system" / "config"
        cfgd.mkdir(parents=True)
        (cfgd / "local.json").write_text(json.dumps({"keys": {}, "video": {"cacheDir": str(self.shared)}}), encoding="utf-8")
        rc, _out, err = self.run_cli("info", str(self.home / "nope.mp4"))
        self.assertEqual(rc, 2, err)
        self.assertIn("family_photos", self.left())
        self.assertIn("notes_2020", self.left())
        self.assertNotIn("yt_dQw4w9WgXcQ", self.left(), "本工具命名的舊資料夾照舊會被自動清")


class VideoArgErrors(_VideoBase):
    """P／TA-16：參數錯誤印一行中文說明、exit 2，不可 traceback（docstring 寫「2 參數或缺依賴」）。"""

    CASES = [
        (["transcript", "x.mp4", "--grep", "("], "--grep"),
        (["transcript", "x.mp4", "--start", "abc"], "--start"),
        (["transcript", "x.mp4", "--end", "1:2:3:4"], "--end"),
        (["transcript", "x.mp4", "--start", "10:00", "--end", "5:00"], "比 --end 晚"),
        (["frames", "x.mp4", "--at", "12:30,abc"], "--at"),
        (["ask", "x.mp4", "q", "--clip", "1:00", "zzz"], "--clip"),
        (["clean", "--older-than", "-1"], "--older-than"),
        (["search", "kw", "-n", "0"], "-n"),
        (["comments", "dQw4w9WgXcQ", "-n", "0"], "-n"),
        (["download", "https://example.com/v", "--max-height", "0"], "--max-height"),
    ]

    def test_exit_code_2_and_one_line_message(self):
        for args, needle in self.CASES:
            rc, out, err = self.run_cli(*args)
            self.assertEqual(rc, 2, (args, err[-200:]))
            self.assertNotIn("Traceback", err, args)
            self.assertIn(needle, err, args)
            self.assertEqual(len(err.strip().splitlines()), 1, ("一行說明", args, err))

    def test_valid_args_pass_validation(self):
        a = SimpleNamespace(cmd="transcript", grep="關鍵(字)?", start="1:00:00", end="1:10:00")
        self.assertIsNone(self.v._arg_error(a))
        self.assertIsNone(self.v._arg_error(SimpleNamespace(cmd="frames", at="12:30, 14:05,")))
        self.assertIsNone(self.v._arg_error(SimpleNamespace(cmd="clean", older_than=0)))

    def test_bad_args_do_not_trigger_auto_clean(self):
        d = self.home / "claude-dev-system" / "cache" / "video" / "yt_dQw4w9WgXcQ"
        d.mkdir(parents=True)
        (d / "a.txt").write_text("t", encoding="utf-8")
        old = time.time() - 400 * 86400
        for q in (d / "a.txt", d):
            os.utime(q, (old, old))
        rc, _o, _e = self.run_cli("clean", "--older-than", "-1")
        self.assertEqual(rc, 2)
        self.assertTrue(d.exists(), "負數 --older-than 不可把所有快取都當成太舊而刪光")


class VideoLocalFileLooksLikeId(_VideoBase):
    """Q／TA-17：沒有副檔名、剛好 11 個字元的本機檔（lecture_001）不可被當成 YouTube ID。"""

    def test_existing_path_wins_over_bare_id(self):
        f = self.home / "lecture_001"
        f.write_bytes(b"x")
        old = os.getcwd()
        os.chdir(self.home)
        try:
            self.assertIsNone(self.v.youtube_id("lecture_001"))
            self.assertTrue(self.v.source_key("lecture_001").startswith("file_"))
            self.assertEqual(self.v.canonical("lecture_001"), "lecture_001")
        finally:
            os.chdir(old)

    def test_bare_id_still_youtube_when_no_such_path(self):
        old = os.getcwd()
        os.chdir(self.home)
        try:
            self.assertEqual(self.v.youtube_id("lecture_002"), "lecture_002")
            self.assertEqual(self.v.source_key("dQw4w9WgXcQ"), "yt_dQw4w9WgXcQ")
        finally:
            os.chdir(old)


class VideoPartialFiles(_VideoBase):
    """R／TA-18（部分）：ffmpeg 轉檔先寫暫存檔名、成功才改名，中途失敗不留半截檔當完整檔。
    下載大小上限、ffmpeg／辨識逾時沒有依據的數字，不加。"""

    SRC = "https://www.youtube.com/watch?v=AAAAAAAAAAA"

    def _fake_ytdlp(self, d, name):
        class Y:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def download(self, urls):
                (d / name).write_bytes(b"downloaded")
        return SimpleNamespace(YoutubeDL=Y)

    def test_download_converts_via_part_file_and_renames(self):
        v = self.v
        d = v.cache_dir(self.SRC)
        (d / "audio.part.m4a").write_bytes(b"stale-half-file")  # 上次被砍留下的
        v.need_ytdlp = lambda: self._fake_ytdlp(d, "audio.webm")
        v.find_ffmpeg = lambda: "ffmpeg"
        seen = []

        def fake_run(cmd, **kw):
            if cmd[-1] == "--version":  # 沒裝 ffmpeg／JS 執行環境的機器（CI）會先探測版本，不是轉檔呼叫
                return SimpleNamespace(returncode=1, stdout="", stderr="")
            out = Path(cmd[-1])
            seen.append(out.name)
            self.assertNotEqual(out.name, "audio.m4a", "不可直接寫最終檔名")
            self.assertEqual(out.suffix, ".m4a", "暫存檔名保留副檔名讓 ffmpeg 認得格式")
            out.write_bytes(b"converted")
            return SimpleNamespace(returncode=0)
        with mock.patch.object(v.subprocess, "run", fake_run):
            got = v.download(self.SRC, "audio")
        self.assertEqual(got.name, "audio.m4a")
        self.assertEqual(got.read_bytes(), b"converted")
        self.assertEqual(seen, ["audio.part.m4a"])
        self.assertFalse((d / "audio.part.m4a").exists())
        self.assertFalse((d / "audio.webm").exists())

    def test_download_failure_leaves_no_final_file(self):
        v = self.v
        d = v.cache_dir(self.SRC)
        v.need_ytdlp = lambda: self._fake_ytdlp(d, "audio.webm")
        v.find_ffmpeg = lambda: "ffmpeg"

        def fake_run(cmd, **kw):
            Path(cmd[-1]).write_bytes(b"half")
            raise subprocess.CalledProcessError(1, cmd)
        with mock.patch.object(v.subprocess, "run", fake_run):
            with self.assertRaises(subprocess.CalledProcessError):
                v.download(self.SRC, "audio")
        self.assertFalse((d / "audio.m4a").exists(), "半截檔不可變成最終檔名")
        self.assertFalse((d / "audio.part.m4a").exists())

    def test_asr_wav_written_via_part_file(self):
        v = self.v
        d = v.cache_dir(self.SRC)
        audio = d / "audio.m4a"
        audio.write_bytes(b"a")
        v.download = lambda src, kind: audio
        v.find_ffmpeg = lambda: "ffmpeg"
        v.have = lambda mod: True

        def fail_run(cmd, **kw):
            out = Path(cmd[-1])
            self.assertEqual(out.name, "audio16k.part.wav")
            out.write_bytes(b"half")
            return SimpleNamespace(returncode=1, stderr="boom")
        with mock.patch.object(v.subprocess, "run", fail_run):
            with self.assertRaises(SystemExit) as cm:
                v._asr(self.SRC, "tiny", None)
        self.assertEqual(cm.exception.code, 3)
        self.assertFalse((d / "audio16k.wav").exists(), "轉檔失敗不留 wav")
        self.assertFalse((d / "audio16k.part.wav").exists())
        self.assertFalse(audio.exists(), "原本就會刪掉可能是壞檔的音訊讓下次重抓（行為不變）")


if __name__ == "__main__":
    unittest.main()
