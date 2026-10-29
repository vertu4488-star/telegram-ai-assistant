"""On-demand reference price lookup for Apple repair services from appservice.ru.

The source site is a third-party service in Saint Petersburg. Its prices are used as
the owner's chosen reference tariff; battery replacement prices are reduced by 20%.
Only fetch pages when a customer asks about repair prices, and cache results briefly.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Optional
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE = "https://appservice.ru"
ROOTS = {
    "iphone": ["/services/remont-iphone"],
    "ipad": ["/services/ipad-pro", "/services/ipad-air", "/services/ipad", "/services/ipad-mini"],
    "macbook": ["/services/remont-macbook-air", "/services/remont-macbook-pro"],
}
CACHE_SECONDS = 6 * 60 * 60
_TIMEOUT = aiohttp.ClientTimeout(total=12, connect=5)
_cache: dict[str, tuple[float, str]] = {}
_lock = asyncio.Lock()

PRICE_INTENT = re.compile(r"цен|сколько стоит|стоимость|прайс|по деньгам|обойд[её]тся|замен[аи]|ремонт|аккумулятор|батаре|экран|диспле|стекл|разъ[её]м|клавиатур|топкейс", re.I)
BATTERY_WORDS = re.compile(r"аккумулятор|батаре", re.I)
DEVICE_WORDS = re.compile(r"iphone|айфон|ipad|айпад|mac\s?book|макбук", re.I)
MONEY = re.compile(r"(?<!\w)(\d[\d\s\u00a0]*(?:[.,]\d{1,2})?)\s*(?:₽|руб(?:\.|лей|ля|ль)?)", re.I)


def _norm(value: str) -> str:
    return re.sub(r"[^a-zа-я0-9]+", "", value.lower().replace("ё", "е"))


def _family(prompt: str) -> Optional[str]:
    p = prompt.lower().replace("ё", "е")
    if re.search(r"iphone|айфон", p):
        return "iphone"
    if re.search(r"ipad|айпад", p):
        return "ipad"
    if re.search(r"mac\s?book|макбук", p):
        return "macbook"
    return None


def _model_hint(prompt: str, family: str) -> str:
    # Keep the customer's original wording; matching will use both English/Russian aliases.
    return prompt.strip()[:180]


async def _get(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    try:
        async with session.get(url, headers={"User-Agent": "NewIphoneServiceBot/1.0 (repair price lookup)"}) as response:
            if response.status != 200:
                logger.warning("Price source returned HTTP %s for %s", response.status, url)
                return None
            ctype = response.headers.get("content-type", "")
            if "html" not in ctype.lower():
                return None
            return await response.text(errors="replace")
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        logger.warning("Could not fetch price source %s: %s", url, exc)
        return None


def _candidate_links(html: str, root_url: str, family: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        label = " ".join(a.get_text(" ", strip=True).split())
        href = urljoin(root_url, str(a.get("href", "")))
        parsed = urlparse(href)
        if parsed.netloc != urlparse(BASE).netloc or not parsed.path.startswith("/services/"):
            continue
        path = parsed.path.rstrip("/")
        if path == urlparse(root_url).path.rstrip("/"):
            continue
        candidate_text = f"{label} {path}".lower()
        if family == "iphone" and ("iphone" in candidate_text or "айфон" in candidate_text):
            found[href] = label or path.rsplit("/", 1)[-1]
        elif family == "ipad" and ("ipad" in candidate_text or "айпад" in candidate_text):
            found[href] = label or path.rsplit("/", 1)[-1]
        elif family == "macbook" and ("macbook" in candidate_text or "macbook" in path.lower()):
            found[href] = label or path.rsplit("/", 1)[-1]

    # Some model selectors are HTML <option value="/services/..."> elements.
    for option in soup.find_all("option", value=True):
        label = " ".join(option.get_text(" ", strip=True).split())
        href = urljoin(root_url, str(option.get("value", "")))
        parsed = urlparse(href)
        candidate_text = f"{label} {parsed.path}".lower()
        if parsed.netloc == urlparse(BASE).netloc and parsed.path.startswith("/services/"):
            if family == "iphone" and "iphone" in candidate_text:
                found[href] = label or parsed.path.rsplit("/", 1)[-1]
            elif family == "ipad" and "ipad" in candidate_text:
                found[href] = label or parsed.path.rsplit("/", 1)[-1]
            elif family == "macbook" and "macbook" in candidate_text:
                found[href] = label or parsed.path.rsplit("/", 1)[-1]
    return list(found.items())


def _score(query: str, label: str, url: str) -> int:
    q = _norm(query)
    candidate = _norm(label + " " + url)
    if q and q in candidate:
        return 100 + len(q)
    # Weight model-specific numbers and modifiers over generic family names.
    tokens = re.findall(r"[a-z]+|[0-9]+|pro|max|mini|air|plus|ultra|m[1-9]", query.lower())
    tokens = [t for t in tokens if t not in {"iphone", "айфон", "ipad", "айпад", "macbook", "макбук", "ремонт", "замена", "стоимость", "сколько", "цена", "цену", "аккумулятора", "батареи"}]
    return sum(3 if len(t) > 1 and t in candidate else 0 for t in tokens)


def _extract_price_cards(html: str, page_url: str, prompt: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    cards: list[str] = []
    seen: set[str] = set()

    # Price cards are headed by h2/h3/h4 on the model pages. Walk up from each
    # heading until we find a compact block containing a ruble amount.
    for heading in soup.find_all(re.compile(r"^h[2-5]$")):
        title = " ".join(heading.get_text(" ", strip=True).split())
        if not title or len(title) > 180:
            continue
        node = heading
        chosen_text = ""
        for _ in range(6):
            node = node.parent
            if not node:
                break
            text = " ".join(node.get_text(" ", strip=True).split())
            if MONEY.search(text) and len(text) <= 1000:
                chosen_text = text
                break
        if not chosen_text:
            # The price may be in a sibling rather than an ancestor card.
            pieces = [title]
            for sibling in heading.find_all_next(limit=12):
                if getattr(sibling, "name", None) in {"h2", "h3", "h4", "h5"}:
                    break
                t = " ".join(sibling.get_text(" ", strip=True).split()) if hasattr(sibling, "get_text") else ""
                if t:
                    pieces.append(t)
            chosen_text = " ".join(pieces)
        amounts = list(MONEY.finditer(chosen_text))
        if not amounts:
            continue
        # Keep the shortest useful description from the card to avoid whole-page noise.
        cleaned = re.sub(r"\s+", " ", chosen_text).strip()
        if len(cleaned) > 360:
            cleaned = cleaned[:357] + "..."
        if cleaned in seen:
            continue
        seen.add(cleaned)

        if BATTERY_WORDS.search(title) or BATTERY_WORDS.search(cleaned):
            # Apply -20% only to the first listed service price for battery replacement.
            m = MONEY.search(cleaned)
            if m:
                raw = re.sub(r"[\s\u00a0]", "", m.group(1)).replace(",", ".")
                try:
                    discounted = round(float(raw) * 0.8, 2)
                    if discounted.is_integer():
                        formatted = f"{int(discounted):,}".replace(",", " ")
                    else:
                        formatted = f"{discounted:,.2f}".replace(",", " ").replace(".", ",")
                    cleaned = cleaned[:m.start(1)] + formatted + cleaned[m.end(1):]
                    cleaned += " [цена аккумулятора уже уменьшена на 20%]"
                except ValueError:
                    pass
        cards.append(cleaned)

    # Some listing pages show only broad starting prices in a table, without cards.
    if not cards:
        text = " ".join(soup.get_text(" ", strip=True).split())
        for match in re.finditer(r"[^.]{0,100}(?:замена|ремонт)[^.]{0,100}\d[\d\s\u00a0]*(?:₽|руб(?:\.|лей|ля|ль)?)[^.]{0,60}", text, re.I):
            snippet = match.group(0).strip()
            if BATTERY_WORDS.search(snippet):
                m = MONEY.search(snippet)
                if m:
                    try:
                        raw = float(re.sub(r"[\s\u00a0]", "", m.group(1)).replace(",", "."))
                        discount = round(raw * 0.8)
                        snippet = snippet[:m.start(1)] + f"{discount:,}".replace(",", " ") + snippet[m.end(1):]
                        snippet += " [цена аккумулятора уже уменьшена на 20%]"
                    except ValueError:
                        pass
            if snippet not in seen:
                seen.add(snippet)
                cards.append(snippet)

    return cards[:35]


async def get_price_context(prompt: str) -> str:
    """Return relevant model-specific price context, or an honest unavailable note."""
    if not PRICE_INTENT.search(prompt) or not DEVICE_WORDS.search(prompt):
        return ""
    family = _family(prompt)
    if not family:
        return ""
    cache_key = f"{family}:{_norm(prompt)}"
    now = time.time()
    cached = _cache.get(cache_key)
    if cached and now - cached[0] < CACHE_SECONDS:
        return cached[1]

    async with _lock:
        cached = _cache.get(cache_key)
        if cached and time.time() - cached[0] < CACHE_SECONDS:
            return cached[1]
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            candidates: dict[str, str] = {}
            root_texts: list[str] = []
            for path in ROOTS[family]:
                root_url = urljoin(BASE, path)
                html = await _get(session, root_url)
                if not html:
                    continue
                root_texts.append(html)
                for url, label in _candidate_links(html, root_url, family):
                    candidates[url] = label

            ranked = sorted(
                (( _score(prompt, label, url), url, label) for url, label in candidates.items()),
                reverse=True,
            )
            if ranked and ranked[0][0] > 0:
                best_score = ranked[0][0]
                # Fetch the best model page and, if ambiguous, one close alternative.
                selected = [(score, url, label) for score, url, label in ranked if score >= max(3, best_score - 2)][:2]
                results: list[str] = []
                for score, url, label in selected:
                    html = await _get(session, url)
                    if not html:
                        continue
                    cards = _extract_price_cards(html, url, prompt)
                    if cards:
                        results.append(f"Модель/страница: {label}\nИсточник: {url}\n" + "\n".join(f"- {card}" for card in cards))
                if results:
                    context = (
                        "ПРАЙС ДЛЯ ОТВЕТА КЛИЕНТУ (получен с appservice.ru). "
                        "Цены аккумуляторов уже уменьшены на 20%.\n"
                        + "\n\n".join(results)
                    )
                    _cache[cache_key] = (time.time(), context)
                    return context

            # Do not invent a price if the model-specific page could not be resolved.
            context = (
                "В прайсе appservice.ru не удалось автоматически найти точную цену для указанной модели. "
                "Не придумывай цену и не переноси цену с другой модели. Скажи, что мастер уточнит стоимость "
                "по точной модели/номеру Axxxx. Если клиент ещё не указал модель, задай один короткий вопрос."
            )
            _cache[cache_key] = (time.time(), context)
            return context
