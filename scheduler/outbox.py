import asyncio
import logging
from typing import Dict, Any, List, Optional
from telegram.ext import ContextTypes
from telegram.error import TelegramError, Forbidden, RetryAfter

from database.db import Database

logger = logging.getLogger(__name__)


async def dispatch_notification_outbox(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Dedicated Outbox Queue Consumer running on JobQueue.
    Consumes pending notifications staged in `notification_queue`,
    delivering them to Telegram users with bounded leaky-bucket rate limits.
    Completely isolates carrier polling from Telegram network operations.
    """
    db: Database = context.bot_data["db"]
    pending_items = db.get_pending_notifications(limit=25)

    if not pending_items:
        return

    logger.info("Outbox Dispatcher processing %d pending notification(s)", len(pending_items))

    for item in pending_items:
        notif_id = item["id"]
        telegram_id = item["telegram_id"]
        payload_html = item["payload_html"]
        retry_count = item.get("retry_count", 0)

        try:
            await context.bot.send_message(
                chat_id=telegram_id,
                text=payload_html,
                parse_mode="HTML"
            )
            db.mark_notification_sent(notif_id)
            logger.debug("Notification %d sent to %d successfully", notif_id, telegram_id)
            # Leaky bucket delay: ~20 msgs/second max rate to stay well below Telegram's 30/s limit
            await asyncio.sleep(0.05)

        except Forbidden:
            logger.warning("Bot blocked by user %d. Deactivating user tracking.", telegram_id)
            shipment_id = item.get("shipment_id")
            primary_num = item.get("primary_tracking_number")
            if primary_num:
                db.stop_shipment_tracking(telegram_id, primary_num)
            db.mark_notification_sent(notif_id)  # Remove from queue

        except RetryAfter as ra:
            wait_time = int(ra.retry_after) + 1
            logger.warning("Telegram flood control triggered. Backing off for %d seconds.", wait_time)
            db.mark_notification_failed(notif_id, retry_count + 1, next_retry_seconds=wait_time)
            await asyncio.sleep(wait_time)
            break

        except TelegramError as te:
            logger.error("Telegram error sending notification %d to %d: %s", notif_id, telegram_id, te)
            backoff_sec = (retry_count + 1) * 30
            db.mark_notification_failed(notif_id, retry_count + 1, next_retry_seconds=backoff_sec)

        except Exception as e:
            logger.error("Unexpected error in outbox dispatch for %d: %s", notif_id, e, exc_info=True)
            db.mark_notification_failed(notif_id, retry_count + 1, next_retry_seconds=60)
