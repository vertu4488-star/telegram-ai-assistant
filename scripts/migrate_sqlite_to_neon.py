#!/usr/bin/env python3
"""One-time, fail-closed SQLite -> PostgreSQL copy for New iPhone Service.

Only run with access to the live bot.db file after suspending new bot updates.
Requires the destination Neon DB tables to exist and be empty.
Never prints database credentials or message contents.
The source is never deleted or modified.
"""
import argparse
import asyncio
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

TABLES = {
    "users": ("id", "telegram_id", "username", "first_name", "last_name",
              "language_code", "created_at", "updated_at"),
    "messages": ("id", "telegram_id", "role", "content", "created_at"),
    "published_news": ("id", "slot_key", "source_url", "title",
                       "source_name", "published_at", "is_evergreen"),
}
DATES = {"created_at", "updated_at", "published_at"}


def safe_datetime(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def snapshot(source: Path, destination: Path):
    if not source.is_file():
        raise RuntimeError("SQLite source does not exist; refusing to create an empty database")
    if destination.exists():
        raise RuntimeError("Backup destination already exists; refusing to overwrite")
    destination.parent.mkdir(parents=True, exist_ok=True)
    old = sqlite3.connect("file:" + source.resolve().as_posix() + "?mode=ro", uri=True)
    try:
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        with sqlite3.connect(destination) as copy:
            old.backup(copy)
            result = copy.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise RuntimeError("SQLite backup failed integrity check")
            for table in TABLES:
                if not copy.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone():
                    raise RuntimeError("SQLite source table is missing: " + table)
    finally:
        old.close()


def source_rows(backup: Path):
    data = {}
    with sqlite3.connect("file:" + backup.resolve().as_posix() + "?mode=ro", uri=True) as src:
        src.row_factory = sqlite3.Row
        for table, fields in TABLES.items():
            query = "SELECT " + ", ".join(fields) + " FROM " + table + " ORDER BY id"
            data[table] = []
            for row in src.execute(query):
                values = []
                for field in fields:
                    value = row[field]
                    if field in DATES and value is not None:
                        value = safe_datetime(value)
                    if field == "is_evergreen":
                        value = bool(value)
                    values.append(value)
                data[table].append(tuple(values))
    return data


async def copy_to_postgres(data, dsn):
    import asyncpg  # Optional runtime dependency; not needed for --dry-run.
    conn = await asyncpg.connect(dsn=dsn, command_timeout=45)
    try:
        async with conn.transaction():
            # Atomic migration and a guard against accidental duplicate imports.
            await conn.execute(
                "LOCK TABLE public.users, public.messages, public.published_news "
                "IN ACCESS EXCLUSIVE MODE"
            )
            for table in TABLES:
                existing = await conn.fetchval("SELECT COUNT(*) FROM public." + table)
                if existing:
                    raise RuntimeError(
                        "Target has data in " + table + "; not overwriting or merging"
                    )
            for table, fields in TABLES.items():
                columns = ", ".join(fields)
                params = ", ".join("$" + str(i) for i in range(1, len(fields) + 1))
                query = "INSERT INTO public." + table + " (" + columns + ") VALUES (" + params + ")"
                if data[table]:
                    await conn.executemany(query, data[table])
                actual = await conn.fetchval("SELECT COUNT(*) FROM public." + table)
                if actual != len(data[table]):
                    raise RuntimeError("Destination count mismatch for " + table)
                await conn.fetchval(
                    "SELECT setval(pg_get_serial_sequence('public." + table + "', 'id'),"
                    " GREATEST(COALESCE(MAX(id),0),1), COALESCE(MAX(id)>0,false))"
                    " FROM public." + table
                )
    finally:
        await conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Existing live SQLite bot.db path")
    parser.add_argument("--backup-out", type=Path, required=True,
                        help="Non-existing path for a SQLite safety backup")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate/backup source only; do not touch Neon")
    args = parser.parse_args()
    snapshot(args.source, args.backup_out)
    data = source_rows(args.backup_out)
    counts = {table: len(rows) for table, rows in data.items()}
    print("SQLite integrity OK. Backup created. Row counts:", counts)
    if args.dry_run:
        return
    dsn = os.environ.get("BOT_MIGRATION_DATABASE_URL", "")
    if not dsn:
        raise RuntimeError("BOT_MIGRATION_DATABASE_URL is missing; backup kept")
    asyncio.run(copy_to_postgres(data, dsn))
    print("Migration committed and verified. Backup kept; switch the bot only after review.")


if __name__ == "__main__":
    main()
