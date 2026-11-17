"""Regression tests for persistent Telegram channel news deduplication."""
from datetime import datetime, timezone
from types import SimpleNamespace

from app.news.publisher import Article, _already_published, _normalized_title, _normalized_url


def article(title: str, url: str, evergreen: bool = False) -> Article:
    return Article("9to5Mac", title, url, "", datetime.now(timezone.utc), is_evergreen=evergreen)


def record(title: str, url: str, evergreen: bool = False):
    return SimpleNamespace(title=title, source_url=url, is_evergreen=evergreen)


def test_same_story_with_different_tracking_parameters_is_blocked():
    history = [record("Fresh iPhone teaser", "https://example.com/story?utm_campaign=a")]
    assert _already_published(article("Different headline", "https://www.example.com/story?utm_source=b"), history)


def test_same_headline_is_blocked_after_sqlite_reset_or_feed_reordering():
    history = [record("MagSafe Monday: Pelican’s wallet", "render-log:2026-11-11-15")]
    assert _already_published(article("MAGSAFE MONDAY — PELICAN’S WALLET", "https://example.org/another"), history)


def test_evergreen_educational_tip_is_not_repeated():
    history = [record("iPhone: полезный совет", "https://support.apple.com/", True)]
    assert _already_published(article("iPhone: полезный совет", "https://support.apple.com/", True), history)


def test_new_topic_remains_publishable():
    history = [record("iPhone: полезный совет", "https://support.apple.com/", True)]
    assert not _already_published(article("MacBook: полезный совет", "https://support.apple.com/mac", True), history)


def test_normalizers_handle_unicode_and_querystrings():
    assert _normalized_title("  Apple’s — iPhone! ") == "apple s iphone"
    assert _normalized_url("https://www.EXAMPLE.COM/path/?utm_source=x") == "example.com/path"
