import os
import asyncio
import logging
from aiohttp import web

logger = logging.getLogger(__name__)


async def handle_ping(request):
    return web.json_response({
        "status": "pong",
        "service": "bdpost-telegram-bot",
        "healthy": True
    }, status=200)


async def handle_health(request):
    return web.Response(text="Bangladesh Post Telegram Bot is running OK", status=200)


async def start_health_server(port: int = None) -> None:
    """
    Runs a lightweight HTTP server on the PORT assigned by Render/hosting provider.
    Provides /ping, /health, and / endpoints for uptime monitoring services
    (e.g., UptimeRobot, Cron-job.org, BetterStack) to keep the bot active 24/7.
    """
    if port is None:
        port = int(os.getenv("PORT", "10000"))

    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/ping", handle_ping)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Web & Ping server running on port %d with endpoints: /, /health, /ping", port)

