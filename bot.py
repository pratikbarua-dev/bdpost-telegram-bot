import asyncio
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

import config
from database.db import Database
from handlers.start import start_handler, help_handler
from handlers.tracking import track_command, status_command
from handlers.commands import my_command, stop_command
from handlers.messages import message_router
from handlers.callbacks import callback_query_handler
from scheduler.checker import check_all_trackings
from server import start_health_server

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
# Reduce noisy logs from httpx / urllib3
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    # Start web server for Render health check compatibility
    asyncio.create_task(start_health_server())


def main() -> None:
    logger.info("Initializing Bangladesh Post Telegram Bot...")

    # Initialize Database
    db = Database(config.DATABASE_PATH)

    # Initialize Application
    application = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    application.bot_data["db"] = db

    # Command Handlers
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(CommandHandler("track", track_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("my", my_command))
    application.add_handler(CommandHandler("stop", stop_command))

    # Inline Button Callback Handler
    application.add_handler(CallbackQueryHandler(callback_query_handler))

    # Text & Menu Message Handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))

    # JobQueue Scheduler
    job_queue = application.job_queue
    if job_queue is not None:
        job_queue.run_repeating(
            check_all_trackings,
            interval=config.POLL_INTERVAL,
            first=10
        )
        logger.info("Scheduled background checker every %d seconds.", config.POLL_INTERVAL)
    else:
        logger.warning("JobQueue not initialized. Make sure python-telegram-bot[job-queue] is installed.")

    logger.info("Bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

