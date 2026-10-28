"""Curated RSS news collector and Telegram channel publisher."""
from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import urlparse

from aiogram import Bot
from aiogram.types import LinkPreviewOptions
from google.genai import types
from sqlalchemy import select

from app.config import settings
from app.database.database import get_db_session
from app.database.models import PublishedNews
from app.ai.gemini import gemini_service

logger = logging.getLogger(__name__)

# Primary sources and established technology publications. We link to original
# articles and rely on Telegram's native preview rather than re-uploading media.
FEEDS: tuple[tuple[str, str], ...] = (
    ("Apple Newsroom", "https://www.apple.com/newsroom/rss-feed.rss"),
    ("Apple Developer", "https://developer.apple.com/news/rss/news.rss"),
    ("9to5Mac", "https://9to5mac.com/feed/"),
    ("MacRumors", "https://feeds.macrumors.com/MacRumors-All"),
    ("AppleInsider", "https://appleinsider.com/rss/news/"),
    ("The Verge", "https://www.theverge.com/rss/index.xml"),
    ("Android Authority", "https://www.androidauthority.com/feed/"),
    ("GSMArena", "https://www.gsmarena.com/rss-news-reviews.php3"),
    ("Samsung Newsroom", "https://news.samsung.com/global/feed"),
)

KEYWORDS = (
    "iphone", "ipad", "macbook", "imac", "mac mini", "mac studio", "macos",
    "ios", "apple watch", "watchos", "apple intelligence", "airpods", "apple",
    "samsung", "galaxy", "android", "pixel", "xiaomi", "oneplus", "huawei",
    "smartphone", "smartwatch", "foldable", "phone", "laptop", "chip",
    "processor", "wearable",
)

EVERGREEN_TOPICS = (
    ("iPhone", "Как правильно проверять состояние аккумулятора iPhone и какие показатели действительно важны.", "https://support.apple.com/"),
    ("MacBook", "Что проверить перед покупкой подержанного MacBook: аккумулятор, дисплей, порты, блокировка активации и история ремонта.", "https://support.apple.com/mac"),
    ("Apple Watch", "Как продлить время работы Apple Watch: настройки экрана, фоновые обновления и проверка состояния аккумулятора.", "https://support.apple.com/watch"),
    ("USB-C", "Почему один кабель USB-C может заряжать устройство, а другой — нет: мощность адаптера, поддерживаемые режимы и состояние разъёмов.", "https://support.apple.com/"),
    ("Samsung Galaxy", "Что проверить перед обновлением смартфона: резервную копию, свободную память, заряд аккумулятора и стабильность Wi-Fi.", "https://www.samsung.com/support/"),
    ("Безопасность", "Почему важно устанавливать системные обновления и как проверить, доступна ли новая версия ОС для устройства.", "https://support.apple.com/"),
    ("Ремонт", "Почему симптомы неисправности не всегда указывают на конкретную микросхему: надёжная диагностика начинается с измерений и исключения простых причин.", "https://support.apple.com/"),
    ("Покупка техники", "На что смотреть при выборе зарядного устройства: совместимость, заявленная мощность, качество кабеля и защита от перегрева.", "https://www.samsung.com/support/"),
    ("Фото и видео", "Как освободить память телефона без потери важных снимков: резервное копирование, проверка синхронизации и удаление дубликатов.", "https://support.apple.com/"),
)

@dataclass(frozen=True)
class Article:
    source: str
    title: str
    url: str
    summary: str
    published_at: datetime
    is_evergreen: bool = False


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _parse_date(value: str | None) -> datetime:
    if value:
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except (TypeError, ValueError, OverflowError):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except (TypeError, ValueError, OverflowError):
                pass
    return datetime.now(timezone.utc) - timedelta(days=3)


def _fetch_feed(feed_name: str, feed_url: str) -> list[Article]:
    request = urllib.request.Request(
        feed_url,
        headers={"User-Agent": "NewIphoneServiceNewsBot/1.0 (+https://t.me/New_Iphone_Service)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read(2_500_000)
        root = ET.fromstring(raw)
    except Exception as exc:
        logger.warning("News feed unavailable (%s): %s", feed_name, exc)
        return []

    result: list[Article] = []
    for node in root.iter():
        if _local_name(node.tag) not in ("item", "entry"):
            continue
        fields: dict[str, str] = {}
        for child in list(node):
            name = _local_name(child.tag)
            value = child.text or ""
            if name == "link" and not value:
                value = child.attrib.get("href", "")
            if name in ("content", "encoded", "summary", "description", "subtitle") and not value:
                value = "".join(child.itertext())
            if name not in fields or (not fields[name] and value):
                fields[name] = value

        title = _clean_text(fields.get("title"))
        url = (fields.get("link") or fields.get("guid") or "").strip()
        if not title or not url.startswith(("https://", "http://")):
            continue
        summary = _clean_text(
            fields.get("summary") or fields.get("description") or
            fields.get("encoded") or fields.get("content")
        )
        published = _parse_date(
            fields.get("pubdate") or fields.get("published") or
            fields.get("updated") or fields.get("date")
        )
        result.append(Article(feed_name, title, url, summary[:2500], published))
    return result


async def _collect_articles() -> list[Article]:
    results = await asyncio.gather(
        *(asyncio.to_thread(_fetch_feed, name, url) for name, url in FEEDS),
        return_exceptions=True,
    )
    articles: list[Article] = []
    for result in results:
        if isinstance(result, list):
            articles.extend(result)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=72)
    unique: dict[str, Article] = {}
    for article in articles:
        title_lower = article.title.lower()
        if article.published_at < cutoff:
            continue
        if not any(word in title_lower for word in KEYWORDS):
            continue
        key = article.url.rstrip("/")
        unique.setdefault(key, article)
    return sorted(unique.values(), key=lambda item: item.published_at, reverse=True)


async def _already_published(url: str) -> bool:
    async with get_db_session() as session:
        row = await session.scalar(
            select(PublishedNews.id).where(
                PublishedNews.source_url == url,
                PublishedNews.is_evergreen.is_(False),
            ).limit(1)
        )
        return row is not None


async def _published_slot(slot_key: str) -> Optional[PublishedNews]:
    async with get_db_session() as session:
        return await session.scalar(
            select(PublishedNews).where(PublishedNews.slot_key == slot_key).limit(1)
        )


async def _generate_post(article: Article) -> str:
    if article.is_evergreen:
        facts = (
            f"Рубрика: {article.source}\nТема: {article.title}\n"
            f"Основа материала: {article.summary}\nСсылка на справочный источник: {article.url}"
        )
    else:
        facts = (
            f"Источник: {article.source}\nЗаголовок оригинала: {article.title}\n"
            f"Дата публикации: {article.published_at.isoformat()}\n"
            f"Описание из RSS: {article.summary or '(описание в RSS отсутствует)'}\n"
            f"Оригинальная ссылка: {article.url}"
        )

    prompt = f"""Подготовь публикацию для русскоязычного Telegram-канала New iPhone Service о смартфонах и технике.

Правила:
- Пиши только на русском языке, естественно и профессионально.
- Не начинай с приветствия и не представляйся.
- Создай оригинальный пересказ, не копируй исходную статью дословно.
- Начни с короткого цепляющего заголовка, затем 2–4 коротких абзаца.
- Объясни, что произошло и почему это важно владельцам техники.
- Используй только факты из предоставленных данных. Не выдумывай характеристики, даты, цены, тесты или цитаты.
- Если это слух или неподтверждённое сообщение, явно назови его слухом/сообщением СМИ, а не подтверждённым фактом.
- Не повторяй ссылку в тексте: источник будет добавлен отдельно.
- Длина 500–900 знаков, максимум 3 подходящих хештега в конце.
- Для справочного материала давай практичный совет, без рекламных обещаний и выдуманных данных.
- Верни только готовый текст публикации, без пояснений редактору.

Материал:
{facts}"""

    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured for channel publishing")

    client = gemini_service.client
    models = [settings.GEMINI_MODEL]
    if settings.GEMINI_FALLBACK_MODEL and settings.GEMINI_FALLBACK_MODEL not in models:
        models.append(settings.GEMINI_FALLBACK_MODEL)
    last_error: Exception | None = None
    for model in models:
        try:
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(temperature=0.35),
                ),
                timeout=min(settings.REQUEST_TIMEOUT_SECONDS, 45),
            )
            text = (getattr(response, "text", None) or "").strip()
            if text:
                return text[:3500]
            last_error = RuntimeError(f"Empty Gemini response from {model}")
        except Exception as exc:
            last_error = exc
            logger.warning("News text generation failed on %s: %s", model, exc)
    raise RuntimeError(f"All Gemini models failed for news post: {last_error}")


async def publish_next_news(bot: Bot, slot_key: str) -> dict[str, object]:
    """Publish one source-linked news post, or a useful evergreen post if feeds are quiet."""
    if not settings.NEWS_CHANNEL_USERNAME:
        raise RuntimeError("NEWS_CHANNEL_USERNAME is not configured")
    if not slot_key or len(slot_key) > 80:
        raise ValueError("A valid news publication slot key is required")

    existing_slot = await _published_slot(slot_key)
    if existing_slot:
        return {"status": "already_published", "slot_key": slot_key, "title": existing_slot.title}

    articles = await _collect_articles()
    article: Article | None = None
    for candidate in articles:
        if not await _already_published(candidate.url):
            article = candidate
            break

    if article is None:
        # Deterministic rotation ensures a useful post even on a quiet news day.
        index = int(hashlib.sha256(slot_key.encode("utf-8")).hexdigest(), 16) % len(EVERGREEN_TOPICS)
        category, advice, source_url = EVERGREEN_TOPICS[index]
        article = Article(
            source=f"Практика New iPhone Service · {category}",
            title=f"{category}: полезный совет",
            url=source_url,
            summary=advice,
            published_at=datetime.now(timezone.utc),
            is_evergreen=True,
        )

    post_text = await _generate_post(article)
    source_line = f"\n\nИсточник: {article.source}\n{article.url}"
    final_text = (post_text + source_line)[:3900]

    await bot.send_message(
        chat_id=settings.NEWS_CHANNEL_USERNAME,
        text=final_text,
        parse_mode=None,
        link_preview_options=LinkPreviewOptions(is_disabled=False, prefer_large_media=True),
    )

    async with get_db_session() as session:
        session.add(
            PublishedNews(
                slot_key=slot_key,
                source_url=article.url,
                title=article.title[:500],
                source_name=article.source[:200],
                published_at=datetime.now(timezone.utc),
                is_evergreen=article.is_evergreen,
            )
        )

    logger.info(
        "News post published: slot=%s source=%s evergreen=%s title=%s",
        slot_key, article.source, article.is_evergreen, article.title,
    )
    return {
        "status": "published",
        "slot_key": slot_key,
        "title": article.title,
        "source": article.source,
        "evergreen": article.is_evergreen,
    }
