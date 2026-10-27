"""FastAPI entry point for running the Telegram bot on Render via webhook."""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
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

    await init_db()

    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = build_dispatcher()
    app.state.bot = bot
    app.state.dp = dp

    await setup_bot_commands(bot)

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
