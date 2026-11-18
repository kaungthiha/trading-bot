"""Data management: backup, restore, reset. All destructive actions back up first.

Backups use SQLite's online backup API (consistent even while the app is running) and are
written to backend/data/backups/ (git-ignored).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from sqlalchemy.engine import make_url

from app.core.config import BACKEND_ROOT
from app.core.lock import AlreadyRunning, SingleInstanceLock

BACKUP_DIR = BACKEND_ROOT / "data" / "backups"
WORKER_LOCK = BACKEND_ROOT / "data" / "worker.lock"


class OpsError(RuntimeError):
    pass


def sqlite_path(database_url: str) -> Path:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise OpsError("Backup/restore supports file-based SQLite databases only")
    return Path(url.database)


def _copy(src: Path, dst: Path) -> None:
    # NB: sqlite3's context manager only commits; close explicitly so Windows releases
    # the file handles.
    with closing(sqlite3.connect(src)) as s, closing(sqlite3.connect(dst)) as d:
        s.backup(d)


def backup(database_url: str, dest_dir: Path = BACKUP_DIR, label: str = "manual") -> Path:
    src = sqlite_path(database_url)
    if not src.exists():
        raise OpsError(f"Database not found: {src.name}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    dst = dest_dir / f"{src.stem}-{label}-{stamp}.sqlite3"
    _copy(src, dst)
    return dst


def validate_backup(path: Path) -> str:
    """Return the schema revision of a backup, or raise if it isn't one of our databases."""
    if not path.is_file():
        raise OpsError("Backup file not found")
    try:
        with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as c:
            if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise OpsError("Backup failed SQLite integrity check")
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"alembic_version", "markets"} <= tables:
                raise OpsError("File is not a Kalshi Research Terminal database")
            rev = c.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.DatabaseError as e:
        raise OpsError(f"Not a valid SQLite database: {type(e).__name__}") from None
    if not rev:
        raise OpsError("File is not a Kalshi Research Terminal database")
    return rev[0]


def _worker_guard(lock_path: Path) -> SingleInstanceLock:
    lock = SingleInstanceLock(lock_path)
    try:
        lock.acquire()
    except AlreadyRunning:
        raise OpsError("The worker is running; stop it before restoring or resetting") from None
    return lock


def restore(database_url: str, backup_file: Path, cfg_factory,  # type: ignore[no-untyped-def]
            lock_path: Path = WORKER_LOCK,
            backup_dir: Path = BACKUP_DIR) -> tuple[Path | None, str]:
    """Replace the database with ``backup_file``. The current database is backed up first.
    Returns (pre-restore backup path, restored schema revision)."""
    rev = validate_backup(backup_file)
    target = sqlite_path(database_url)
    lock = _worker_guard(lock_path)
    try:
        safety = backup(database_url, backup_dir, label="pre-restore") if target.exists() else None
        target.parent.mkdir(parents=True, exist_ok=True)
        _copy(backup_file, target)
        command.upgrade(cfg_factory(database_url), "head")  # bring older backups up to date
    finally:
        lock.release()
    return safety, rev


def reset(database_url: str, cfg_factory, lock_path: Path = WORKER_LOCK,  # type: ignore[no-untyped-def]
          backup_dir: Path = BACKUP_DIR) -> Path | None:
    """Back up, delete, and re-create an empty migrated database."""
    target = sqlite_path(database_url)
    lock = _worker_guard(lock_path)
    try:
        safety = backup(database_url, backup_dir, label="pre-reset") if target.exists() else None
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(target) + suffix)
            if p.exists():
                try:
                    p.unlink()
                except PermissionError:
                    raise OpsError("The database is in use; stop the backend and worker, then "
                                   f"retry. Your data was backed up to {safety}") from None
        command.upgrade(cfg_factory(database_url), "head")
    finally:
        lock.release()
    return safety


def list_backups(backup_dir: Path = BACKUP_DIR) -> list[Path]:
    return sorted(backup_dir.glob("*.sqlite3"), reverse=True) if backup_dir.exists() else []
