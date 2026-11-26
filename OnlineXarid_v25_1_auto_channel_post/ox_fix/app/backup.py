"""Daily database backups with 30-day retention.
Run as a separate always-on worker: python -m app.backup
"""
import os, time, subprocess
from datetime import datetime, timezone
from pathlib import Path
from app.config import DATABASE_URL

BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "storage/backups"))
RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))

def backup_once():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if DATABASE_URL.startswith("sqlite"):
        raw = DATABASE_URL.split("///", 1)[-1].split("?", 1)[0]
        source = Path(raw)
        if not source.is_absolute():
            source = Path.cwd() / source
        if not source.exists():
            raise FileNotFoundError(f"SQLite database not found: {source}")
        import sqlite3
        target = BACKUP_DIR / f"onlinexarid_{stamp}.sqlite3"
        with sqlite3.connect(str(source)) as src, sqlite3.connect(str(target)) as dst:
            src.backup(dst)
            if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                target.unlink(missing_ok=True)
                raise RuntimeError("Backup integrity check failed")
    elif "postgresql" in DATABASE_URL:
        dsn = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
        target = BACKUP_DIR / f"onlinexarid_{stamp}.dump"
        proc = subprocess.run(["pg_dump", "--format=custom", "--no-owner", "--file", str(target), dsn],
                              capture_output=True, text=True)
        if proc.returncode:
            target.unlink(missing_ok=True)
            raise RuntimeError("pg_dump failed: " + proc.stderr[-1000:])
    else:
        raise RuntimeError("Unsupported DATABASE_URL for backup")
    cutoff = time.time() - RETENTION_DAYS * 86400
    for item in BACKUP_DIR.iterdir():
        if item.is_file() and item.stat().st_mtime < cutoff:
            item.unlink()
    return str(target)

def main():
    while True:
        try:
            print("Database backup created:", backup_once(), flush=True)
        except Exception as exc:
            print("DATABASE BACKUP ERROR:", str(exc), flush=True)
        time.sleep(86400)

if __name__ == "__main__":
    main()
