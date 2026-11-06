"""FastAPI entry point for running the Telegram bot on Render via webhook."""

import os
import logging
import hmac
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from app.crm_api import router as crm_router
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update

from app.bot.commands import setup_bot_commands
from app.config import settings
from app.database.database import close_db, init_db
from app.logging_config import setup_logging
from app.main import build_dispatcher

logger = logging.getLogger(__name__)
WEBHOOK_PATH = "/telegram/webhook"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()

    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    if not settings.GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY is not configured; AI replies will fail")
    logger.info(
        "AI configuration loaded (model=%s, api_key_configured=%s, timeout_seconds=%s)",
        settings.GEMINI_MODEL,
        bool(settings.GEMINI_API_KEY),
        settings.REQUEST_TIMEOUT_SECONDS,
    )

    await init_db()

    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = build_dispatcher()
    app.state.bot = bot
    app.state.dp = dp

    await setup_bot_commands(bot)

    # Scheduled publishing is handled only by the dedicated Render Cron Job.
    # Do not start a second in-process scheduler: overlapping deploys can duplicate posts.

    render_url = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    if not render_url:
        raise RuntimeError("RENDER_EXTERNAL_URL is not available")

    webhook_url = render_url + WEBHOOK_PATH

    # Webhook and polling are mutually exclusive. Registering the webhook
    # here makes the current deployment the single Telegram update consumer.
    await bot.set_webhook(
        url=webhook_url,
        allowed_updates=dp.resolve_used_update_types(),
        drop_pending_updates=False,
    )

    me = await bot.get_me()
    logger.info("Telegram webhook active for @%s at %s", me.username, webhook_url)

    try:
        yield
    finally:
        # Do not delete the webhook on SIGTERM: Render starts the new instance
        # before stopping the old one during a zero-downtime deployment.
        await bot.session.close()
        await close_db()


app = FastAPI(title="New iPhone Service", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["https://new-iphone-crm-preview.onrender.com"], allow_methods=["POST", "GET"], allow_headers=["Authorization", "Content-Type"])
app.include_router(crm_router)


@app.get("/")
async def root():
    return {"service": "New iPhone Service", "status": "ok", "transport": "telegram_webhook"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = Update.model_validate(data)
        await request.app.state.dp.feed_update(request.app.state.bot, update)
        return {"ok": True}
    except Exception as exc:
        logger.exception("Telegram webhook update failed")
        raise HTTPException(status_code=400, detail="Invalid Telegram update") from exc


@app.post("/news/publish-next")
async def publish_next_channel_news(request: Request):
    """Authenticated endpoint invoked by the Render cron scheduler."""
    configured_secret = settings.NEWS_PUBLISH_SECRET
    supplied_secret = request.headers.get("X-News-Publish-Secret", "")
    if not configured_secret or not hmac.compare_digest(configured_secret, supplied_secret):
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    slot_key = str(payload.get("slot_key") or request.headers.get("X-News-Slot", "")).strip()
    if not slot_key or len(slot_key) > 80:
        raise HTTPException(status_code=400, detail="Missing or invalid slot_key")

    from app.news.publisher import publish_next_news
    try:
        result = await publish_next_news(request.app.state.bot, slot_key)
        return result
    except Exception as exc:
        logger.exception("Scheduled channel news publication failed for slot %s", slot_key)
        raise HTTPException(status_code=500, detail="News publication failed") from exc



# Private bridge to the Neon CRM. Never expose Telegram tokens or customer data to a browser.
# The shared secret is set independently for the CRM and bot services in Render.
def require_crm_bridge(request: Request):
    configured=os.getenv("CRM_BRIDGE_SECRET","")
    provided=request.headers.get("X-CRM-Bridge-Secret","")
    if not configured or len(configured)<48 or not hmac.compare_digest(configured,provided):
        raise HTTPException(403,"Forbidden")

class CRMPrivateMessage(BaseModel):
    chat_id: int = Field(gt=0)
    text: str = Field(min_length=1,max_length=3500)

@app.get("/internal/crm/health")
async def crm_bridge_health(request: Request):
    require_crm_bridge(request)
    return {"ok":True,"telegram":bool(settings.TELEGRAM_BOT_TOKEN),
            "voice":bool(settings.GEMINI_API_KEY)}

@app.post("/internal/crm/voice-extract")
async def crm_bridge_extract(request: Request):
    require_crm_bridge(request)
    from app.crm_api import bounded_json,extract_finance
    payload=await bounded_json(request)
    return await extract_finance(payload)

@app.post("/internal/crm/telegram-send")
async def crm_bridge_telegram_send(request: Request,payload:CRMPrivateMessage):
    require_crm_bridge(request)
    from aiogram.exceptions import TelegramBadRequest,TelegramForbiddenError,TelegramRetryAfter
    try:
        chat=await request.app.state.bot.get_chat(payload.chat_id)
        if chat.type!="private":
            raise HTTPException(422,"Messages allowed only to verified private conversations")
        result=await request.app.state.bot.send_message(
            chat_id=payload.chat_id,text=payload.text,parse_mode=None)
        return {"ok":True,"message_id":str(result.message_id)}
    except HTTPException:
        raise
    except (TelegramBadRequest,TelegramForbiddenError) as exc:
        logger.warning("CRM Telegram delivery rejected by Telegram")
        raise HTTPException(422,"Telegram recipient cannot be reached") from None
    except TelegramRetryAfter as exc:
        raise HTTPException(429,"Telegram rate limit") from None
    except Exception as exc:
        logger.warning("CRM Telegram delivery outcome unknown")
        raise HTTPException(502,"Telegram delivery outcome could not be confirmed") from None
