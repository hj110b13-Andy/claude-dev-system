"""子命令實作：install／update（共用 apply）、uninstall、verify、status。"""
from __future__ import annotations

import datetime as _dt
import py_compile
import shutil
from pathlib import Path

from . import HOOK_MARK, SKILL_MARKER_FILE
from . import claudemd, manifest as mf, payload, settings_ops
from .checks import claude_code_status, parse_ver
from .fsio import atomic_write_bytes, read_json, sha256_bytes, sha256_file, write_json
from .paths import REPO, Layout, repo_version

OK, BAD, WARN = "✅", "❌", "⚠️"


def _ts() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def backup(lay: Layout, log: list) -> dict:
    """備份 settings.json 與 CLAUDE.md 到 <home>/backups/claude-dev-system-<時間>*。"""
    lay.backups.mkdir(parents=True, exist_ok=True)
    base = f"claude-dev-system-{_ts()}"
    n = 0
    while (lay.backups / f"{base}.json").exists() or (lay.backups / f"{base}-CLAUDE.md").exists():
        n += 1
        base = f"claude-dev-system-{_ts()}-{n}"
    rec = {"settings": None, "claudeMd": None, "at": _dt.datetime.now().isoformat(timespec="seconds")}
    if lay.settings.exists():
        dst = lay.backups / f"{base}.json"
        shutil.copy2(lay.settings, dst)
        rec["settings"] = str(dst)
        log.append(f"備份 settings.json → {dst}")
    if lay.claude_md.exists():
        dst = lay.backups / f"{base}-CLAUDE.md"
        shutil.copy2(lay.claude_md, dst)
        rec["claudeMd"] = str(dst)
        log.append(f"備份 CLAUDE.md → {dst}")
    return rec


def _read_settings(lay: Layout) -> tuple:
    if not lay.settings.exists():
        return {}, False
    return read_json(lay.settings), True


def _sync_files(lay: Layout, repo: Path, version: str, old: dict, new: dict, force: bool, log: list) -> None:
    """規則、工具、hook 腳本、設定範本、skills：使用者改過的保留（新版存 .new），非本工具的檔不覆蓋。"""
    home = lay.home
    desired = payload.entries(repo, version)
    conflicts = set()
    for sk in payload.skill_names(repo):
        d = lay.skills / sk
        if d.exists() and not (d / SKILL_MARKER_FILE).exists() and sk not in old.get("skills", []):
            conflicts.add(sk)
            log.append(f"{WARN} skills/{sk} 已存在且不是本工具裝的，略過不覆蓋（改名或移走後重跑 update）")
    extra = []
    for rel, data in desired.items():
        parts = rel.split("/")
        if parts[0] == "skills" and parts[1] in conflicts:
            continue
        p = home / rel
        cur, want, rec = sha256_file(p), sha256_bytes(data), old["files"].get(rel)
        if cur == want:
            new["files"][rel] = want
            continue
        if cur is not None and rec is not None and cur != rec and not force:
            new["files"][rel] = rec  # 保留使用者改動；紀錄維持舊雜湊，verify 標「使用者已修改」
            np = p.with_name(p.name + ".new")
            atomic_write_bytes(np, data)
            extra.append(np.relative_to(home).as_posix())
            log.append(f"{WARN} {rel} 有使用者改動，保留不覆蓋；新版放在 {np.name}（--force 可覆蓋）")
            continue
        if cur is not None and rec is None and not force:
            log.append(f"{WARN} {rel} 已存在且不是本工具寫的，略過（--force 可覆蓋）")
            continue
        atomic_write_bytes(p, data)
        new["files"][rel] = want
        log.append(("更新 " if cur else "新增 ") + rel)
    new["extraFiles"] = sorted(set(old.get("extraFiles", [])) | set(extra))
    for rel, rec in old["files"].items():
        if rel in desired:
            continue
        p = home / rel
        if sha256_file(p) == rec or force:
            p.unlink(missing_ok=True)
            log.append(f"移除舊版檔案 {rel}")
        elif p.exists():
            log.append(f"{WARN} 舊版檔案 {rel} 有使用者改動，保留")
    new["skills"] = [s for s in payload.skill_names(repo) if s not in conflicts]


def _sync_settings(lay: Layout, python: str, old: dict, new: dict, log: list) -> None:
    """先清掉本工具舊條目，再加新條目；其他鍵不碰；沒有變化就不寫檔。"""
    s, existed = _read_settings(lay)
    script = (lay.payload / "hooks" / "usage_guard.py").as_posix()
    cleaned, _ = settings_ops.remove_marked(s, old["settings"].get("createdKeys"))
    s2, rec = settings_ops.add_hooks(cleaned, settings_ops.hook_command(python, script))
    new["settings"] = {**rec, "createdFile": bool(old["settings"].get("createdFile")) or (not existed and bool(s2))}
    for x in rec["hooksSkippedExisting"]:
        log.append(f"{WARN} {x['event']} 已有使用者自己的 usage_guard hook，不重複註冊：{x['command']}")
    if s2 != s:
        write_json(lay.settings, s2)
        log.extend(f"settings.json 新增 hook {h['event']}：{h['command']}" for h in rec["hooksAdded"])
    else:
        log.append("settings.json 無需變更（未寫入）")


def _sync_claude_md(lay: Layout, repo: Path, version: str, old: dict, new: dict, force: bool, log: list) -> None:
    text = lay.claude_md.read_text(encoding="utf-8") if lay.claude_md.exists() else ""
    cur_hash = claudemd.block_hash(text)
    old_md = old.get("claudeMd") or {}
    block = claudemd.make_block(payload.core_rules(repo), version)
    new["claudeMd"] = {"createdFile": bool(old_md.get("createdFile")) or not lay.claude_md.exists(),
                       "sep": old_md.get("sep", "")}
    if cur_hash and old_md.get("blockSha256") and cur_hash != old_md["blockSha256"] and not force:
        np = lay.payload / "CLAUDE-block.new.md"
        atomic_write_bytes(np, block.encode("utf-8"))
        new["extraFiles"] = sorted(set(new["extraFiles"]) | {np.relative_to(lay.home).as_posix()})
        new["claudeMd"]["blockSha256"] = old_md["blockSha256"]
        log.append(f"{WARN} CLAUDE.md 的本工具區塊有使用者改動，保留；新版區塊在 {np}（--force 可覆蓋）")
        return
    t2, sep = claudemd.upsert(text, block)
    if sep is not None:
        new["claudeMd"]["sep"] = sep
    new["claudeMd"]["blockSha256"] = claudemd.block_hash(t2)
    if t2 != text:
        atomic_write_bytes(lay.claude_md, t2.encode("utf-8"))
        log.append(f"CLAUDE.md 寫入標記區塊（{len(block.splitlines())} 行，區塊外未變動）")
    else:
        log.append("CLAUDE.md 區塊已是最新")


def apply(lay: Layout, python: str, repo: Path = REPO, force: bool = False, mode: str = "install") -> tuple:
    log: list = []
    old = mf.load(lay.manifest)
    if mode == "install" and old and old.get("version"):
        return 2, [f"已安裝 v{old['version']}；要更新請用 `update`，要重裝請先 `uninstall`"]
    if mode == "update" and not old:
        return 2, ["尚未安裝（找不到 manifest），請用 `install`"]
    old = old or mf.empty()
    version = repo_version(repo)
    if mode == "update":
        ov, nv = parse_ver(old.get("version") or "0"), parse_ver(version)
        log.append(f"版本 {old.get('version')} → {version}" + ("（相同版本，重新套用）" if ov == nv else ""))
        if nv < ov and not force:
            return 2, log + [f"repo 版本 {version} 比已安裝的 {old['version']} 舊；要降版請加 --force"]
    now = _dt.datetime.now().isoformat(timespec="seconds")
    new = mf.empty()
    new.update({"version": version, "repo": str(repo), "python": python,
                "installedAt": old.get("installedAt") or now, "updatedAt": now,
                "userEditable": list(payload.USER_EDITABLE)})
    new["backups"] = list(old.get("backups", [])) + [backup(lay, log)]
    _sync_files(lay, repo, version, old, new, force, log)
    _sync_settings(lay, python, old, new, log)
    _sync_claude_md(lay, repo, version, old, new, force, log)
    mf.save(lay.manifest, new)
    log.append(f"{OK} {'安裝' if mode == 'install' else '更新'}完成 v{version}；安裝紀錄 {lay.manifest}")
    return 0, log


def uninstall(lay: Layout, force: bool = False, restore_backup: bool = False) -> tuple:
    log: list = []
    m = mf.load(lay.manifest)
    if not m:
        log.append(f"{WARN} 找不到安裝紀錄，只清除帶標記的 hook 與 CLAUDE.md 區塊")
        m = mf.empty()
    backup(lay, log)
    home = lay.home
    if lay.settings.exists():
        s = read_json(lay.settings)
        s2, removed = settings_ops.remove_marked(s, m["settings"].get("createdKeys"))
        if removed:
            first = next((b for b in m.get("backups", []) if b.get("settings")), None)
            if m["settings"].get("createdFile") and s2 == {}:
                lay.settings.unlink()
                log.append("刪除本工具建立的 settings.json（已無其他內容）")
            elif first and Path(first["settings"]).exists() and read_json(Path(first["settings"])) == s2:
                shutil.copy2(first["settings"], lay.settings)  # 逐鍵相等時還原原檔位元組，連排版都不變
                log.append("移除後內容與安裝前備份逐鍵相等，已還原原檔（含原排版）")
            else:
                write_json(lay.settings, s2)
            log.extend(f"移除 hook {r}" for r in removed)
        else:
            log.append("settings.json 沒有本工具的條目（未寫入）")
    if lay.claude_md.exists():
        md = m.get("claudeMd") or {}
        t = lay.claude_md.read_text(encoding="utf-8")
        t2 = claudemd.remove(t, md.get("sep", ""))
        if t2 != t:
            if md.get("createdFile") and t2 == "":
                lay.claude_md.unlink()
                log.append("刪除本工具建立的 CLAUDE.md（已無其他內容）")
            else:
                atomic_write_bytes(lay.claude_md, t2.encode("utf-8"))
                log.append("移除 CLAUDE.md 標記區塊（區塊外未變動）")
    deleted = 0
    for rel, h in m.get("files", {}).items():
        p = home / rel
        cur = sha256_file(p)
        if cur is None:
            continue
        if cur == h or force:
            p.unlink()
            deleted += 1
        else:
            log.append(f"{WARN} 保留 {rel}（使用者改過；--force 可刪）")
    log.append(f"刪除本工具檔案 {deleted} 個")
    for rel in m.get("extraFiles", []):
        p = home / rel
        if p.exists():
            p.unlink()
            log.append(f"刪除 {rel}")
    if lay.payload.exists():
        for cache in list(lay.payload.rglob("__pycache__")):
            shutil.rmtree(cache, ignore_errors=True)
    lay.manifest.unlink(missing_ok=True)
    dirs = [lay.skills / s for s in m.get("skills", [])] + [lay.payload]
    for d in dirs:
        if not d.exists():
            continue
        for sub in sorted((x for x in d.rglob("*") if x.is_dir()), key=lambda x: -len(x.parts)):
            if not any(sub.iterdir()):
                sub.rmdir()
        if not any(d.iterdir()):
            d.rmdir()
            log.append(f"移除資料夾 {d}")
        else:
            log.append(f"{WARN} 保留 {d}（內有非本工具的檔案）")
    if restore_backup:
        first = next((b for b in m.get("backups", []) if b.get("settings")), None)
        if first and Path(first["settings"]).exists():
            shutil.copy2(first["settings"], lay.settings)
            log.append(f"已用安裝前備份還原 settings.json：{first['settings']}")
        else:
            log.append(f"{WARN} 沒有可用的安裝前 settings 備份")
    log.append(f"{OK} 解除安裝完成")
    return 0, log


def verify(lay: Layout, repo: Path | None = REPO, check_claude: bool = True) -> tuple:
    rows: list = []
    m = mf.load(lay.manifest)
    if not m:
        return 1, [f"{BAD} 找不到安裝紀錄 {lay.manifest}（尚未安裝）"]
    rows.append((OK, f"安裝紀錄 v{m['version']}（schema {m['schemaVersion']}）"))
    vf = lay.payload / "config" / "VERSION"
    inst_ver = vf.read_text(encoding="utf-8").strip() if vf.exists() else None
    rows.append((OK if inst_ver == m["version"] else BAD, f"已安裝檔案版本 {inst_ver}，紀錄 {m['version']}"))
    if repo is not None:
        rv = repo_version(repo)
        rows.append((OK if rv == m["version"] else WARN, f"repo 版本 {rv}" + ("" if rv == m["version"] else "（與已安裝不同，可執行 update）")))
    bad, edited = [], []
    editable = m.get("userEditable", [])
    for rel, h in m["files"].items():
        cur = sha256_file(lay.home / rel)
        if cur is None:
            bad.append(f"缺 {rel}")
        elif cur != h:
            (edited if rel in editable else bad).append(rel)
    if repo is not None and repo_version(repo) == m["version"]:
        desired = payload.entries(repo, m["version"])
        bad += [f"與 repo 不一致 {r}" for r, d in desired.items()
                if r in m["files"] and r not in editable and m["files"][r] != sha256_bytes(d)]
    n = len(m["files"])
    rows.append((OK if not bad else BAD, f"檔案雜湊 {n - len([b for b in bad if not b.startswith('與 repo')])}/{n} 一致"
                 + ("" if not bad else "：" + "；".join(bad[:8]))))
    rows.extend((WARN, f"{e} 已被使用者修改（允許，update 會保留）") for e in edited)
    s = read_json(lay.settings) if lay.settings.exists() else {}
    script = (lay.payload / "hooks" / "usage_guard.py").as_posix()
    for event, _ in settings_ops.HOOK_SPECS:
        marked = settings_ops.has_marked(s, event)
        skipped = any(x["event"] == event for x in m["settings"].get("hooksSkippedExisting", []))
        if marked:
            good = len(marked) == 1 and script in marked[0]
            rows.append((OK if good else BAD, f"{event} hook（本工具）" + ("存在、指向已安裝腳本" if good else f"異常：{marked}")))
        elif skipped and settings_ops.find_unmarked_equivalent(s, event):
            rows.append((OK, f"{event} hook：使用者既有的 usage_guard 條目在作用（本工具未重複註冊）"))
        else:
            rows.append((BAD, f"{event} hook 不存在"))
    try:
        cfile = lay.payload / "_verify.pyc"
        py_compile.compile(str(lay.payload / "hooks" / "usage_guard.py"), cfile=str(cfile), doraise=True)
        cfile.unlink(missing_ok=True)
        rows.append((OK, "usage_guard.py 可編譯"))
    except Exception as e:  # noqa: BLE001
        rows.append((BAD, f"usage_guard.py 無法編譯：{e}"))
    text = lay.claude_md.read_text(encoding="utf-8") if lay.claude_md.exists() else ""
    try:
        bh = claudemd.block_hash(text)
    except ValueError as e:
        bh = None
        rows.append((BAD, str(e)))
    if bh is None:
        rows.append((BAD, "CLAUDE.md 標記區塊不存在"))
    else:
        same = bh == m["claudeMd"]["blockSha256"]
        rows.append((OK if same else WARN, "CLAUDE.md 標記區塊存在" + ("、內容與紀錄一致" if same else "（使用者改過）")))
    for sk in m.get("skills", []):
        f = lay.skills / sk / "SKILL.md"
        good = f.exists() and f"name: {sk}" in f.read_text(encoding="utf-8")
        rows.append((OK if good else BAD, f"skill {sk}" + ("" if good else " 缺檔或 frontmatter name 不符")))
    if check_claude:
        ok, msg = claude_code_status(repo or REPO)
        rows.append((OK if ok else (WARN if ok is None else BAD), msg))
    code = 1 if any(r[0] == BAD for r in rows) else 0
    return code, [f"{a} {b}" for a, b in rows] + ["全部通過" if code == 0 else "有項目未通過"]


def status(lay: Layout, repo: Path = REPO) -> tuple:
    m = mf.load(lay.manifest)
    rv = repo_version(repo)
    if not m:
        return 0, [f"未安裝；repo 版本 {rv}；設定目錄 {lay.home}"]
    s = read_json(lay.settings) if lay.settings.exists() else {}
    marked = sum(len(settings_ops.has_marked(s, e)) for e, _ in settings_ops.HOOK_SPECS)
    upd = "（repo 較新，可 update）" if parse_ver(rv) > parse_ver(m["version"]) else ""
    last = (m.get("backups") or [{}])[-1]
    return 0, [
        f"已安裝 v{m['version']}；repo v{rv}{upd}",
        f"安裝於 {m.get('installedAt')}，最後更新 {m.get('updatedAt')}；來源 {m.get('repo')}",
        f"檔案 {len(m['files'])} 個；skills：{', '.join(m.get('skills', []))}",
        f"本工具 hook 條目 {marked} 條；沿用使用者既有 hook {len(m['settings'].get('hooksSkippedExisting', []))} 條（標記 {HOOK_MARK}）",
        f"備份 {len(m.get('backups', []))} 次，最近：{last.get('settings')}",
    ]
