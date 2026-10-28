"""Render Cron entry point for scheduled New iPhone Service channel news."""
import datetime
import json
import os
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

def main() -> None:
    url = os.environ["PUBLISH_URL"].strip()
    secret = os.environ["NEWS_PUBLISH_SECRET"].strip()
    if not url or not secret:
        raise RuntimeError("PUBLISH_URL and NEWS_PUBLISH_SECRET must be configured")

    slot_key = datetime.datetime.now(ZoneInfo("Asia/Novosibirsk")).strftime("%Y-%m-%d-%H")
    payload = json.dumps({"slot_key": slot_key}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-News-Publish-Secret": secret,
        },
        method="POST",
    )
    # Render's free web service may be waking from sleep when the scheduled
    # job calls it. Retry transient timeouts and gateway/network errors. The
    # slot_key makes the publishing endpoint idempotent, so retries won't
    # create duplicate posts if Telegram accepted a post but the response was lost.
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                body = response.read().decode("utf-8", errors="replace")
                print(f"HTTP {response.status}")
                print(body)
                if response.status >= 400:
                    raise RuntimeError(f"News endpoint returned HTTP {response.status}")
                return
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            last_error = exc
            print(f"Publish attempt {attempt}/3 failed: {type(exc).__name__}: {exc}", flush=True)
            if attempt < 3:
                time.sleep(10 * attempt)
    raise RuntimeError(f"News publishing failed after 3 attempts: {last_error}") from last_error

if __name__ == "__main__":
    main()
