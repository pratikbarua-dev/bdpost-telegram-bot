import asyncio
import logging
from typing import List, Dict
from telegram.ext import ContextTypes
from telegram.error import TelegramError, Forbidden

from database.db import Database
from bdpost.client import track as track_bdpost, BangladeshPostUnavailableError
from bdpost.parser import parse_tracking_response as parse_bdpost, is_delivered, is_bdpost_handover_event
from bdpost.formatter import format_event_notification, format_handover_notification
from cainiao.client import track as track_cainiao, CainiaoUnavailableError, CainiaoError
from cainiao.parser import parse_tracking_response as parse_cainiao

logger = logging.getLogger(__name__)


async def check_all_trackings(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Periodic job executed by JobQueue.
    Fetches updates for all unique active tracking numbers and handles
    Cainiao -> Bangladesh Post dual tracking with automated handover.
    """
    db: Database = context.bot_data["db"]
    active_trackings = db.get_active_trackings_with_providers()

    if not active_trackings:
        logger.debug("No active trackings to check.")
        return

    logger.info("Starting periodic check for %d active parcels", len(active_trackings))

    for item in active_trackings:
        tracking_number = item["tracking_number"]
        cainiao_enabled = bool(item.get("cainiao_enabled", 0))
        bdpost_enabled = bool(item.get("bdpost_enabled", 1))
        handover_detected = bool(item.get("handover_detected", 0))

        subscribers_data = db.get_subscribers_with_labels_for_tracking(tracking_number)
        if not subscribers_data:
            continue

        # -------------------------------------------------------------
        # 1. Check Cainiao (if enabled)
        # -------------------------------------------------------------
        if cainiao_enabled:
            try:
                logger.info("Checking Cainiao: %s", tracking_number)
                cainiao_data = await track_cainiao(tracking_number)
                cainiao_events = parse_cainiao(cainiao_data)

                if cainiao_events:
                    new_cainiao_events = db.save_events(tracking_number, cainiao_events)
                    if new_cainiao_events:
                        logger.info("Cainiao new event(s) for %s: %d", tracking_number, len(new_cainiao_events))
                        for event in new_cainiao_events:
                            await _notify_users(context, db, subscribers_data, tracking_number, event)
            except (CainiaoUnavailableError, CainiaoError) as ce:
                logger.warning("Cainiao check failed for %s: %s", tracking_number, ce)
            except Exception as e:
                logger.error("Unexpected error checking Cainiao for %s: %s", tracking_number, e, exc_info=True)

        # -------------------------------------------------------------
        # 2. Check Bangladesh Post (if enabled)
        # -------------------------------------------------------------
        if bdpost_enabled:
            try:
                logger.info("Checking Bangladesh Post: %s", tracking_number)
                html = await track_bdpost(tracking_number)
                bdpost_events = parse_bdpost(html)

                if bdpost_events:
                    # Check for Handover if not yet detected
                    if not handover_detected and cainiao_enabled:
                        for event in bdpost_events:
                            if is_bdpost_handover_event(event):
                                logger.info("Handover detected for %s at event: %s", tracking_number, event.get("status"))
                                db.set_handover_detected(tracking_number, event["event_hash"])
                                handover_detected = True
                                cainiao_enabled = False

                                # Send handover notification
                                await _notify_users(context, db, subscribers_data, tracking_number, event, is_handover=True)
                                break

                    new_bdpost_events = db.save_events(tracking_number, bdpost_events)
                    if new_bdpost_events:
                        logger.info("Bangladesh Post new event(s) for %s: %d", tracking_number, len(new_bdpost_events))
                        has_delivered = False
                        for event in new_bdpost_events:
                            if is_delivered(event.get("status", "")):
                                has_delivered = True
                            await _notify_users(context, db, subscribers_data, tracking_number, event)

                        if has_delivered:
                            logger.info("Parcel %s has been delivered. Deactivating tracking.", tracking_number)
                            db.deactivate_tracking_number(tracking_number)

            except BangladeshPostUnavailableError as be:
                logger.warning("Bangladesh Post unavailable for %s: %s", tracking_number, be)
            except Exception as e:
                logger.error("Unexpected error checking Bangladesh Post for %s: %s", tracking_number, e, exc_info=True)

        db.update_last_checked(tracking_number)
        await asyncio.sleep(1.5)


async def _notify_users(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    subscribers_data: List[Dict],
    tracking_number: str,
    event: Dict,
    is_handover: bool = False
) -> None:
    for sub in subscribers_data:
        user_id = sub["telegram_id"]
        label = sub.get("label")

        if is_handover:
            text = format_handover_notification(tracking_number, event, label=label)
        else:
            text = format_event_notification(tracking_number, event, label=label)

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode="Markdown"
            )
        except Forbidden:
            logger.warning("Bot was blocked by user %s. Stopping tracking for %s.", user_id, tracking_number)
            db.stop_tracking(user_id, tracking_number)
        except TelegramError as te:
            logger.error("Failed to send Telegram notification to %s: %s", user_id, te)
