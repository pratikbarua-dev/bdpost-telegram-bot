import logging
from telegram import Update
from telegram.ext import ContextTypes

from database.db import Database
from bdpost.validator import extract_tracking_numbers, validate_and_normalize_tracking_number
from handlers.keyboards import (
    get_main_keyboard,
    get_cancel_keyboard,
    get_my_parcels_inline_keyboard,
    get_stop_all_confirm_keyboard
)
from handlers.cleanup import cleanup_previous_messages, record_prompt_message

logger = logging.getLogger(__name__)


async def my_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    await cleanup_previous_messages(update, context)
    context.user_data.pop("state", None)

    telegram_id = update.effective_user.id
    db: Database = context.bot_data["db"]

    trackings = db.get_user_active_trackings(telegram_id)

    if not trackings:
        msg = await update.message.reply_text(
            "📦 You aren't tracking any parcels yet.\n\n"
            "Tap *📦 Track Parcel* to add one!",
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown"
        )
        return

    message_lines = ["📦 *Your Active Parcels:*\n"]

    for idx, item in enumerate(trackings, 1):
        num = item["tracking_number"]
        label = item.get("label")
        latest_event = db.get_latest_event_for_tracking(num)

        title = f"*{label}* (`{num}`)" if label else f"`{num}`"

        if latest_event:
            loc = latest_event.get("location", "")
            loc_str = f"📍 {loc}\n   " if loc else ""
            status = latest_event.get("status", "N/A")
            src = "🇧🇩 BD Post" if latest_event.get("source") == "bdpost" else "🚚 Cainiao"
            message_lines.append(f"{idx}. {title} ({src})\n   {loc_str}📌 {status}\n")
        else:
            message_lines.append(f"{idx}. {title}\n   (Pending first update)\n")

    await update.message.reply_text(
        "\n".join(message_lines),
        reply_markup=get_my_parcels_inline_keyboard(trackings),
        parse_mode="Markdown"
    )


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    await cleanup_previous_messages(update, context)
    context.user_data.pop("state", None)

    telegram_id = update.effective_user.id
    db: Database = context.bot_data["db"]

    if not context.args:
        trackings = db.get_user_active_trackings(telegram_id)
        if not trackings:
            await update.message.reply_text(
                "⚠️ You don't have any active parcel trackings.",
                reply_markup=get_main_keyboard()
            )
            return

        context.user_data["state"] = "waiting_for_stop"
        prompt = await update.message.reply_text(
            "🛑 Please send the tracking number(s) to stop, or type `all` to stop all parcels:",
            reply_markup=get_cancel_keyboard(),
            parse_mode="Markdown"
        )
        record_prompt_message(context, prompt.message_id)
        return

    # Check for /stop all
    if len(context.args) == 1 and context.args[0].strip().lower() == "all":
        stopped_count = db.stop_all_trackings(telegram_id)
        if stopped_count > 0:
            await update.message.reply_text(
                f"🛑 Stopped tracking all {stopped_count} parcel(s).\n\n"
                "You will no longer receive notifications.",
                reply_markup=get_main_keyboard()
            )
        else:
            await update.message.reply_text(
                "⚠️ You don't have any active parcel trackings.",
                reply_markup=get_main_keyboard()
            )
        return

    valid_numbers, invalid_numbers = extract_tracking_numbers(context.args)

    if invalid_numbers:
        invalid_list = ", ".join(invalid_numbers)
        await update.message.reply_text(
            f"⚠️ Invalid tracking number format: {invalid_list}",
            reply_markup=get_main_keyboard()
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
        response_lines.append(f"🛑 Stopped tracking: `{', '.join(stopped_list)}`.")
    if not_found_list:
        response_lines.append(f"⚠️ Not actively tracking: `{', '.join(not_found_list)}`.")

    await update.message.reply_text(
        "\n".join(response_lines),
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )


async def name_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Usage: /name <tracking_number> <custom label>
    Example: /name UG251542831MV Mechanical Keyboard
    """
    if not update.effective_user or not update.message:
        return

    await cleanup_previous_messages(update, context)
    telegram_id = update.effective_user.id
    db: Database = context.bot_data["db"]

    if not context.args or len(context.args) < 2:
        prompt = await update.message.reply_text(
            "✏️ *Set Parcel Name:*\n\n"
            "Usage: `/name <tracking_number> <custom name>`\n"
            "Example: `/name UG251542831MV Mechanical Keyboard`\n\n"
            "Or tap *📋 My Parcels* and click ✏️ next to any parcel!",
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown"
        )
        record_prompt_message(context, prompt.message_id)
        return

    raw_tracking = context.args[0]
    tracking_number = validate_and_normalize_tracking_number(raw_tracking)
    custom_name = " ".join(context.args[1:]).strip()

    if not tracking_number:
        await update.message.reply_text("❌ Invalid tracking number.")
        return

    if custom_name.lower() in ["none", "clear", "remove"]:
        custom_name = None

    updated = db.set_parcel_label(telegram_id, tracking_number, custom_name)
    if updated:
        if custom_name:
            await update.message.reply_text(
                f"🏷️ Parcel `{tracking_number}` renamed to *{custom_name}*.",
                reply_markup=get_main_keyboard(),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"🏷️ Removed custom name for `{tracking_number}`.",
                reply_markup=get_main_keyboard(),
                parse_mode="Markdown"
            )
    else:
        await update.message.reply_text(
            f"⚠️ You are not actively tracking `{tracking_number}`.\n"
            "Track it first using `/track`.",
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown"
        )
