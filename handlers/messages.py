import logging
from telegram import Update
from telegram.ext import ContextTypes

from handlers.start import start_handler, help_handler
from handlers.commands import my_command, stop_command
from handlers.tracking import process_track_numbers, process_status_numbers
from handlers.feedback import feedback_command, handle_feedback_message
from handlers.directory import postcode_command, execute_postcode_search, process_phone_report_submission
from handlers.keyboards import get_main_keyboard, get_cancel_keyboard
from handlers.cleanup import cleanup_previous_messages, record_prompt_message
from bdpost.validator import extract_tracking_numbers
from database.db import Database

logger = logging.getLogger(__name__)


async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text or not update.effective_user:
        return

    text = update.message.text.strip()
    state = context.user_data.get("state")
    telegram_id = update.effective_user.id
    db: Database = context.bot_data["db"]

    # Check for banned status
    if db.is_user_banned(telegram_id):
        return

    # Update user metadata
    db.get_or_create_user(
        telegram_id,
        username=update.effective_user.username,
        full_name=update.effective_user.full_name
    )

    # Handle Cancel & Home
    if text in ["❌ Cancel", "cancel", "/cancel", "🏠 Home", "🏠 Back to Home", "home", "/home"]:
        await cleanup_previous_messages(update, context)
        context.user_data.pop("state", None)
        context.user_data.pop("rename_tracking", None)
        await start_handler(update, context)
        return

    # Button: 📦 Track Parcel
    if text == "📦 Track Parcel":
        await cleanup_previous_messages(update, context)
        context.user_data["state"] = "waiting_for_track"
        prompt = await update.message.reply_text(
            "📦 <b>Track a Parcel:</b>\n\n"
            "Please send your tracking number(s) (e.g. <code>UG251542831MV</code> or <code>AP00839881455575</code>).\n"
            "You can enter multiple numbers separated by spaces or commas.",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
        record_prompt_message(context, prompt.message_id)
        return

    # Button: 🔍 Quick Status
    if text == "🔍 Quick Status":
        await cleanup_previous_messages(update, context)
        context.user_data["state"] = "waiting_for_status"
        prompt = await update.message.reply_text(
            "🔍 <b>Quick Status Check:</b>\n\n"
            "Please send the tracking number(s) to check immediate status without subscribing.",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
        record_prompt_message(context, prompt.message_id)
        return

    # Button: 📋 My Parcels
    if text == "📋 My Parcels":
        await cleanup_previous_messages(update, context)
        context.user_data.pop("state", None)
        await my_command(update, context)
        return

    # Button: 📮 Postcode & Offices
    if text in ["📮 Postcode & Offices", "📮 Postcode Finder", "postcode", "/postcode"]:
        await cleanup_previous_messages(update, context)
        await postcode_command(update, context)
        return

    # Button: 🛑 Stop Tracking
    if text == "🛑 Stop Tracking":
        await cleanup_previous_messages(update, context)
        context.user_data.pop("state", None)
        await stop_command(update, context)
        return

    # Button: 💬 Feedback
    if text == "💬 Feedback":
        await cleanup_previous_messages(update, context)
        await feedback_command(update, context)
        return

    # Button: ℹ️ Help
    if text == "ℹ️ Help":
        await cleanup_previous_messages(update, context)
        context.user_data.pop("state", None)
        await help_handler(update, context)
        return

    # Handle State-driven input
    if state == "waiting_for_postcode_query":
        await cleanup_previous_messages(update, context)
        context.user_data.pop("state", None)
        await execute_postcode_search(update, context, text)
        return

    if state == "waiting_for_phone_report":
        await process_phone_report_submission(update, context, text)
        return

    if state == "waiting_for_feedback":
        await handle_feedback_message(update, context, text)
        return

    if state == "waiting_for_track":
        await cleanup_previous_messages(update, context)
        context.user_data.pop("state", None)
        await process_track_numbers(update, context, text)
        return

    if state == "waiting_for_status":
        await cleanup_previous_messages(update, context)
        context.user_data.pop("state", None)
        await process_status_numbers(update, context, text)
        return

    if state == "waiting_for_stop":
        await cleanup_previous_messages(update, context)
        context.user_data.pop("state", None)
        context.args = text.split()
        await stop_command(update, context)
        return

    if state == "waiting_for_rename":
        await cleanup_previous_messages(update, context)
        context.user_data.pop("state", None)
        rename_tracking = context.user_data.pop("rename_tracking", None)

        if rename_tracking:
            custom_name = text if text.lower() not in ["none", "clear", "remove"] else None
            db.set_parcel_label(telegram_id, rename_tracking, custom_name)
            if custom_name:
                await update.message.reply_text(
                    f"🏷️ Parcel <code>{rename_tracking}</code> renamed to <b>{custom_name}</b>!",
                    reply_markup=get_main_keyboard(),
                    parse_mode="HTML"
                )
            else:
                await update.message.reply_text(
                    f"🏷️ Removed custom name for <code>{rename_tracking}</code>.",
                    reply_markup=get_main_keyboard(),
                    parse_mode="HTML"
                )
        return

    # If not in a specific state, check if the input looks like tracking number(s)
    valid_numbers, invalid_numbers = extract_tracking_numbers(text)
    if valid_numbers and not invalid_numbers:
        await cleanup_previous_messages(update, context)
        # User directly pasted tracking number(s) -> Track them by default
        await process_track_numbers(update, context, valid_numbers)
        return

    # Fallback response
    await update.message.reply_text(
        "Please select an option from the menu below or send a valid tracking number:",
        reply_markup=get_main_keyboard()
    )

