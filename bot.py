import asyncio
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import Conflict, NetworkError, TelegramError

import config
from database.db import Database
from handlers.start import start_handler, help_handler
from handlers.tracking import track_command, status_command
from handlers.commands import my_command, stop_command, name_command
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


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Global error handler for telegram exceptions.
    """
    if isinstance(context.error, Conflict):
        logger.warning(
            "Conflict detected: Another instance of this bot is running with the same BOT_TOKEN. "
            "If you recently redeployed on Render or have the bot running on PythonAnywhere / locally, "
            "please stop the old instance."
        )
    elif isinstance(context.error, NetworkError):
        logger.warning("Telegram network error: %s", context.error)
    else:
        logger.error("Exception while handling an update: %s", context.error, exc_info=context.error)


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

    # Register error handler
    application.add_error_handler(error_handler)

    # Command Handlers
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("home", start_handler))
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(CommandHandler("track", track_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("my", my_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("name", name_command))
    application.add_handler(CommandHandler("rename", name_command))

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
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()


