"""檔案讀寫：原子寫入、雜湊、JSON。"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str | None:
    try:
        return sha256_bytes(p.read_bytes())
    except FileNotFoundError:
        return None


REPLACE_RETRIES, REPLACE_WAIT = 5, 0.05  # Windows 上目標檔正被別的程序（防毒、編輯器、另一個安裝程序）短暫開著時 os.replace 會 PermissionError（自己加的次數與間隔）


def atomic_write_bytes(p: Path, data: bytes) -> None:
    """同目錄寫唯一暫存檔再 os.replace。IN-06：原本暫存檔名固定（<名>.cds-tmp），兩個程序同時寫會互踩
    （3 個程序各 update 8 次：24 次中 11 次 PermissionError）；replace 遇 PermissionError 短暫重試，失敗時刪掉暫存檔。"""
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=p.name + ".", suffix=".cds-tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        if os.name != "nt":  # mkstemp 建的是 0600；維持原本的權限（原檔的，沒有原檔就依 umask），不要因為改寫法而改權限
            try:
                mode = p.stat().st_mode & 0o777
            except OSError:
                um = os.umask(0)
                os.umask(um)
                mode = 0o666 & ~um
            os.chmod(tmp, mode)
        for i in range(REPLACE_RETRIES):
            try:
                os.replace(tmp, p)
                return
            except PermissionError:
                if i == REPLACE_RETRIES - 1:
                    raise
                time.sleep(REPLACE_WAIT)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class LockBusy(Exception):
    """另一個程序已拿著同一個設定目錄的安裝鎖。"""


def acquire_lock(path: Path) -> int:
    """作業系統層級的非阻塞檔案鎖（程序結束、被殺都由系統自動釋放，不會有殘留鎖）。回傳 fd；拿不到丟 LockBusy。
    依據：tox-dev/filelock（MIT）src/filelock/_unix.py 用 fcntl.flock(fd, LOCK_EX | LOCK_NB)、_windows.py 用 LockFileEx；
    Windows 這裡用標準庫的 msvcrt.locking(fd, LK_NBLCK, 1)（鎖第 0 個位元組，鎖超過檔尾也可以）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise LockBusy(str(path)) from None
    return fd


def release_lock(fd: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        os.close(fd)


def read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def dump_json(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def write_json(p: Path, obj) -> None:
    atomic_write_bytes(p, dump_json(obj))
