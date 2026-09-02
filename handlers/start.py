from telegram import Update
from telegram.ext import ContextTypes
from database.db import Database


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    db: Database = context.bot_data.get("db")
    if db:
        db.get_or_create_user(update.effective_user.id)

    await update.message.reply_text(
        "📦 Bangladesh Post Tracker\n\n"
        "Track your Bangladesh Post parcels and receive\n"
        "Telegram notifications when their status changes.\n\n"
        "Commands:\n\n"
        "/track <number1> [number2...] — Track one or more parcels\n"
        "/status <number1> [number2...] — Check current status\n"
        "/my — View all your tracked parcels\n"
        "/stop <number1> [number2...] — Stop tracking\n"
        "/stop all — Stop tracking all parcels\n\n"
        "/help"
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(
        "📦 Bangladesh Post Tracker — Help\n\n"
        "/track <tracking numbers> — Start tracking parcel(s) & receive updates\n"
        "/status <tracking numbers> — Check current status without subscribing\n"
        "/my — View all your tracked parcels\n"
        "/stop <tracking numbers> — Stop tracking parcel(s)\n"
        "/stop all — Stop tracking all parcels\n\n"
        "Multiple tracking numbers can be space or comma separated.\n\n"
        "Examples:\n"
        "/track UG251338889MV\n"
        "/track UG251338889MV XX123456789BD\n"
        "/status UG251338889MV, XX123456789BD"
    )
