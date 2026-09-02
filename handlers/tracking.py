import asyncio
import logging
from telegram import Update
from telegram.ext import ContextTypes

from database.db import Database
from bdpost.client import track as track_bdpost, BangladeshPostUnavailableError
from bdpost.parser import parse_tracking_response as parse_bdpost, get_latest_event, is_delivered, is_bdpost_handover_event
from bdpost.validator import extract_tracking_numbers
from bdpost.formatter import format_status_message
from cainiao.client import track as track_cainiao, CainiaoUnavailableError, CainiaoError
from cainiao.parser import parse_tracking_response as parse_cainiao
from handlers.keyboards import get_main_keyboard, get_parcel_inline_keyboard

logger = logging.getLogger(__name__)


async def fetch_tracking_sources(tracking_number: str) -> tuple[list[dict], list[dict]]:
    """
    Queries both Cainiao (AliExpress) and Bangladesh Post concurrently.
    Returns (cainiao_events, bdpost_events).
    """
    cainiao_task = asyncio.create_task(track_cainiao(tracking_number))
    bdpost_task = asyncio.create_task(track_bdpost(tracking_number))

    cainiao_events = []
    bdpost_events = []

    try:
        cainiao_data = await cainiao_task
        cainiao_events = parse_cainiao(cainiao_data)
    except Exception as e:
        logger.debug("Cainiao fetch for %s returned: %s", tracking_number, e)

    try:
        bdpost_html = await bdpost_task
        bdpost_events = parse_bdpost(bdpost_html)
    except Exception as e:
        logger.debug("BD Post fetch for %s returned: %s", tracking_number, e)

    return cainiao_events, bdpost_events


async def process_track_numbers(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    tracking_numbers_input: list[str] | str
) -> None:
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id
    db: Database = context.bot_data["db"]

    valid_numbers, invalid_numbers = extract_tracking_numbers(tracking_numbers_input)

    if invalid_numbers:
        invalid_list = ", ".join(invalid_numbers)
        await update.message.reply_text(
            f"⚠️ Invalid tracking number format: {invalid_list}",
            reply_markup=get_main_keyboard()
        )

    if not valid_numbers:
        return

    total = len(valid_numbers)
    if total > 1:
        await update.message.reply_text(f"🔍 Processing {total} tracking numbers...")

    for i, tracking_number in enumerate(valid_numbers):
        try:
            cainiao_events, bdpost_events = await fetch_tracking_sources(tracking_number)

            if not cainiao_events and not bdpost_events:
                await update.message.reply_text(
                    f"🔎 No tracking information found for `{tracking_number}` on AliExpress/Cainiao or Bangladesh Post.\n"
                    "Please verify the number and try again.",
                    parse_mode="Markdown",
                    reply_markup=get_main_keyboard()
                )
                continue

            # Save all existing events as known events (no spam for historical events)
            all_events = cainiao_events + bdpost_events
            db.save_events(tracking_number, all_events)
            db.update_last_checked(tracking_number)

            # Determine Handover & Provider states
            has_handover = any(is_bdpost_handover_event(e) for e in bdpost_events)
            latest_bdpost = get_latest_event(bdpost_events)
            latest_cainiao = get_latest_event(cainiao_events)

            is_already_delivered = bool(latest_bdpost and is_delivered(latest_bdpost.get("status", "")))

            if is_already_delivered:
                # Completed shipment
                db.stop_tracking(telegram_id, tracking_number)
                msg = (
                    f"🎉 *Parcel {tracking_number} is already Delivered!*\n\n"
                    f"{format_status_message(tracking_number, latest_bdpost)}\n\n"
                    "Tracking is complete and will not be polled."
                )
                await update.message.reply_text(
                    msg,
                    reply_markup=get_main_keyboard()
                )
            elif has_handover:
                # Parcel is already in Bangladesh
                cainiao_enabled = 0
                bdpost_enabled = 1
                handover_detected = 1
                db.add_or_reactivate_tracking(
                    telegram_id, tracking_number,
                    cainiao_enabled=cainiao_enabled,
                    bdpost_enabled=bdpost_enabled,
                    handover_detected=handover_detected
                )
                display_event = latest_bdpost or latest_cainiao
                msg = (
                    f"✅ *Subscribed to updates for {tracking_number}!*\n"
                    "🇧🇩 *Active Provider:* Bangladesh Post\n\n"
                    f"{format_status_message(tracking_number, display_event)}"
                )
                await update.message.reply_text(
                    msg,
                    reply_markup=get_parcel_inline_keyboard(tracking_number)
                )
            elif cainiao_events:
                # International Cainiao / AliExpress tracking active, waiting for BD arrival
                cainiao_enabled = 1
                bdpost_enabled = 1
                handover_detected = 0
                db.add_or_reactivate_tracking(
                    telegram_id, tracking_number,
                    cainiao_enabled=cainiao_enabled,
                    bdpost_enabled=bdpost_enabled,
                    handover_detected=handover_detected
                )
                display_event = latest_cainiao
                msg = (
                    f"✅ *Subscribed to Dual Tracking for {tracking_number}!*\n"
                    "🚚 *Current Provider:* AliExpress / Cainiao\n"
                    "🔄 *Note:* Tracking will automatically switch to Bangladesh Post upon local arrival.\n\n"
                    f"{format_status_message(tracking_number, display_event)}"
                )
                await update.message.reply_text(
                    msg,
                    reply_markup=get_parcel_inline_keyboard(tracking_number)
                )
            else:
                # Pure Bangladesh Post tracking
                cainiao_enabled = 0
                bdpost_enabled = 1
                handover_detected = 1
                db.add_or_reactivate_tracking(
                    telegram_id, tracking_number,
                    cainiao_enabled=cainiao_enabled,
                    bdpost_enabled=bdpost_enabled,
                    handover_detected=handover_detected
                )
                display_event = latest_bdpost
                msg = (
                    f"✅ *Subscribed to updates for {tracking_number}!*\n\n"
                    f"{format_status_message(tracking_number, display_event)}"
                )
                await update.message.reply_text(
                    msg,
                    reply_markup=get_parcel_inline_keyboard(tracking_number)
                )

        except Exception as e:
            logger.error("Unexpected error in /track for %s: %s", tracking_number, e, exc_info=True)
            await update.message.reply_text(
                f"⚠️ An unexpected error occurred while fetching details for `{tracking_number}`.",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )

        if i < total - 1:
            await asyncio.sleep(1.0)


async def process_status_numbers(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    tracking_numbers_input: list[str] | str
) -> None:
    if not update.message:
        return

    valid_numbers, invalid_numbers = extract_tracking_numbers(tracking_numbers_input)

    if invalid_numbers:
        invalid_list = ", ".join(invalid_numbers)
        await update.message.reply_text(
            f"⚠️ Invalid tracking number format: {invalid_list}",
            reply_markup=get_main_keyboard()
        )

    if not valid_numbers:
        return

    total = len(valid_numbers)
    for i, tracking_number in enumerate(valid_numbers):
        try:
            cainiao_events, bdpost_events = await fetch_tracking_sources(tracking_number)

            if not cainiao_events and not bdpost_events:
                await update.message.reply_text(
                    f"🔎 No tracking information found for `{tracking_number}` on AliExpress/Cainiao or Bangladesh Post.",
                    parse_mode="Markdown",
                    reply_markup=get_main_keyboard()
                )
            else:
                latest_bdpost = get_latest_event(bdpost_events)
                latest_cainiao = get_latest_event(cainiao_events)

                # Prioritize Bangladesh Post if local events exist, otherwise Cainiao
                if latest_bdpost and any(is_bdpost_handover_event(e) for e in bdpost_events):
                    display_event = latest_bdpost
                elif latest_bdpost and not latest_cainiao:
                    display_event = latest_bdpost
                else:
                    display_event = latest_cainiao or latest_bdpost

                msg = format_status_message(tracking_number, display_event)
                await update.message.reply_text(
                    msg,
                    reply_markup=get_parcel_inline_keyboard(tracking_number)
                )

        except Exception as e:
            logger.error("Unexpected error in /status for %s: %s", tracking_number, e, exc_info=True)
            await update.message.reply_text(
                f"⚠️ An unexpected error occurred while checking status for `{tracking_number}`.",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )

        if i < total - 1:
            await asyncio.sleep(1.0)


async def track_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    context.user_data.pop("state", None)

    if not context.args:
        await update.message.reply_text(
            "❌ Please provide one or more tracking numbers.\n\n"
            "Example:\n"
            "/track UG251542831MV\n"
            "/track UG251542831MV XX123456789BD",
            reply_markup=get_main_keyboard()
        )
        return

    await process_track_numbers(update, context, context.args)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    context.user_data.pop("state", None)

    if not context.args:
        await update.message.reply_text(
            "❌ Please provide one or more tracking numbers.\n\n"
            "Example:\n"
            "/status UG251542831MV\n"
            "/status UG251542831MV XX123456789BD",
            reply_markup=get_main_keyboard()
        )
        return

    await process_status_numbers(update, context, context.args)



