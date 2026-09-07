"""Backup/restore of the local SQLite database file (app.paths.db_path())."""
import shutil
import sqlite3

from app import db
from app.paths import db_path


def backup_database(dest_path: str) -> None:
    """Snapshot the live database to dest_path using SQLite's own backup
    API rather than a raw file copy - it's safe to call while the app's
    own connection is open and mid-session, since it can't catch the file
    in a half-written state the way copying the file bytes directly could."""
    dest = sqlite3.connect(dest_path)
    try:
        db.get_connection().backup(dest)
    finally:
        dest.close()


def validate_backup_file(src_path: str) -> None:
    """Raises sqlite3.DatabaseError with a human-readable message if
    src_path isn't a usable scheduler database, so restore_database() fails
    before touching the live file rather than after."""
    conn = sqlite3.connect(src_path)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise sqlite3.DatabaseError(f"integrity check failed: {result}")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "clients" not in tables or "appointments" not in tables:
            raise sqlite3.DatabaseError("not an Electrolysis Scheduler database")
    finally:
        conn.close()


def restore_database(src_path: str) -> None:
    """Replace the live database file with src_path. Closes the app's
    current connection first so the live file isn't open/locked during the
    copy. The caller must restart the app afterward - every already-open
    view holds data read from the old file in memory, and there is no
    reload path that safely re-syncs all of them in place."""
    validate_backup_file(src_path)
    db.close_connection()
    shutil.copyfile(src_path, db_path())
