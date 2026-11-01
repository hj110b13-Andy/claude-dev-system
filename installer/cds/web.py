"""聯網來源（選用）：依 config/web-sources.json 註冊免金鑰搜尋 MCP、寫入 WebSearch 上限環境變數。

為什麼用 `claude mcp add／remove` 而不直接改 ~/.claude.json：那是 Claude Code 的主狀態檔（含登入狀態、各專案紀錄），
交給官方 CLI 寫最安全；本模組只「讀」它來判斷名稱是否已存在與 verify。
本機偏好（金鑰、啟用／停用、env 覆寫）放 <CLAUDE_HOME>/claude-dev-system/config/local.json：不在 manifest 的 files 裡，
update／uninstall 都不會動它，也不會進 repo。
"""
from __future__ import annotations

import copy
import re
import shutil
import urllib.parse
import subprocess
from pathlib import Path

from .fsio import read_json, write_json
from .paths import Layout

SOURCES_REL = "config/web-sources.json"
LOCAL_REL = "config/local.json"
OK, BAD, WARN = "✅", "❌", "⚠️"


def empty_record() -> dict:
    return {"enabled": False, "mcpAdded": [], "envCreatedKeys": [], "skipped": []}


def sources(lay: Layout) -> dict:
    return read_json(lay.payload / SOURCES_REL)


def local_path(lay: Layout) -> Path:
    return lay.payload / LOCAL_REL


def load_local(lay: Layout) -> dict:
    base = {"keys": {}, "enable": [], "disable": [], "env": {}}
    p = local_path(lay)
    if p.exists():
        try:
            data = read_json(p)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"本機偏好檔 {p} 不是合法 JSON：{e}；請修好或刪除後重跑") from None
        if not isinstance(data, dict):
            raise ValueError(f"本機偏好檔 {p} 最外層必須是物件（{{...}}）")
        for k, v in data.items():
            base[k] = v
    return base


def save_local(lay: Layout, d: dict) -> None:
    write_json(local_path(lay), d)


def user_config_path(lay: Layout) -> Path:
    """`claude mcp add --scope user` 寫入的檔：預設 ~/.claude.json；設 CLAUDE_CONFIG_DIR／--claude-home 時在該目錄下。"""
    if lay.home == Path.home() / ".claude":
        return Path.home() / ".claude.json"
    return lay.home / ".claude.json"


def installed_servers(lay: Layout) -> dict:
    p = user_config_path(lay)
    if not p.exists():
        return {}
    try:
        return dict(read_json(p).get("mcpServers") or {})
    except Exception:  # noqa: BLE001
        return {}


KEY_MODES = ("fallback", "always", "free")  # fallback（預設）：免金鑰版＋金鑰版（<名稱>-key）同時註冊，規則先用免金鑰；always：只註冊金鑰版；free：只註冊免金鑰版（金鑰留著不用；少一個伺服器＝每次工具呼叫少讀一段說明，2026-11-01 實測 5 個 -key 共約 9,400 token）


def _entry(spec: dict, key: str | None = None) -> dict:
    url = spec["url"]
    headers = dict(spec.get("headers") or {})
    if key and spec.get("keyParam"):
        url += ("&" if "?" in url else "?") + f"{spec['keyParam']}={urllib.parse.quote(key, safe='')}"
        headers = dict(spec.get("keyedHeaders") if spec.get("keyedHeaders") is not None else headers)
    elif key and spec.get("keyHeader"):
        headers[spec["keyHeader"]] = spec.get("keyHeaderPrefix", "") + key
    return {"url": url, "headers": headers}


def key_mode(local: dict, name: str) -> str:
    m = (local.get("keyMode") or {}).get(name)
    return m if m in KEY_MODES else "fallback"


def desired_servers(src: dict, local: dict) -> dict[str, dict]:
    """名稱 → {url, headers}；default 與 local 的 enable／disable 決定開關。
    有金鑰時依 keyMode：fallback（預設）＝免金鑰版 `<名稱>` 與金鑰版 `<名稱>-key` 都註冊，規則先用免金鑰、撞限流才用 -key；
    always＝只註冊金鑰版 `<名稱>`；free＝只註冊免金鑰版（金鑰保留在 local.json 但不用）。"""
    out: dict[str, dict] = {}
    for name, spec in (src.get("mcpServers") or {}).items():
        on = bool(spec.get("default"))
        if name in local.get("enable", []):
            on = True
        if name in local.get("disable", []):
            on = False
        if not on:
            continue
        key = (local.get("keys") or {}).get(spec.get("keyName") or name)
        keyable = bool(spec.get("keyParam") or spec.get("keyHeader"))
        mode = key_mode(local, name)
        if key and keyable and mode == "always":
            out[name] = _entry(spec, key)
        elif key and keyable and mode == "fallback":
            out[name] = _entry(spec)
            out[name + "-key"] = _entry(spec, key)
        else:  # 沒金鑰、不可帶金鑰、或 free
            out[name] = _entry(spec)
    return out


def desired_env(src: dict, local: dict) -> dict[str, str]:
    env = {k: str(v) for k, v in (src.get("env") or {}).items() if not k.startswith("_")}
    env.update({k: str(v) for k, v in (local.get("env") or {}).items()})
    return env


def mask(text: str, local: dict) -> str:
    """把金鑰值遮成 ***；URL 編碼後的形式也遮（金鑰會出現在 `claude mcp add` 的命令列與 ~/.claude.json，這是 Claude Code 的設計，本工具只能保證不印出來）。"""
    for v in (local.get("keys") or {}).values():
        if v:
            text = text.replace(str(v), "***")
            q = urllib.parse.quote(str(v), safe="")
            if q != str(v):
                text = text.replace(q, "***")
    return text


def default_runner(args: list[str]) -> tuple[int, str]:
    exe = shutil.which("claude")
    if not exe:
        return 127, "找不到 claude 指令"
    try:
        r = subprocess.run([exe, "mcp", *args], capture_output=True, timeout=90)
    except Exception as e:  # noqa: BLE001
        return 1, str(e)
    return r.returncode, ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace").strip()


def _same(have: dict | None, want: dict) -> bool:
    return bool(have) and have.get("url") == want["url"] and dict(have.get("headers") or {}) == want["headers"]


def sync_mcp(lay: Layout, old: dict, runner=default_runner, log: list | None = None) -> dict:
    """把 user scope 的 MCP 對齊 desired：只動本工具加過的名稱；使用者自己同名的略過；關掉的移除。"""
    log = log if log is not None else []
    src, local = sources(lay), load_local(lay)
    want, have = desired_servers(src, local), installed_servers(lay)
    mine = set(old.get("mcpAdded", []))
    rec = {"mcpAdded": [], "skipped": []}
    for name, spec in want.items():
        if name in have and name not in mine:
            rec["skipped"].append(name)
            log.append(f"{WARN} MCP {name} 已由使用者自行設定，略過不覆蓋（想交給本工具管理：先 `claude mcp remove -s user {name}` 再重跑）")
            continue
        if name in mine and _same(have.get(name), spec):
            rec["mcpAdded"].append(name)
            continue
        if name in mine and name in have:
            runner(["remove", "--scope", "user", name])  # 連線設定變了（例如新增金鑰），重建
        args = ["add", "--scope", "user", "--transport", "http", name, spec["url"]]
        for k, v in spec["headers"].items():
            args += ["--header", f"{k}: {v}"]
        code, out = runner(args)
        if code != 0:
            log.append(f"{BAD} MCP {name} 註冊失敗：{mask(out, local)}")
            continue
        rec["mcpAdded"].append(name)
        log.append(f"MCP 註冊 {name} → {mask(spec['url'], local)}" + ("（含 header）" if spec["headers"] else ""))
    for name in sorted(mine - set(want)):
        if name in have:
            code, out = runner(["remove", "--scope", "user", name])
            log.append(f"MCP 移除 {name}" if code == 0 else f"{BAD} MCP {name} 移除失敗：{mask(out, local)}")
    rec["mcpAdded"].sort()
    return rec


def remove_mcp(lay: Layout, old: dict, runner=default_runner, log: list | None = None) -> None:
    log = log if log is not None else []
    have = installed_servers(lay)
    try:
        local = load_local(lay)
    except ValueError:
        local = {}  # 只用來遮罩；偏好檔壞掉不該擋住移除
    for name in old.get("mcpAdded", []):
        if name not in have:
            continue
        code, out = runner(["remove", "--scope", "user", name])
        log.append(f"MCP 移除 {name}" if code == 0 else f"{BAD} MCP {name} 移除失敗：{mask(out, local)}")


def apply_env(settings: dict, env: dict[str, str], old_created: list[str]) -> tuple[dict, list[str], list[str]]:
    """回傳 (新 settings, createdKeys, skipped)。使用者自己設過的鍵（不論值）不覆蓋、不登記；env 不是物件時整個略過。"""
    s = copy.deepcopy(settings)
    created, skipped = [], []
    old = set(old_created or [])
    if "env" in s and not isinstance(s.get("env"), dict):
        return s, [], ["env"]
    if "env" not in s:
        s["env"] = {}
        created.append("env")
    elif "env" in old:
        created.append("env")
    for k, v in env.items():
        if k in s["env"] and f"env.{k}" not in old:
            skipped.append(k)
            continue
        s["env"][k] = v
        created.append(f"env.{k}")
    for key in old:  # 本工具以前寫的、新版不再要的鍵：拿掉（0.10.9 撤回 CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH 時發現殘留）
        if key.startswith("env.") and key[4:] not in env and key[4:] in s["env"]:
            del s["env"][key[4:]]
    return s, created, skipped


def remove_env(settings: dict, created: list[str]) -> tuple[dict, list[str]]:
    s = copy.deepcopy(settings)
    removed: list[str] = []
    env = s.get("env")
    if not isinstance(env, dict):
        return s, removed
    for key in created or []:
        if key.startswith("env.") and key[4:] in env:
            del env[key[4:]]
            removed.append(key[4:])
    if not env and "env" in (created or []):
        del s["env"]
    return s, removed


def verify_rows(lay: Layout, rec: dict, settings: dict) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if not rec.get("enabled"):
        rows.append((OK, "聯網來源：未啟用（選用；`install.py web` 可開）"))
        return rows
    src, local = sources(lay), load_local(lay)
    want, have = desired_servers(src, local), installed_servers(lay)
    for name in rec.get("mcpAdded", []):
        if name not in want:
            rows.append((WARN, f"MCP {name} 已在設定中關閉，但仍登記在紀錄（重跑 `install.py web` 會移除）"))
        elif _same(have.get(name), want[name]):
            rows.append((OK, f"MCP {name} 已註冊（user scope）"))
        else:
            rows.append((BAD, f"MCP {name} 不在 user scope 或連線設定不符（重跑 `install.py web`）"))
    for name in rec.get("skipped", []):
        rows.append((WARN, f"MCP {name} 沿用使用者自己的設定"))
    for name in want:
        if name not in rec.get("mcpAdded", []) and name not in rec.get("skipped", []):
            rows.append((BAD, f"MCP {name} 應啟用但未註冊"))
    env = (settings.get("env") or {}) if isinstance(settings.get("env"), dict) else {}
    for k, v in desired_env(src, local).items():
        if f"env.{k}" in rec.get("envCreatedKeys", []):
            rows.append((OK if str(env.get(k)) == v else BAD, f"env {k}={env.get(k)}（預期 {v}）"))
        elif k in env:
            rows.append((WARN, f"env {k}={env.get(k)} 為使用者自行設定，未覆蓋"))
        else:
            rows.append((BAD, f"env {k} 未寫入"))
    keys = local.get("keys") or {}
    rows.append((OK, "本機金鑰：" + (", ".join(sorted(k for k, v in keys.items() if v)) or "無") + f"（{local_path(lay)}）"))
    return rows


def set_key_arg(local: dict, kv: str) -> None:
    m = re.fullmatch(r"([A-Za-z0-9_-]+)=(.*)", kv.strip())
    if not m:
        raise ValueError(f"--key 格式應為 名稱=值：{kv}")
    local.setdefault("keys", {})[m.group(1)] = m.group(2)


def set_key_mode_arg(local: dict, kv: str) -> None:
    m = re.fullmatch(r"([A-Za-z0-9_-]+)=(fallback|always|free)", kv.strip())
    if not m:
        raise ValueError(f"--key-mode 格式應為 名稱=fallback|always|free：{kv}")
    local.setdefault("keyMode", {})[m.group(1)] = m.group(2)


def set_env_arg(local: dict, kv: str) -> None:
    m = re.fullmatch(r"([A-Z0-9_]+)=(.*)", kv.strip())
    if not m:
        raise ValueError(f"--env 格式應為 大寫鍵=值：{kv}")
    local.setdefault("env", {})[m.group(1)] = m.group(2)
