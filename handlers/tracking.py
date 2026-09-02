import asyncio
import logging
from telegram import Update
from telegram.ext import ContextTypes

from database.db import Database
from bdpost.client import track, BangladeshPostUnavailableError
from bdpost.parser import parse_tracking_response, get_latest_event
from bdpost.validator import extract_tracking_numbers
from bdpost.formatter import format_status_message

logger = logging.getLogger(__name__)


async def track_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id
    db: Database = context.bot_data["db"]

    if not context.args:
        await update.message.reply_text(
            "❌ Please provide one or more tracking numbers.\n\n"
            "Example:\n"
            "/track UG251338889MV\n"
            "/track UG251338889MV XX123456789BD"
        )
        return

    valid_numbers, invalid_numbers = extract_tracking_numbers(context.args)

    if invalid_numbers:
        invalid_list = ", ".join(invalid_numbers)
        await update.message.reply_text(
            f"⚠️ Invalid tracking number format: {invalid_list}"
        )

    if not valid_numbers:
        return

    total = len(valid_numbers)
    if total > 1:
        await update.message.reply_text(f"🔍 Processing {total} tracking numbers...")

    for i, tracking_number in enumerate(valid_numbers):
        try:
            html = await track(tracking_number)
            events = parse_tracking_response(html)

            if not events:
                await update.message.reply_text(
                    f"🔎 No tracking information found for {tracking_number}."
                )
            else:
                # Save existing events as known events (no notification for historical events)
                db.save_events(tracking_number, events)
                db.update_last_checked(tracking_number)

                latest = get_latest_event(events)

                if latest and is_delivered(latest.get("status", "")):
                    # Parcel is already delivered: do not leave background tracking active
                    db.stop_tracking(telegram_id, tracking_number)
                    msg = (
                        f"🎉 Parcel {tracking_number} is already Delivered!\n\n"
                        f"{format_status_message(tracking_number, latest)}\n\n"
                        "Tracking is complete and will not be polled."
                    )
                else:
                    # Save active subscription
                    db.add_or_reactivate_tracking(telegram_id, tracking_number)
                    msg = (
                        f"✅ Subscribed to updates for {tracking_number}!\n\n"
                        f"{format_status_message(tracking_number, latest)}"
                    )
                await update.message.reply_text(msg)

        except BangladeshPostUnavailableError:
            await update.message.reply_text(
                f"⚠️ Bangladesh Post tracking is temporarily unavailable for {tracking_number}.\n"
                "I'll try again automatically later."
            )
        except Exception as e:
            logger.error("Unexpected error in /track for %s: %s", tracking_number, e, exc_info=True)
            await update.message.reply_text(
                f"⚠️ An unexpected error occurred while fetching details for {tracking_number}."
            )

        if i < total - 1:
            await asyncio.sleep(1.0)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text(
            "❌ Please provide one or more tracking numbers.\n\n"
            "Example:\n"
            "/status UG251338889MV\n"
            "/status UG251338889MV XX123456789BD"
        )
        return

    valid_numbers, invalid_numbers = extract_tracking_numbers(context.args)

    if invalid_numbers:
        invalid_list = ", ".join(invalid_numbers)
        await update.message.reply_text(
            f"⚠️ Invalid tracking number format: {invalid_list}"
        )

    if not valid_numbers:
        return

    total = len(valid_numbers)
    for i, tracking_number in enumerate(valid_numbers):
        try:
            html = await track(tracking_number)
            events = parse_tracking_response(html)

            if not events:
                await update.message.reply_text(
                    f"🔎 No tracking information found for {tracking_number}."
                )
            else:
                latest = get_latest_event(events)
                msg = format_status_message(tracking_number, latest)
                await update.message.reply_text(msg)

        except BangladeshPostUnavailableError:
            await update.message.reply_text(
                f"⚠️ Bangladesh Post tracking is temporarily unavailable for {tracking_number}."
            )
        except Exception as e:
            logger.error("Unexpected error in /status for %s: %s", tracking_number, e, exc_info=True)
            await update.message.reply_text(
                f"⚠️ An unexpected error occurred while checking status for {tracking_number}."
            )

        if i < total - 1:
            await asyncio.sleep(1.0)

