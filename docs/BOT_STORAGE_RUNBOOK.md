# New iPhone Service — Telegram bot storage recovery and cutover

Verified: 2026-11-07. Workspace: My Workspace (Render). This guide contains no credentials.

## Verified facts
- Production bot: Render `new-iphone-service`, service `srv-dbef22vavr4c73anlk9g`.
- Production webhook: `https://new-iphone-service.onrender.com/telegram/webhook`.
- Backend startup logs confirmed `BOT_STORAGE_RISK: SQLite backend detected`.
- Render plan: Free; no persistent disk, shell or SSH.
- Prepared persistent Neon Free project: `royal-hat-88545523` in Oregon,
  database `new_iphone_bot`, matching tables `users`, `messages`, `published_news`.
  This new database currently contains no imported production data.
- Production's `DATABASE_URL` has NOT been modified. No data migration has been claimed.
- Source repository contains `scripts/migrate_sqlite_to_neon.py` and the
  `asyncpg` dependency; its backup dry run is tested in GitHub Actions.

## Do not destroy existing data
A Render Free filesystem is ephemeral. Updates, restarts and idle spin-downs
can remove `bot.db`. Upgrading the plan may also restart/replace the instance:
DO NOT assume upgrading preserves the old file.

Never switch `DATABASE_URL` until one of the following is explicitly resolved:
1. A verified, externally saved copy of the active SQLite `bot.db` exists
   and no new bot writes can be missed during cutover; or
2. The owner explicitly accepts starting with the new, empty PostgreSQL
   tables because no historical SQLite file can be recovered.

Do not use unauthenticated HTTP file-export routes, embed credentials in
GitHub, or delete the old source as part of migration.

## If a verified SQLite copy becomes available
1. Verify it has `users`, `messages` and `published_news`.
2. Arrange a short maintenance window to prevent new messages or posts from
   being recorded in SQLite after the snapshot; preserve pending Telegram
   updates (never `drop_pending_updates=True`).
3. Retrieve the Neon PostgreSQL connection URL securely, without displaying
   it in chat, source code, or logs.
4. In a trusted environment with `asyncpg` installed, set
   `BOT_MIGRATION_DATABASE_URL` to the PostgreSQL URL and run:

   ```bash
   python scripts/migrate_sqlite_to_neon.py /secure/bot.db \\
     --backup-out /secure/bot-before-cutover.backup.db
   ```

   To validate without network writes, add `--dry-run`.
   The script refuses an existing backup destination or a nonempty Neon table,
   checks backup integrity, and imports all rows in one database transaction.
5. Verify counts in Neon, protect the local backup, then update Render's
   `DATABASE_URL` to an SQLAlchemy asyncpg URL. The live instance should
   use `postgresql+asyncpg://...`, not the migration script's raw
   `postgresql://...` DSN.
6. Check the Render deploy is live, bot webhook is registered, AI replies and
   cron publication work, and repeat the database-count comparison.
7. Do not delete the SQLite backup until independently verified backups of
   Neon have been configured.

## Other reliability work still needed
- Render settings: choose `After CI Checks Pass` on services with actual
  required GitHub checks and configure per-service build filters.
- GitHub and Render API app connections currently do not expose changing
  those settings, so they are not marked done.
- DNS for apex domains stays DNS-only to preserve Russian-user access;
  Cloudflare WAF protects only requests that pass through its proxy.
- Independent GitHub uptime checks and hourly Render health monitoring are
  already enabled; production PapAuto API audit runs separately from
  pre-deploy CI, avoiding a deployment/CI dependency loop.
