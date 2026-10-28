"""Scheduled Render cron trigger for the web service news publisher."""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> int:
    base_url = os.getenv("NEWS_TRIGGER_URL", "").strip().rstrip("/")
    secret = os.getenv("NEWS_PUBLISH_SECRET", "").strip()
    if not base_url or not secret:
        logger.error("NEWS_TRIGGER_URL and NEWS_PUBLISH_SECRET must be configured")
        return 2

    now = datetime.now(ZoneInfo("Asia/Novosibirsk"))
    slot_hour = 10 if now.hour < 12 else 15 if now.hour < 17 else 20
    slot_key = f"{now:%Y-%m-%d}-{slot_hour:02d}"
    payload = json.dumps({"slot_key": slot_key}).encode("utf-8")
    request = Request(
        f"{base_url}/news/publish-next",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-News-Publish-Secret": secret,
            "X-News-Slot": slot_key,
            "User-Agent": "NewIphoneServiceNewsScheduler/1.0",
        },
        method="POST",
    )

    for attempt in range(1, 6):
        try:
            with urlopen(request, timeout=180) as response:
                body = response.read().decode("utf-8", errors="replace")
                logger.info("News trigger response (HTTP %s): %s", response.status, body[:1000])
                return 0 if 200 <= response.status < 300 else 1
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            logger.error("News trigger HTTP %s: %s", exc.code, body[:1000])
            if exc.code in (401, 403, 404):
                return 1
        except (URLError, TimeoutError, OSError) as exc:
            logger.warning("News trigger attempt %d/5 failed: %s", attempt, exc)
        if attempt < 5:
            time.sleep(20 * attempt)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
