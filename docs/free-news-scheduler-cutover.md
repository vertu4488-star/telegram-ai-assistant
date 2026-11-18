# Free news scheduling migration: safety checklist

Current production: Render Cron `new-iphone-news-cron` runs at 03:00, 05:00, 08:00, 10:00 and 13:00 UTC, matching 10:00, 12:00, 15:00, 17:00, 20:00 in Novosibirsk. The actual publishing API is `https://new-iphone-service.onrender.com/news/publish-next`.

## Important safety constraints

- **Do not merge this branch yet** if the legacy bot still holds conversation data in ephemeral SQLite. Any Render deployment can replace the container and lose that local history. Make a verified backup first.
- **Do not disable or delete the existing Render Cron** until a production GitHub Actions test is successful.
- **Do not run both schedulers intentionally**. The Neon `published_news.slot_key` unique record protects from duplicate slot publishing, but avoiding parallel schedulers is safer.
- **Do not paste the shared secret into a GitHub file, issue, PR or chat.** Add it only as a GitHub Actions repository secret named `NEWS_PUBLISH_SECRET`.
- The workflow intentionally has NO automatic schedule at this stage and defaults to a read-only health check.

## Cutover procedure

1. Preserve the existing SQLite bot history, if any, using a protected backup procedure. Verify the archive before replacing the running instance.
2. Set the `NEWS_PUBLISH_SECRET` Actions secret in the repository settings, using the value configured on the Render news publisher. GitHub will mask this secret in workflow logs.
3. Merge the pilot only when the bot's data is safe. Run `Telegram news scheduler — free GitHub Actions pilot` with `publish=false`. Verify the HTTP health check passed and the secret was configured.
4. During a normal Novosibirsk publishing hour, run manually with `publish=true`. Confirm status `published` or `already_published` and check Neon slot history. The same source script is used by Render Cron and GitHub Actions.
5. Stop the paid Render Cron schedule before enabling the GitHub schedule.
6. Enable GitHub Actions scheduled triggers in `.github/workflows/free-news-scheduler-pilot.yml`:
   ```yaml
   schedule:
     - cron: '0 3,5,8,10,13 * * *'
   ```
   Keep `workflow_dispatch` enabled for diagnostics. Monitor five scheduled successes and zero duplicated `slot_key` rows.
7. Confirm no unintended Render billing (minimum $1/month per Render Cron) and check build pipeline spending limits.

The repository's GitHub Actions workflow is a staged replacement, **not an active scheduler** until the cutover is completed.
