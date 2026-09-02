import asyncio
import logging
from typing import List, Dict
from telegram.ext import ContextTypes
from telegram.error import TelegramError, Forbidden

from database.db import Database
from bdpost.client import track, BangladeshPostUnavailableError
from bdpost.parser import parse_tracking_response
from bdpost.formatter import format_event_notification

logger = logging.getLogger(__name__)


async def check_all_trackings(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Periodic job executed by JobQueue.
    Fetches updates for all unique active tracking numbers and notifies subscribers.
    """
    db: Database = context.bot_data["db"]
    active_tracking_numbers = db.get_all_active_tracking_numbers()

    if not active_tracking_numbers:
        logger.debug("No active trackings to check.")
        return

    logger.info("Starting periodic check for %d active parcels", len(active_tracking_numbers))

    for tracking_number in active_tracking_numbers:
        try:
            logger.info("Checking tracking number: %s", tracking_number)
            html = await track(tracking_number)
            events = parse_tracking_response(html)

            if not events:
                logger.debug("No events found for %s", tracking_number)
                db.update_last_checked(tracking_number)
                await asyncio.sleep(1.0)
                continue

            # In typical tracking tables, events are in chronological order (oldest to newest)
            new_events = db.save_events(tracking_number, events)
            db.update_last_checked(tracking_number)

            if new_events:
                logger.info("Detected %d new event(s) for %s", len(new_events), tracking_number)
                subscribers = db.get_subscribers_for_tracking(tracking_number)
                
                # Send events in chronological order
                events_to_notify = new_events
                has_delivered_event = False

                for event in events_to_notify:
                    if is_delivered(event.get("status", "")):
                        has_delivered_event = True
                    message_text = format_event_notification(tracking_number, event)
                    for user_id in subscribers:
                        try:
                            await context.bot.send_message(
                                chat_id=user_id,
                                text=message_text
                            )
                        except Forbidden:
                            logger.warning("Bot was blocked by user %s. Stopping tracking.", user_id)
                            db.stop_tracking(user_id, tracking_number)
                        except TelegramError as te:
                            logger.error("Failed to send Telegram notification to %s: %s", user_id, te)

                # Automatically deactivate completed tracking subscriptions
                if has_delivered_event:
                    logger.info("Parcel %s has been delivered. Deactivating tracking.", tracking_number)
                    db.deactivate_tracking_number(tracking_number)

            # Delay to avoid overwhelming the Bangladesh Post server
            await asyncio.sleep(1.5)

        except BangladeshPostUnavailableError as e:
            logger.warning("Bangladesh Post unavailable while checking %s: %s", tracking_number, e)
        except Exception as e:
            logger.error("Unexpected error checking %s: %s", tracking_number, e, exc_info=True)
            # Continue checking remaining parcels
            continue
