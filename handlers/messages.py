import logging
from telegram import Update
from telegram.ext import ContextTypes

from handlers.start import start_handler, help_handler
from handlers.commands import my_command, stop_command
from handlers.tracking import process_track_numbers, process_status_numbers
from handlers.keyboards import get_main_keyboard, get_cancel_keyboard
from bdpost.validator import extract_tracking_numbers

logger = logging.getLogger(__name__)


async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    state = context.user_data.get("state")

    # Handle Cancel
    if text in ["❌ Cancel", "cancel", "/cancel"]:
        context.user_data.pop("state", None)
        await update.message.reply_text(
            "Action cancelled.",
            reply_markup=get_main_keyboard()
        )
        return

    # Button: 📦 Track Parcel
    if text == "📦 Track Parcel":
        context.user_data["state"] = "waiting_for_track"
        await update.message.reply_text(
            "📦 *Track a Parcel:*\n\n"
            "Please send your tracking number(s) (e.g. `UG251350054MV`).\n"
            "You can enter multiple tracking numbers separated by spaces or commas.",
            reply_markup=get_cancel_keyboard(),
            parse_mode="Markdown"
        )
        return

    # Button: 🔍 Quick Status
    if text == "🔍 Quick Status":
        context.user_data["state"] = "waiting_for_status"
        await update.message.reply_text(
            "🔍 *Quick Status Check:*\n\n"
            "Please send the tracking number(s) to check immediate status without subscribing.",
            reply_markup=get_cancel_keyboard(),
            parse_mode="Markdown"
        )
        return

    # Button: 📋 My Parcels
    if text == "📋 My Parcels":
        context.user_data.pop("state", None)
        await my_command(update, context)
        return

    # Button: 🛑 Stop Tracking
    if text == "🛑 Stop Tracking":
        context.user_data.pop("state", None)
        await stop_command(update, context)
        return

    # Button: ℹ️ Help
    if text == "ℹ️ Help":
        context.user_data.pop("state", None)
        await help_handler(update, context)
        return

    # Handle State-driven input
    if state == "waiting_for_track":
        context.user_data.pop("state", None)
        await process_track_numbers(update, context, text)
        return

    if state == "waiting_for_status":
        context.user_data.pop("state", None)
        await process_status_numbers(update, context, text)
        return

    if state == "waiting_for_stop":
        context.user_data.pop("state", None)
        context.args = text.split()
        await stop_command(update, context)
        return

    # If not in a specific state, check if the input looks like tracking number(s)
    valid_numbers, invalid_numbers = extract_tracking_numbers(text)
    if valid_numbers and not invalid_numbers:
        # User directly pasted tracking number(s) -> Track them by default
        await process_track_numbers(update, context, valid_numbers)
        return

    # Fallback response
    await update.message.reply_text(
        "Please select an option from the menu below or send a valid tracking number:",
        reply_markup=get_main_keyboard()
    )
