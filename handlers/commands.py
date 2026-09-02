import logging
from telegram import Update
from telegram.ext import ContextTypes

from database.db import Database
from bdpost.validator import validate_and_normalize_tracking_number

logger = logging.getLogger(__name__)


async def my_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id
    db: Database = context.bot_data["db"]

    trackings = db.get_user_active_trackings(telegram_id)

    if not trackings:
        await update.message.reply_text(
            "📦 You aren't tracking any parcels yet.\n\n"
            "Use:\n\n"
            "/track <tracking number>"
        )
        return

    message_lines = ["📦 Your tracked parcels\n"]

    for idx, item in enumerate(trackings, 1):
        num = item["tracking_number"]
        latest_event = db.get_latest_event_for_tracking(num)

        if latest_event:
            loc = latest_event.get("location", "N/A")
            status = latest_event.get("status", "N/A")
            message_lines.append(f"{idx}. {num}\n   📍 {loc}\n   📌 {status}\n")
        else:
            message_lines.append(f"{idx}. {num}\n   (Pending first update)\n")

    await update.message.reply_text("\n".join(message_lines))


import logging
from telegram import Update
from telegram.ext import ContextTypes

from database.db import Database
from bdpost.validator import extract_tracking_numbers

logger = logging.getLogger(__name__)


async def my_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id
    db: Database = context.bot_data["db"]

    trackings = db.get_user_active_trackings(telegram_id)

    if not trackings:
        await update.message.reply_text(
            "📦 You aren't tracking any parcels yet.\n\n"
            "Use:\n\n"
            "/track <tracking number>"
        )
        return

    message_lines = ["📦 Your tracked parcels\n"]

    for idx, item in enumerate(trackings, 1):
        num = item["tracking_number"]
        latest_event = db.get_latest_event_for_tracking(num)

        if latest_event:
            loc = latest_event.get("location", "N/A")
            status = latest_event.get("status", "N/A")
            message_lines.append(f"{idx}. {num}\n   📍 {loc}\n   📌 {status}\n")
        else:
            message_lines.append(f"{idx}. {num}\n   (Pending first update)\n")

    await update.message.reply_text("\n".join(message_lines))


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id
    db: Database = context.bot_data["db"]

    if not context.args:
        await update.message.reply_text(
            "❌ Please provide the tracking number(s) you wish to stop tracking, or use `/stop all`.\n\n"
            "Example:\n"
            "/stop UG251338889MV\n"
            "/stop UG251338889MV XX123456789BD\n"
            "/stop all"
        )
        return

    # Check for /stop all
    if len(context.args) == 1 and context.args[0].strip().lower() == "all":
        stopped_count = db.stop_all_trackings(telegram_id)
        if stopped_count > 0:
            await update.message.reply_text(
                f"🛑 Stopped tracking all {stopped_count} parcel(s).\n\n"
                "You will no longer receive notifications."
            )
        else:
            await update.message.reply_text("⚠️ You don't have any active parcel trackings.")
        return

    valid_numbers, invalid_numbers = extract_tracking_numbers(context.args)

    if invalid_numbers:
        invalid_list = ", ".join(invalid_numbers)
        await update.message.reply_text(
            f"⚠️ Invalid tracking number format: {invalid_list}"
        )

    if not valid_numbers:
        return

    stopped_list = []
    not_found_list = []

    for tracking_number in valid_numbers:
        stopped = db.stop_tracking(telegram_id, tracking_number)
        if stopped:
            stopped_list.append(tracking_number)
        else:
            not_found_list.append(tracking_number)

    response_lines = []
    if stopped_list:
        response_lines.append(f"🛑 Stopped tracking: {', '.join(stopped_list)}.")
    if not_found_list:
        response_lines.append(f"⚠️ Not actively tracking: {', '.join(not_found_list)}.")

    await update.message.reply_text("\n".join(response_lines))

