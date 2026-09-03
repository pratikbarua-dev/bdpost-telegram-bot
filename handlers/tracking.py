import asyncio
import logging
from typing import Dict, Any, List, Tuple, Optional
from telegram import Update
from telegram.ext import ContextTypes

from database.db import Database
from bdpost.client import track as track_bdpost, BangladeshPostUnavailableError
from bdpost.parser import parse_tracking_response as parse_bdpost, get_latest_event, is_delivered, is_bdpost_handover_event
from bdpost.validator import extract_tracking_numbers
from bdpost.formatter import format_status_message, format_pending_status_message
from cainiao.client import track as track_cainiao, CainiaoUnavailableError, CainiaoError
from cainiao.parser import parse_tracking_response as parse_cainiao, extract_linked_tracking_numbers
from handlers.keyboards import get_main_keyboard, get_parcel_inline_keyboard

logger = logging.getLogger(__name__)


async def discover_and_fetch_chain(
    db: Database,
    initial_tracking_number: str,
    shipment_id: Optional[int] = None
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str], Optional[str]]:
    """
    Recursively discovers tracking chain (e.g. AP -> CNG -> UG) and fetches events from
    both Cainiao and Bangladesh Post.
    Returns:
        (cainiao_events, bdpost_events, tracking_chain_numbers, local_tracking_number)
    """
    cleaned_start = initial_tracking_number.strip().upper()
    if shipment_id is None:
        shipment = db.get_shipment_by_tracking_number(cleaned_start)
        if shipment:
            shipment_id = shipment["id"]

    chain_queue = [cleaned_start]
    checked_cainiao = set()
    checked_bdpost = set()
    all_chain_numbers = [cleaned_start]

    if shipment_id is not None:
        existing_chain = db.get_tracking_chain_numbers(shipment_id)
        for num in existing_chain:
            if num not in all_chain_numbers:
                all_chain_numbers.append(num)
            if num not in chain_queue:
                chain_queue.append(num)

    all_cainiao_events: List[Dict[str, Any]] = []
    all_bdpost_events: List[Dict[str, Any]] = []
    local_tracking_number: Optional[str] = None

    # Process chain queue (max 5 hops to prevent any infinite loops)
    hops = 0
    while chain_queue and hops < 5:
        hops += 1
        current_num = chain_queue.pop(0)

        # 1. Fetch Cainiao
        if current_num not in checked_cainiao:
            checked_cainiao.add(current_num)
            try:
                cainiao_data = await track_cainiao(current_num)
                events = parse_cainiao(cainiao_data)
                for e in events:
                    e["tracking_number"] = current_num
                all_cainiao_events.extend(events)

                # Discover linked numbers
                discovered_links = extract_linked_tracking_numbers(cainiao_data, current_num)
                for link in discovered_links:
                    linked_num = link["tracking_number"]
                    if linked_num not in all_chain_numbers:
                        all_chain_numbers.append(linked_num)
                        chain_queue.append(linked_num)
                        logger.info("Discovered new linked tracking number: %s -> %s (%s)", current_num, linked_num, link.get("type"))
                        if shipment_id is not None:
                            db.link_tracking_number(
                                shipment_id=shipment_id,
                                tracking_number=linked_num,
                                source=link.get("source", "cainiao"),
                                num_type=link.get("type", "linked"),
                                discovered_from=current_num
                            )
            except Exception as e:
                logger.debug("Cainiao fetch for %s in chain: %s", current_num, e)

        # 2. Fetch Bangladesh Post
        if current_num not in checked_bdpost:
            checked_bdpost.add(current_num)
            try:
                bdpost_html = await track_bdpost(current_num)
                b_events = parse_bdpost(bdpost_html)
                if b_events:
                    for be in b_events:
                        be["tracking_number"] = current_num
                    all_bdpost_events.extend(b_events)
                    local_tracking_number = current_num
                    if shipment_id is not None:
                        db.update_shipment_status(shipment_id, local_tracking_number=current_num)
            except Exception as e:
                logger.debug("BD Post fetch for %s in chain: %s", current_num, e)

    # Sort events chronologically
    all_cainiao_events.sort(key=lambda x: x.get("event_date", ""))
    all_bdpost_events.sort(key=lambda x: x.get("event_date", ""))

    return all_cainiao_events, all_bdpost_events, all_chain_numbers, local_tracking_number


async def fetch_tracking_sources(db: Any, tracking_number: str) -> tuple[list[dict], list[dict]]:
    """
    Convenience wrapper to fetch tracking sources across the chain.
    """
    cainiao_events, bdpost_events, _, _ = await discover_and_fetch_chain(db, tracking_number)
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
            # 1. Get or create shipment
            shipment_id = db.get_or_create_shipment(tracking_number, telegram_id=telegram_id)

            # 2. Discover chain and fetch all events
            cainiao_events, bdpost_events, chain_numbers, local_num = await discover_and_fetch_chain(
                db, tracking_number, shipment_id=shipment_id
            )

            label = db.get_parcel_label(telegram_id, tracking_number)

            if not cainiao_events and not bdpost_events:
                # No events found yet -> Keep active, auto-monitor for 10 days
                db.update_shipment_status(
                    shipment_id,
                    cainiao_enabled=1,
                    bdpost_enabled=1,
                    handover_detected=0,
                    local_tracking_number=local_num
                )
                msg = format_pending_status_message(tracking_number, label=label, tracking_chain=chain_numbers, day_number=1)
                await update.message.reply_text(
                    msg,
                    reply_markup=get_parcel_inline_keyboard(tracking_number),
                    parse_mode="HTML"
                )
                continue

            # Save all existing events as known events (no notification for historical events)
            all_events = cainiao_events + bdpost_events
            db.save_events(tracking_number, all_events)
            for num in chain_numbers:
                db.update_last_checked(num)

            # Determine Handover & Delivery states
            has_handover = any(is_bdpost_handover_event(e) for e in bdpost_events)
            latest_bdpost = get_latest_event(bdpost_events)
            latest_cainiao = get_latest_event(cainiao_events)
            is_already_delivered = bool(latest_bdpost and is_delivered(latest_bdpost.get("status", "")))

            if is_already_delivered:
                # Completed shipment
                db.deactivate_shipment_on_delivery(shipment_id)
                msg = format_status_message(
                    tracking_number, latest_bdpost,
                    label=label,
                    tracking_chain=chain_numbers,
                    local_tracking_number=local_num,
                    header_title="🎉 <b>Parcel Delivered</b>"
                )
                await update.message.reply_text(
                    msg,
                    reply_markup=get_main_keyboard(),
                    parse_mode="HTML"
                )
            elif has_handover:
                # Parcel is already in Bangladesh
                db.update_shipment_status(
                    shipment_id,
                    cainiao_enabled=0,
                    bdpost_enabled=1,
                    handover_detected=1,
                    handover_event_hash=latest_bdpost["event_hash"] if latest_bdpost else None,
                    local_tracking_number=local_num
                )
                display_event = latest_bdpost or latest_cainiao
                msg = format_status_message(
                    tracking_number, display_event,
                    label=label,
                    tracking_chain=chain_numbers,
                    local_tracking_number=local_num,
                    header_title="✅ <b>Subscribed to Updates</b>"
                )
                await update.message.reply_text(
                    msg,
                    reply_markup=get_parcel_inline_keyboard(tracking_number),
                    parse_mode="HTML"
                )
            elif cainiao_events:
                # International Cainiao / AliExpress tracking active, waiting for BD arrival
                db.update_shipment_status(
                    shipment_id,
                    cainiao_enabled=1,
                    bdpost_enabled=1,
                    handover_detected=0,
                    local_tracking_number=local_num
                )
                display_event = latest_cainiao
                msg = format_status_message(
                    tracking_number, display_event,
                    label=label,
                    tracking_chain=chain_numbers,
                    local_tracking_number=local_num,
                    header_title="✅ <b>Subscribed to Dual Tracking</b>"
                )
                await update.message.reply_text(
                    msg,
                    reply_markup=get_parcel_inline_keyboard(tracking_number),
                    parse_mode="HTML"
                )
            else:
                # Pure Bangladesh Post tracking
                db.update_shipment_status(
                    shipment_id,
                    cainiao_enabled=0,
                    bdpost_enabled=1,
                    handover_detected=1,
                    local_tracking_number=local_num
                )
                display_event = latest_bdpost
                msg = format_status_message(
                    tracking_number, display_event,
                    label=label,
                    tracking_chain=chain_numbers,
                    local_tracking_number=local_num,
                    header_title="✅ <b>Subscribed to Updates</b>"
                )
                await update.message.reply_text(
                    msg,
                    reply_markup=get_parcel_inline_keyboard(tracking_number),
                    parse_mode="HTML"
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

    telegram_id = update.effective_user.id if update.effective_user else None
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
    for i, tracking_number in enumerate(valid_numbers):
        try:
            cainiao_events, bdpost_events, chain_numbers, local_num = await discover_and_fetch_chain(
                db, tracking_number
            )

            if not cainiao_events and not bdpost_events:
                label = db.get_parcel_label(telegram_id, tracking_number) if telegram_id else None
                msg = format_pending_status_message(tracking_number, label=label, tracking_chain=chain_numbers, day_number=1)
                await update.message.reply_text(
                    msg,
                    parse_mode="HTML",
                    reply_markup=get_parcel_inline_keyboard(tracking_number)
                )
            else:
                latest_bdpost = get_latest_event(bdpost_events)
                latest_cainiao = get_latest_event(cainiao_events)

                if latest_bdpost and any(is_bdpost_handover_event(e) for e in bdpost_events):
                    display_event = latest_bdpost
                elif latest_bdpost and not latest_cainiao:
                    display_event = latest_bdpost
                else:
                    display_event = latest_cainiao or latest_bdpost

                label = db.get_parcel_label(telegram_id, tracking_number) if telegram_id else None
                msg = format_status_message(
                    tracking_number,
                    display_event,
                    label=label,
                    tracking_chain=chain_numbers,
                    local_tracking_number=local_num
                )
                await update.message.reply_text(
                    msg,
                    reply_markup=get_parcel_inline_keyboard(tracking_number),
                    parse_mode="HTML"
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
            "/track AP00839881455575\n"
            "/track UG251542831MV",
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
            "/status AP00839881455575\n"
            "/status UG251542831MV",
            reply_markup=get_main_keyboard()
        )
        return

    await process_status_numbers(update, context, context.args)




