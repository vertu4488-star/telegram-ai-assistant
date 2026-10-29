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
from zoneinfo import ZoneInfo
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
    ("MacRumors", "https://feeds.macrumors.com/MacRumors-All"),
    ("9to5Mac", "https://9to5mac.com/feed/"),
    ("AppleInsider", "https://appleinsider.com/rss/news/"),
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

    prompt = f"""Ты — редактор русскоязычного Telegram-канала New iPhone Service о смартфонах, Apple, ремонте и технологиях. Канал должен быть полезным и живым, а не лентой безличных пересказов.

Правила публикации:
- Пиши только на русском языке, естественно, уверенно и без канцелярита. Не начинай с приветствия и не представляйся.
- Выбери подходящий формат по теме: новость с объяснением последствий; короткий разбор «что это значит для владельца»; практический совет; «миф или факт»; чек-лист; осторожный прогноз; редакционный комментарий.
- Начни с ясного, цепляющего заголовка. Затем 2–5 коротких абзацев, удобных для чтения с телефона.
- Помимо пересказа добавь полезный редакционный вывод: что в новости действительно важно, на что стоит обратить внимание или что мы считаем разумным решением. Если это мнение, обозначь его словами «Наш взгляд:» или «Что думаем:» — не выдавай мнение за установленный факт.
- Не изображай личный опыт реального тестирования или ремонта, если он не указан в исходных данных. Не выдумывай опыт мастеров, отзывы клиентов, статистику, цены, сроки, наличие деталей, характеристики, даты или цитаты.
- Используй только факты из материала. Если данных мало, прямо обозначь неопределённость и не додумывай детали.
- Если это слух или неподтверждённое сообщение, прямо назови его слухом/сообщением СМИ. Не превращай предположения в подтверждённые новости.
- Для справочных публикаций давай конкретный безопасный совет, который читатель может применить. Не советуй опасный самостоятельный ремонт и не обещай, что один симптом точно указывает на конкретную поломку.
- Мягко связывай тему с заботой о технике и грамотной диагностикой, но не превращай каждый пост в рекламу сервиса.
- В части публикаций заверши одним простым вопросом по теме, чтобы подписчикам было легко ответить. Не добавляй вопрос механически, если он выглядит неестественно.
- Не повторяй ссылку в тексте: источник будет добавлен отдельно.
- Длина 600–1100 знаков. Не более 3 уместных хештегов в конце; если они не нужны, не добавляй их.
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
            logger.warning("News text generation failed on %s (%s): %r", model, type(exc).__name__, exc)
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


async def run_news_scheduler(bot: Bot) -> None:
    """Best-effort in-process scheduler; Render Cron can call the same publisher reliably."""
    timezone_local = ZoneInfo("Asia/Novosibirsk")
    scheduled_hours = (10, 15, 20)
    logger.info("In-process news scheduler started (Asia/Novosibirsk, slots=%s)", scheduled_hours)
    while True:
        try:
            now = datetime.now(timezone_local)
            due_hours = [hour for hour in scheduled_hours if now.hour >= hour]
            if due_hours:
                # Publish only the latest due slot after a wake/restart, avoiding a burst of backlogged posts.
                hour = due_hours[-1]
                slot_key = f"{now:%Y-%m-%d}-{hour:02d}"
                if await _published_slot(slot_key) is None:
                    logger.info("News slot due: %s", slot_key)
                    try:
                        await publish_next_news(bot, slot_key)
                    except Exception:
                        logger.exception("Scheduled news post failed for slot %s; will retry", slot_key)
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            logger.info("In-process news scheduler stopped")
            raise
        except Exception:
            logger.exception("Unexpected news scheduler error")
            await asyncio.sleep(60)
