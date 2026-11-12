"""子命令實作：install／update（共用 apply）、uninstall、verify、status。"""
from __future__ import annotations

import copy
import datetime as _dt
import functools
import shutil
import sys
from pathlib import Path

from . import HOOK_MARK, SKILL_MARKER_FILE
from . import claudemd, manifest as mf, payload, settings_ops, video, web
from .checks import claude_code_status, parse_ver, settings_error
from .fsio import LockBusy, acquire_lock, atomic_write_bytes, read_json, release_lock, sha256_bytes, sha256_file, write_json
from .paths import REPO, Layout, repo_version

OK, BAD, WARN = "✅", "❌", "⚠️"


LOCK_NAME = ".install.lock"  # <home>/claude-dev-system/.install.lock；不進 manifest 的 files


def _locked(fn):
    """IN-06：同一個設定目錄同時只跑一個會寫入的子命令（apply／web_config／video_config／uninstall）。
    用作業系統層級的檔案鎖：程序結束或被殺時系統自動釋放，沒有「殘留鎖要等逾時」的問題。拿不到鎖回 (2, [一行說明])。
    沒有安裝紀錄（還沒裝、或剛解除安裝）時，結束後把鎖檔與空的 claude-dev-system 資料夾一起清掉，不留痕跡。"""
    @functools.wraps(fn)
    def wrapper(lay: Layout, *args, **kwargs):
        lock = lay.payload / LOCK_NAME
        try:
            fd = acquire_lock(lock)
        except LockBusy:
            return 2, [f"另一個安裝程序正在執行（設定目錄 {lay.home}）；等它結束再重跑"]
        try:
            return fn(lay, *args, **kwargs)
        finally:
            release_lock(fd)
            if not lay.manifest.exists():
                for clean in (lock.unlink, lay.payload.rmdir):  # rmdir 只刪空資料夾；別的程序剛好又打開鎖檔時刪不掉，略過
                    try:
                        clean()
                    except OSError:
                        pass
    return wrapper


def _ver(s) -> tuple:
    """版本比較用的唯一來源：解析不出來（None、"0"、亂寫）一律當 (0, 0, 0)，不讓比較丟 TypeError（IN-12）。"""
    return parse_ver(str(s or "")) or (0, 0, 0)


def _ts() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def backup(lay: Layout, log: list, pre_install: bool = False) -> dict:
    """備份 settings.json 與 CLAUDE.md 到 <home>/backups/claude-dev-system-<時間>*。
    pre_install：第一次 install 那筆（安裝前的原狀）記 "preInstall": true——安裝前沒有 settings.json 時 settings 為 None 也照記，
    `--restore-backup` 才知道「安裝前根本沒有這個檔」，不會拿安裝後的備份來還原（2026-11-12 健檢 main 實跑確認）。"""
    lay.backups.mkdir(parents=True, exist_ok=True)
    base = f"claude-dev-system-{_ts()}"
    n = 0
    while (lay.backups / f"{base}.json").exists() or (lay.backups / f"{base}-CLAUDE.md").exists():
        n += 1
        base = f"claude-dev-system-{_ts()}-{n}"
    rec = {"settings": None, "claudeMd": None, "at": _dt.datetime.now().isoformat(timespec="seconds")}
    if pre_install:
        rec["preInstall"] = True  # 選用鍵（不升 MANIFEST_SCHEMA：舊版 exe 讀到較新的 schema 會直接丟錯；舊程式會忽略這個鍵）
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


KEEP_BACKUPS = 10
LEGACY_PRE_INSTALL_WINDOW = 120  # 秒；0.27.0 前的紀錄沒有 preInstall 旗標，第一筆的時間在 installedAt 之後這麼久以內才當成安裝前那筆（自己加的門檻：install 時兩個時間只差 0～1 秒）


def _pre_install_index(items: list, installed_at) -> int | None:
    """唯一來源：backups 清單裡「安裝前」那筆的索引。有 preInstall 旗標的優先；整份都沒有旗標（0.27.0 前的舊紀錄）時，
    只有第一筆的 at 在 installedAt 之後 LEGACY_PRE_INSTALL_WINDOW 秒內才算（update 超過 KEEP_BACKUPS 次後第一筆早被修剪，那時就回 None）。"""
    for i, b in enumerate(items):
        if isinstance(b, dict) and b.get("preInstall"):
            return i
    if not items or not isinstance(items[0], dict) or not installed_at:
        return None
    try:
        delta = (_dt.datetime.fromisoformat(str(items[0].get("at"))) - _dt.datetime.fromisoformat(str(installed_at))).total_seconds()
    except (TypeError, ValueError):
        return None
    return 0 if 0 <= delta <= LEGACY_PRE_INSTALL_WINDOW else None


def pre_install_backup(m: dict) -> dict | None:
    """安裝前那筆備份紀錄（找不到回 None）。uninstall 的「還原原排版」與 `--restore-backup` 都只用這個函式。"""
    items = list((m or {}).get("backups") or [])
    i = _pre_install_index(items, (m or {}).get("installedAt"))
    return None if i is None else items[i]


def _prune_backups(items: list, log: list, installed_at=None) -> list:
    """每次 apply／web 都備份；安裝前那筆永遠保留，其他只留最近 KEEP_BACKUPS-1 份，舊的連檔案一起刪（原本無限增長）。"""
    pre = _pre_install_index(items, installed_at)
    rest = [b for i, b in enumerate(items) if i != pre]
    n_rest = KEEP_BACKUPS - 1 if pre is not None else KEEP_BACKUPS
    keep_rest, drop = rest[-n_rest:], rest[:-n_rest]
    for b in drop:
        for k in ("settings", "claudeMd"):
            if isinstance(b, dict) and b.get(k):
                Path(b[k]).unlink(missing_ok=True)
    if drop:
        log.append(f"清掉 {len(drop)} 份較舊的備份（只留安裝前那份＋最近 {n_rest} 份）")
    return ([items[pre]] if pre is not None else []) + keep_rest


def _md_text(p: Path) -> str:
    """讀 CLAUDE.md 原文、不轉換換行。使用者的檔是 CRLF 就維持 CRLF，區塊外才真的一字不動。
    IN-09：原本整檔先轉 LF、寫回時整檔換成同一種換行，混合換行的檔區塊外位元組會變；現在只換區塊本身（claudemd.upsert／remove），
    雜湊在 claudemd.block_hash 裡以 LF 正規化（與舊紀錄相容）。"""
    if not p.exists():
        return ""
    return p.read_bytes().decode("utf-8")


def _preflight(lay: Layout, web_on: bool = False) -> None:
    """IN-04：任何備份與寫入之前先確認讀得懂使用者的檔，否則丟一行「檔名＋原因＋怎麼修」的 ValueError（install.py 印成 ❌、結束碼 2）。
    原本是寫到一半才丟錯：payload 27 個檔與 7 條 hook 已寫、manifest 沒存，修好重裝後 createdKeys 變空，解除安裝留下空的 hooks 鍵。"""
    err = settings_error(lay.settings)
    if err:
        raise ValueError(err)
    if lay.claude_md.exists():
        try:
            t = lay.claude_md.read_bytes().decode("utf-8")
        except UnicodeDecodeError as e:
            raise ValueError(f"{lay.claude_md} 不是 UTF-8 編碼（位置 {e.start}；例如用 Big5／cp950 存的）：請用編輯器另存成 UTF-8 後重跑") from None
        try:
            claudemd.find_block(t)
        except ValueError as e:
            raise ValueError(f"{lay.claude_md}：{e}") from None
    if web_on:
        web.load_local(lay)  # local.json 壞掉時這裡就丟（訊息已含檔名），不要等到檔案寫了一半


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
    old_extra = set(old.get("extraFiles", []))

    def clear_new(rel: str) -> None:
        """IN-11：這個檔已和新版一致（使用者改回來、或被 --force 覆蓋）時，之前留的 <rel>.new 已沒用，刪掉並從 extraFiles 拿掉。"""
        nrel = rel + ".new"
        if nrel in old_extra and (home / nrel).exists():
            (home / nrel).unlink()
            log.append(f"移除已不需要的 {nrel}（{rel} 已與新版一致）")

    for rel, data in desired.items():
        parts = rel.split("/")
        if parts[0] == "skills" and parts[1] in conflicts:
            continue
        p = home / rel
        cur, want, rec = sha256_file(p), sha256_bytes(data), old["files"].get(rel)
        if cur == want:
            new["files"][rel] = want
            clear_new(rel)
            continue
        if cur is not None and rec is not None and cur != rec and not force:
            new["files"][rel] = rec  # 保留使用者改動；紀錄維持舊雜湊，verify 標「使用者已修改」
            np = p.with_name(p.name + ".new")
            if rel in payload.USER_EDITABLE:  # 本來就給使用者改的設定檔（門檻、巡檢由視窗管理）：保留，不生 .new；新版多出的頂層鍵補進去
                added = _merge_new_keys(p, data)
                log.append(f"保留使用者設定 {rel}" + (f"（補上新版新增的 {', '.join(added)}）" if added else ""))
                continue
            atomic_write_bytes(np, data)
            extra.append(np.relative_to(home).as_posix())
            log.append(f"{WARN} {rel} 有使用者改動，保留不覆蓋；新版放在 {np.name}（--force 可覆蓋）")
            continue
        if cur is not None and rec is None and not force:
            log.append(f"{WARN} {rel} 已存在且不是本工具寫的，略過（--force 可覆蓋）")
            continue
        atomic_write_bytes(p, data)
        new["files"][rel] = want
        clear_new(rel)
        log.append(("更新 " if cur else "新增 ") + rel)
    stale = {f"{r}.new" for r in payload.USER_EDITABLE}  # 0.9.6 前每次 update 都會生的 dispatch-config.json.new：清掉
    for rel in stale:
        if (home / rel).exists():
            (home / rel).unlink()
            log.append(f"移除多餘的 {rel}（設定檔本來就可改，不需新版副本）")
    new["extraFiles"] = sorted(x for x in (old_extra | set(extra)) - stale if (home / x).exists())  # 已不存在的（清掉的、使用者自己刪的）不再登記
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


def _merge_new_keys(user_file: Path, new_bytes: bytes) -> list[str]:
    """使用者改過的 JSON 設定檔：新版多出的頂層鍵（例如 0.8 加的 taskCheck）補進去，已有的鍵一律不動。兩邊任一不是 JSON 物件就不做。"""
    import json
    try:
        cur, new = read_json(user_file), json.loads(new_bytes.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(cur, dict) or not isinstance(new, dict):
        return []
    added = [k for k in new if k not in cur]
    if added:
        for k in added:
            cur[k] = new[k]
        write_json(user_file, cur)
    return added


def usage_guard_enabled(lay: Layout) -> bool:
    """本機偏好 local.json 的 usageGuard（預設 true）。關掉＝不註冊 hook、verify 不視為錯。"""
    try:
        return bool(web.load_local(lay).get("usageGuard", True))
    except ValueError:
        return True


def _sync_settings(lay: Layout, python: str, old: dict, new: dict, log: list) -> None:
    """先清掉本工具舊條目，再加新條目；其他鍵不碰；沒有變化就不寫檔。"""
    s, existed = _read_settings(lay)
    script = (lay.payload / "hooks" / "usage_guard.py").as_posix()
    cleaned, _ = settings_ops.remove_marked(s, old["settings"].get("createdKeys"))
    if not usage_guard_enabled(lay):  # 使用者在 local.json 關掉用量守門：只清不加
        s2, rec = cleaned, {"hooksAdded": [], "hooksSkippedExisting": [], "createdKeys": []}
        log.append("用量守門 hook：已依本機偏好關閉（local.json usageGuard=false），不註冊")
    else:
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
    text = _md_text(lay.claude_md)
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
    stale = (lay.payload / "CLAUDE-block.new.md").relative_to(lay.home).as_posix()
    if stale in new.get("extraFiles", []):  # IN-11：區塊衝突已解除（使用者改回、或 --force），上次留的新版區塊副本沒用了
        (lay.home / stale).unlink(missing_ok=True)
        new["extraFiles"] = [x for x in new["extraFiles"] if x != stale]
        log.append(f"移除已不需要的 {stale}")
    if t2 != text:
        atomic_write_bytes(lay.claude_md, t2.encode("utf-8"))
        log.append(f"CLAUDE.md 寫入標記區塊（{len(block.splitlines())} 行，區塊外未變動）")
    else:
        log.append("CLAUDE.md 區塊已是最新")


def _sync_web(lay: Layout, old: dict, new: dict, enable: bool, runner, log: list) -> None:
    """聯網來源（選用）：enable 時對齊 MCP 與 env；關閉時移除本工具加過的；都只動自己登記過的項目。"""
    old_web = {**web.empty_record(), **(old.get("web") or {})}
    if not enable:
        failed: list = []
        if old_web["mcpAdded"] or old_web["envCreatedKeys"]:
            failed = web.remove_mcp(lay, old_web, runner, log)
            s, _ = _read_settings(lay)
            s2, removed = web.remove_env(s, old_web["envCreatedKeys"])
            if s2 != s:
                write_json(lay.settings, s2)
                log.extend(f"settings.json 移除 env {k}" for k in removed)
        new["web"] = {**web.empty_record(), "mcpAdded": failed}  # 移不掉的留著登記（IN-02／IN-03 同根因），重跑 `web --off` 會接著移除
        return
    rec = web.sync_mcp(lay, old_web, runner, log)
    s, _ = _read_settings(lay)
    s2, created, skipped = web.apply_env(s, web.desired_env(web.sources(lay), web.load_local(lay)), old_web["envCreatedKeys"])
    for k in skipped:
        log.append(f"{WARN} settings.json 的 env 不是物件，略過 env 寫入" if k == "env" else f"{WARN} env {k} 為使用者自行設定，不覆蓋")
    if s2 != s:
        write_json(lay.settings, s2)
        before = s.get("env") if isinstance(s.get("env"), dict) else {}
        log.extend(f"settings.json 寫入 env {k[4:]}={s2['env'][k[4:]]}" for k in created
                   if k.startswith("env.") and before.get(k[4:]) != s2["env"][k[4:]])
        log.extend(f"settings.json 移除不再需要的 env {k}" for k in before if k not in (s2.get("env") or {}))
    new["web"] = {"enabled": True, "mcpAdded": rec["mcpAdded"], "envCreatedKeys": created, "skipped": rec["skipped"]}


@_locked
def apply(lay: Layout, python: str, repo: Path = REPO, force: bool = False, mode: str = "install",
          with_web: bool | None = None, runner=web.default_runner, with_video: bool | None = None, pip=video.default_pip) -> tuple:
    """with_web／with_video：True 開啟、False 關閉、None 沿用已安裝的狀態。"""
    log: list = []
    old = mf.load(lay.manifest)
    if mode == "install" and old and old.get("version"):
        return 2, [f"已安裝 v{old['version']}；要更新請用 `update`，要重裝請先 `uninstall`"]
    if mode == "update" and not old:
        return 2, ["尚未安裝（找不到 manifest），請用 `install`"]
    old = old or mf.empty()
    version = repo_version(repo)
    if mode == "update":
        ov, nv = _ver(old.get("version")), _ver(version)
        log.append(f"版本 {old.get('version')} → {version}" + ("（相同版本，重新套用）" if ov == nv else ""))
        if nv < ov and not force:
            return 2, log + [f"repo 版本 {version} 比已安裝的 {old['version']} 舊；要降版請加 --force"]
    enable = bool((old.get("web") or {}).get("enabled")) if with_web is None else with_web
    _preflight(lay, web_on=enable)
    now = _dt.datetime.now().isoformat(timespec="seconds")
    new = mf.empty()
    new.update({"version": version, "repo": str(repo), "python": python,
                "installedAt": old.get("installedAt") or now, "updatedAt": now,
                "userEditable": list(payload.USER_EDITABLE)})
    new["backups"] = _prune_backups(list(old.get("backups", [])) + [backup(lay, log, pre_install=mode == "install")], log, new["installedAt"])
    _sync_files(lay, repo, version, old, new, force, log)
    _sync_settings(lay, python, old, new, log)
    _sync_claude_md(lay, repo, version, old, new, force, log)
    _sync_web(lay, old, new, enable, runner, log)
    v_enable = bool((old.get("video") or {}).get("enabled")) if with_video is None else with_video
    new["video"] = video.sync(lay, python, v_enable, pip, log)
    mf.save(lay.manifest, new)
    failed = any(x.startswith(BAD) for x in log)
    log.append(f"{BAD if failed else OK} {'安裝' if mode == 'install' else '更新'}{'完成但有項目失敗（見上方 ❌）' if failed else '完成'} v{version}；安裝紀錄 {lay.manifest}")
    return (1 if failed else 0), log


@_locked
def web_config(lay: Layout, keys=(), enable=(), disable=(), env=(), off: bool = False, show: bool = False,
               runner=web.default_runner, key_mode=(), usage_guard: str | None = None) -> tuple:
    """`install.py web`：改本機偏好（local.json）後立即套用；--off 關閉並移除；--show 只顯示。"""
    m = mf.load(lay.manifest)
    if not m:
        return 2, ["尚未安裝（找不到 manifest），請先 `install`"]
    log: list = []
    try:
        local = web.load_local(lay)
    except ValueError as e:
        return 2, [str(e)]
    names = set((web.sources(lay).get("mcpServers") or {}).keys())
    bad = [n for n in (*enable, *disable) if n not in names]
    if bad:
        return 2, [f"不認識的 MCP 名稱：{', '.join(bad)}；可用：{', '.join(sorted(names))}"]
    try:
        for kv in keys:
            web.set_key_arg(local, kv)
        for kv in env:
            web.set_env_arg(local, kv)
        for kv in key_mode:
            web.set_key_mode_arg(local, kv)
        if usage_guard is not None:
            if usage_guard not in ("on", "off"):
                raise ValueError("--usage-guard 只能是 on 或 off")
            local["usageGuard"] = usage_guard == "on"
    except ValueError as e:
        return 2, [str(e)]
    for n in enable:
        local["enable"] = sorted(set(local.get("enable", [])) | {n})
        local["disable"] = [x for x in local.get("disable", []) if x != n]
    for n in disable:
        local["disable"] = sorted(set(local.get("disable", [])) | {n})
        local["enable"] = [x for x in local.get("enable", []) if x != n]
    # IN-01：聯網來源原本沒啟用時，只帶 --key／--env／--key-mode／--usage-guard 是「存偏好」，不可順便註冊 6 個 MCP、改 env
    # （docs/video.md 教使用者用 `web --key youtube=…` 存影片金鑰）。不帶任何參數、--enable／--disable、--off、或已啟用時照舊同步。
    prefs_only = (not m["web"].get("enabled") and not off and not enable and not disable
                  and bool(keys or env or key_mode or usage_guard is not None))
    if not show and (not prefs_only or usage_guard is not None):
        try:
            _preflight(lay)  # IN-04：接下來會寫 settings.json
        except ValueError as e:
            return 2, [str(e)]
    if keys or env or enable or disable or key_mode or usage_guard is not None:
        web.save_local(lay, local)
        log.append(f"本機偏好已寫入 {web.local_path(lay)}（不進 repo、update／uninstall 不動）")
    if show:
        want = web.desired_servers(web.sources(lay), local)
        head = "將啟用的 MCP：" if m["web"].get("enabled") else "啟用後將註冊的 MCP（目前未啟用；`install.py web` 或 `update --with-web` 可開）："
        log.append(head + (", ".join(f"{n} → {web.mask(v['url'], local)}" for n, v in want.items()) or "無"))
        log.append("env：" + ", ".join(f"{k}={v}" for k, v in web.desired_env(web.sources(lay), local).items()))
        log.append("本機金鑰：" + (", ".join(sorted(k for k, v in (local.get('keys') or {}).items() if v)) or "無"))
        keyed = sorted(n for n in want if n.endswith("-key"))
        always = sorted(n for n, v in (local.get("keyMode") or {}).items() if v == "always")
        log.append("金鑰模式：免費優先（免金鑰版＋-key 版並存）" + (f"：{', '.join(k[:-4] for k in keyed)}" if keyed else "：無")
                   + ("；一律用金鑰：" + ", ".join(always) if always else ""))
        log.append(f"目前狀態：{'已啟用' if m['web'].get('enabled') else '未啟用'}；已註冊 {', '.join(m['web'].get('mcpAdded', [])) or '無'}")
        return 0, log
    new = copy.deepcopy(m)
    new["backups"] = _prune_backups(list(m.get("backups", [])) + [backup(lay, log)], log, m.get("installedAt"))  # 原本只增不減
    if usage_guard is not None:  # 用量守門開關立刻反映到 settings.json（原本要再跑 update，期間 verify 7 條 ❌）
        _sync_settings(lay, m.get("python") or Path(sys.executable).as_posix(), m, new, log)
    if not prefs_only:
        _sync_web(lay, m, new, not off, runner, log)
    new["updatedAt"] = _dt.datetime.now().isoformat(timespec="seconds")
    mf.save(lay.manifest, new)
    if prefs_only:
        log.append("聯網來源未啟用（`install.py web` 或 `update --with-web` 可開）；這次只存本機偏好，沒有註冊 MCP、沒有改 env")
        log.append(f"{OK} 本機偏好已儲存")
    else:
        log.append(f"{OK} 聯網來源{'已關閉並移除' if off else '已套用'}；重開 Claude Code 對話後生效（`/mcp` 可看連線狀態）")
    return (1 if any(x.startswith(BAD) for x in log) else 0), log


@_locked
def video_config(lay: Layout, python: str, off: bool = False, show: bool = False, pip=video.default_pip,
                 importer=video.default_importer, ffmpeg=video.ffmpeg_path) -> tuple:
    """`install.py video`：啟用（pip 安裝套件並登記）／--off 取消登記／--show 只檢查。"""
    m = mf.load(lay.manifest)
    if not m:
        return 2, ["尚未安裝（找不到 manifest），請先 `install`"]
    log: list = []
    try:
        keys = (web.load_local(lay).get("keys") or {})
    except ValueError as e:
        return 2, [str(e)]
    if show:
        rows = video.verify_rows(lay, m.get("video") or video.empty_record(), importer, keys, ffmpeg)
        if not (m.get("video") or {}).get("enabled"):
            rows += video.verify_rows(lay, {"enabled": True}, importer, keys, ffmpeg)
        return 0, [f"{a} {b}" for a, b in rows]
    new = copy.deepcopy(m)
    new["video"] = video.sync(lay, python, not off, pip, log)
    new["updatedAt"] = _dt.datetime.now().isoformat(timespec="seconds")
    mf.save(lay.manifest, new)
    if off:
        log.append(f"{WARN} 已取消登記影片來源；pip 套件未移除（可能被其他程式使用），要刪請自行 `{python} -m pip uninstall yt-dlp youtube-transcript-api`")
    failed = any(x.startswith(BAD) for x in log)
    log.append(f"{BAD if failed else OK} 影片來源{'已關閉' if off else ('安裝有誤（見上方 ❌）' if failed else '已啟用；`py -3 ~/.claude/claude-dev-system/tools/video.py setup` 可檢查')}")
    return (1 if failed else 0), log


def _json_equals(p: Path, obj) -> bool:
    try:
        return p.exists() and read_json(p) == obj
    except (OSError, ValueError):
        return False


def _restore_pre_install(lay: Layout, m: dict, log: list) -> None:
    """`--restore-backup`：只用安裝前那筆（pre_install_backup）。找不到、安裝前沒有 settings.json、或備份檔已不在 → 不還原，
    保留已移除本工具條目的 settings.json。備份裡若有本工具標記的 hook（例如重裝前沒解乾淨）先清掉再寫；沒有就原檔位元組複製（保留排版）。"""
    keep = "保留目前已移除本工具條目的 settings.json"
    pre = pre_install_backup(m)
    if pre is None:
        log.append(f"{WARN} 找不到安裝前的 settings 備份紀錄（0.27.0 前安裝且 update 超過 {KEEP_BACKUPS} 次時已被修剪），不還原；{keep}")
        return
    if not pre.get("settings"):
        log.append(f"{WARN} 安裝前沒有 settings.json（{pre.get('at')} 的安裝前備份紀錄為空），不還原；{keep}")
        return
    src = Path(pre["settings"])
    if not src.exists():
        log.append(f"{WARN} 安裝前備份檔已不在：{src}，不還原；{keep}")
        return
    try:
        data = read_json(src)
    except (OSError, ValueError) as e:
        log.append(f"{WARN} 安裝前備份檔讀不了：{src}（{e}），不還原；{keep}")
        return
    cleaned, removed = settings_ops.remove_marked(data) if isinstance(data, dict) else (data, [])
    if removed:
        write_json(lay.settings, cleaned)
        log.append(f"已用安裝前備份還原 settings.json：{src}（備份裡有 {len(removed)} 條本工具 hook，已清掉）")
    else:
        shutil.copy2(src, lay.settings)
        log.append(f"已用安裝前備份還原 settings.json：{src}")


@_locked
def uninstall(lay: Layout, force: bool = False, restore_backup: bool = False, runner=web.default_runner) -> tuple:
    log: list = []
    m = mf.load(lay.manifest)
    if not m:
        log.append(f"{WARN} 找不到安裝紀錄，只清除帶標記的 hook 與 CLAUDE.md 區塊")
        m = mf.empty()
    _preflight(lay)  # IN-04：settings.json 或 CLAUDE.md 讀不懂時，MCP、hook 一個都還沒動就停（原本移到一半才丟錯）
    backup(lay, log)
    home = lay.home
    mcp_failed = web.remove_mcp(lay, m.get("web") or {}, runner, log)
    if lay.settings.exists():
        s = read_json(lay.settings)
        s2, removed = settings_ops.remove_marked(s, m["settings"].get("createdKeys"))
        s2, env_removed = web.remove_env(s2, (m.get("web") or {}).get("envCreatedKeys"))
        removed += [f"env {k}" for k in env_removed]
        if removed:
            first = pre_install_backup(m)
            if m["settings"].get("createdFile") and s2 == {}:
                lay.settings.unlink()
                log.append("刪除本工具建立的 settings.json（已無其他內容）")
            elif first and first.get("settings") and _json_equals(Path(first["settings"]), s2):
                shutil.copy2(first["settings"], lay.settings)  # 逐鍵相等時還原原檔位元組，連排版都不變
                log.append("移除後內容與安裝前備份逐鍵相等，已還原原檔（含原排版）")
            else:
                write_json(lay.settings, s2)
            log.extend(f"移除 {'' if r.startswith('env ') else 'hook '}{r}" for r in removed)
        else:
            log.append("settings.json 沒有本工具的條目（未寫入）")
    if web.local_path(lay).exists():
        log.append(f"{WARN} 保留本機偏好 {web.local_path(lay)}（含你的金鑰；不需要請自行刪除）")
    if lay.claude_md.exists():
        md = m.get("claudeMd") or {}
        t = _md_text(lay.claude_md)
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
    rep = home / "state" / "selftest-reports"
    if rep.exists():
        shutil.rmtree(rep, ignore_errors=True)
        log.append("刪除 state/selftest-reports")
    if mcp_failed:  # IN-02：MCP 移不掉時不刪紀錄，只留這些名稱；重跑 uninstall 會接著移除（重裝也會認得它們是本工具的）
        rest = mf.empty()
        rest["web"]["mcpAdded"] = sorted(mcp_failed)
        mf.save(lay.manifest, rest)
        log.append(f"{WARN} 安裝紀錄只保留移除失敗的 MCP：{', '.join(sorted(mcp_failed))}（修好後重跑 `uninstall`）")
    else:
        lay.manifest.unlink(missing_ok=True)
    dirs = [lay.skills / s for s in m.get("skills", [])] + [lay.payload]
    for d in dirs:
        if not d.exists():
            continue
        for sub in sorted((x for x in d.rglob("*") if x.is_dir()), key=lambda x: -len(x.parts)):
            if not any(sub.iterdir()):
                sub.rmdir()
        if not any(x for x in d.iterdir() if x.name != LOCK_NAME or d != lay.payload):
            if not (d / LOCK_NAME).exists() or d != lay.payload:  # 只剩鎖檔：鎖放掉後由 _locked 刪鎖檔與這個資料夾
                d.rmdir()
            log.append(f"移除資料夾 {d}")
        else:
            log.append(f"{WARN} 保留 {d}（內有非本工具的檔案）")
    if restore_backup:
        _restore_pre_install(lay, m, log)
    failed = any(x.startswith(BAD) for x in log)  # IN-02：比照 apply，有 ❌ 就回 1、最後一行 ❌
    log.append(f"{BAD} 解除安裝完成但有項目失敗（見上方 ❌）" if failed else f"{OK} 解除安裝完成")
    return (1 if failed else 0), log


def _python_row(py) -> tuple:
    """IN-08：hook 用的 Python 還在不在（venv 或 Python 被移除後 7 個 hook 每次都失敗，原本 verify 仍全 ✅）。"""
    if not py:
        return BAD, "hook 用的 Python：安裝紀錄沒有記錄（重跑 `install.py update`）"
    p = Path(str(py))
    found = p.exists() if p.is_absolute() else bool(shutil.which(str(py)))
    return (OK, f"hook 用的 Python 存在：{py}") if found else (
        BAD, f"hook 用的 Python 不存在：{py}（用現在的 Python 重跑 `install.py update`，或加 `--python 路徑`）")


def verify(lay: Layout, repo: Path | None = REPO, check_claude: bool = True, importer=video.default_importer,
           ffmpeg=video.ffmpeg_path) -> tuple:
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
    # IN-15：editable 來自 manifest 的 userEditable，目前每次 apply 都設成 payload.USER_EDITABLE，所以下面的 WARN 分支平常走不到；
    # 只有舊版安裝器寫的 manifest（userEditable 比現在多）或手改過 manifest 時才會出現。保留行為，不刪。
    rows.extend((OK, f"{e} 使用者自己的設定值（update 會保留、新版新增的鍵會補上）") if e in payload.USER_EDITABLE else (WARN, f"{e} 已被使用者修改（允許，update 會保留）") for e in edited)
    s = read_json(lay.settings) if lay.settings.exists() else {}
    script = (lay.payload / "hooks" / "usage_guard.py").as_posix()
    guard_on = usage_guard_enabled(lay)
    if not guard_on:
        rows.append((OK, "用量守門 hook：已由使用者關閉（local.json usageGuard=false；視窗或 `web --usage-guard on` 可開）"))
    for event, _ in settings_ops.HOOK_SPECS:
        if not guard_on:
            if settings_ops.has_marked(s, event):
                rows.append((BAD, f"{event} hook 仍在 settings.json（用量守門已關閉，重跑 update 會移除）"))
            continue
        marked = settings_ops.has_marked(s, event)
        skipped = any(x["event"] == event for x in m["settings"].get("hooksSkippedExisting", []))
        if marked:
            good = len(marked) == 1 and script in marked[0]
            rows.append((OK if good else BAD, f"{event} hook（本工具）" + ("存在、指向已安裝腳本" if good else f"異常：{marked}")))
        elif skipped and settings_ops.find_unmarked_equivalent(s, event):
            rows.append((OK, f"{event} hook：使用者既有的 usage_guard 條目在作用（本工具未重複註冊）"))
        else:
            rows.append((BAD, f"{event} hook 不存在"))
    if guard_on and any(settings_ops.has_marked(s, e) for e, _ in settings_ops.HOOK_SPECS):
        rows.append(_python_row(m.get("python")))
    rows.extend(web.verify_rows(lay, m.get("web") or {}, s))
    try:
        vkeys = web.load_local(lay).get("keys") or {}
    except ValueError:
        vkeys = {}
    rows.extend(video.verify_rows(lay, m.get("video") or {}, importer, vkeys, ffmpeg))
    try:  # IN-13：只在記憶體編譯（原本寫 _verify.pyc 再刪：verify 不是唯讀，兩個同時跑或目錄唯讀時誤報）
        src = lay.payload / "hooks" / "usage_guard.py"
        compile(src.read_bytes(), str(src), "exec")
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
    upd = "（repo 較新，可 update）" if _ver(rv) > _ver(m.get("version")) else ""
    last = (m.get("backups") or [{}])[-1]
    skipped_n = len(m["settings"].get("hooksSkippedExisting", []))
    guard_line = ("用量守門：已關閉（本機偏好 usageGuard=false）" if not usage_guard_enabled(lay)
                  else f"用量守門：本工具 hook 條目 {marked} 條；沿用使用者既有 hook {skipped_n} 條（標記 {HOOK_MARK}）")
    return 0, [
        f"已安裝 v{m['version']}；repo v{rv}{upd}",
        f"安裝於 {m.get('installedAt')}，最後更新 {m.get('updatedAt')}；來源 {m.get('repo')}",
        f"檔案 {len(m['files'])} 個；skills：{', '.join(m.get('skills', []))}",
        guard_line,
        f"聯網來源：{'已啟用，MCP ' + (', '.join(m['web'].get('mcpAdded', [])) or '無') if m.get('web', {}).get('enabled') else '未啟用（`install.py web` 可開）'}",
        f"影片來源：{'已啟用（' + ', '.join(m['video'].get('packages', [])) + '）' if m.get('video', {}).get('enabled') else '未啟用（`install.py video` 可開）'}",
        f"備份 {len(m.get('backups', []))} 次，最近：{last.get('settings')}",
    ]
