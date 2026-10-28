"""Render Cron entry point for scheduled New iPhone Service channel news."""
import datetime
import json
import os
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
    with urllib.request.urlopen(request, timeout=180) as response:
        body = response.read().decode("utf-8", errors="replace")
        print(f"HTTP {response.status}")
        print(body)

if __name__ == "__main__":
    main()
