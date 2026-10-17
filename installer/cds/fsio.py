"""檔案讀寫：原子寫入、雜湊、JSON。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str | None:
    try:
        return sha256_bytes(p.read_bytes())
    except FileNotFoundError:
        return None


def atomic_write_bytes(p: Path, data: bytes) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".cds-tmp")
    tmp.write_bytes(data)
    os.replace(tmp, p)


def read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def dump_json(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def write_json(p: Path, obj) -> None:
    atomic_write_bytes(p, dump_json(obj))
