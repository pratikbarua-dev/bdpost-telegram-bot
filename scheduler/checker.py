import asyncio
import logging
from typing import List, Dict, Optional
from telegram.ext import ContextTypes
from telegram.error import TelegramError, Forbidden

from database.db import Database
from bdpost.client import track as track_bdpost, BangladeshPostUnavailableError
from bdpost.parser import parse_tracking_response as parse_bdpost, is_delivered, is_bdpost_handover_event
from bdpost.formatter import format_event_notification, format_handover_notification, format_expiry_notification
from cainiao.client import track as track_cainiao, CainiaoUnavailableError, CainiaoError
from cainiao.parser import parse_tracking_response as parse_cainiao, extract_linked_tracking_numbers as extract_linked_cainiao

logger = logging.getLogger(__name__)


async def check_all_trackings(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Periodic job executed by JobQueue with priority-aware batching.
    Fetches updates for shipments due for inspection and enqueues notifications to outbox.
    """
    db: Database = context.bot_data["db"]
    # Retrieve top 25 shipments due for check (prioritizing HOT > WARM > COLD)
    due_shipments = db.get_shipments_due_for_check(batch_size=25)

    if not due_shipments:
        logger.debug("No shipments currently due for check.")
        return

    logger.info("Starting priority check for %d due shipment(s)", len(due_shipments))

    # Bound concurrency with semaphore to protect Render memory and carrier endpoints
    sem = asyncio.Semaphore(2)

    for shipment in due_shipments:
        async with sem:
            await _process_single_shipment_check(context, db, shipment)
        await asyncio.sleep(1.0)

    # -------------------------------------------------------------
    # 3. Check for Stale Shipments (10 days without updates)
    # -------------------------------------------------------------
    stale_shipments = db.get_stale_unscanned_shipments(days=10)
    for stale in stale_shipments:
        sid = stale["id"]
        p_num = stale["primary_tracking_number"]
        subs = db.get_shipment_subscribers(sid)

        logger.info("Expiring shipment %d (%s) due to 10 days of inactivity", sid, p_num)
        db.expire_stale_shipment(sid)

        for sub in subs:
            uid = sub["telegram_id"]
            lbl = sub.get("label")
            msg = format_expiry_notification(p_num, label=lbl)
            db.enqueue_notification(uid, sid, msg, message_type="EXPIRY")


async def _process_single_shipment_check(context: ContextTypes.DEFAULT_TYPE, db: Database, shipment: Dict) -> None:
    shipment_id = shipment["id"]
    primary_number = shipment["primary_tracking_number"]
    cainiao_enabled = bool(shipment.get("cainiao_enabled", 1))
    bdpost_enabled = bool(shipment.get("bdpost_enabled", 1))
    handover_detected = bool(shipment.get("handover_detected", 0))
    local_tracking_number = shipment.get("local_tracking_number")

    subscribers = db.get_shipment_subscribers(shipment_id)
    if not subscribers:
        return

    chain_numbers = db.get_tracking_chain_numbers(shipment_id)
    if not chain_numbers:
        chain_numbers = [primary_number]

    # -------------------------------------------------------------
    # 1. Check Cainiao across chain numbers (if enabled)
    # -------------------------------------------------------------
    if cainiao_enabled:
        # Prioritize single active Cainiao identifier per shipment to avoid duplicate API hammering
        cainiao_targets = [n for n in chain_numbers if n.startswith("CNG") or n.startswith("AP")]
        if not cainiao_targets:
            cainiao_targets = [primary_number]
        else:
            cainiao_targets = [cainiao_targets[-1]]  # Use latest known alias

        for num in cainiao_targets:
            try:
                logger.info("Checking Cainiao for shipment %d (%s)", shipment_id, num)
                cainiao_data = await track_cainiao(num)
                cainiao_events = parse_cainiao(cainiao_data)

                # Discover any newly linked tracking numbers
                discovered = extract_linked_cainiao(cainiao_data, num)
                for link in discovered:
                    new_num = link["tracking_number"]
                    if new_num not in chain_numbers:
                        chain_numbers.append(new_num)
                        db.link_tracking_number(
                            shipment_id=shipment_id,
                            tracking_number=new_num,
                            source=link.get("source", "cainiao"),
                            num_type=link.get("type", "linked"),
                            discovered_from=num
                        )
                        logger.info("Scheduler discovered linked tracking number for shipment %d: %s -> %s", shipment_id, num, new_num)

                if cainiao_events:
                    for ce in cainiao_events:
                        ce["tracking_number"] = num
                    new_cainiao_events = db.save_events(primary_number, cainiao_events)
                    if new_cainiao_events:
                        logger.info("Cainiao new event(s) for shipment %d (%s): %d", shipment_id, primary_number, len(new_cainiao_events))
                        for event in new_cainiao_events:
                            await _notify_subscribers(
                                context, db, subscribers, shipment_id, primary_number, event,
                                local_tracking_number=local_tracking_number,
                                tracking_chain=chain_numbers
                            )
            except (CainiaoUnavailableError, CainiaoError) as ce:
                logger.warning("Cainiao check failed for shipment %d (%s): %s", shipment_id, num, ce)
            except Exception as e:
                logger.error("Unexpected error checking Cainiao for %s: %s", num, e, exc_info=True)

    # -------------------------------------------------------------
    # 2. Check Bangladesh Post across all numbers in chain (if enabled)
    # -------------------------------------------------------------
    if bdpost_enabled:
        for num in list(chain_numbers):
            try:
                logger.info("Checking Bangladesh Post for shipment %d (%s)", shipment_id, num)
                html = await track_bdpost(num)
                bdpost_events = parse_bdpost(html)

                if bdpost_events:
                    for be in bdpost_events:
                        be["tracking_number"] = num

                    if not local_tracking_number:
                        local_tracking_number = num
                        db.update_shipment_status(shipment_id, local_tracking_number=num)

                    # Check for Handover if not yet confirmed
                    if not handover_detected and cainiao_enabled:
                        for event in bdpost_events:
                            if is_bdpost_handover_event(event):
                                logger.info("Handover confirmed for shipment %d (%s) at event: %s", shipment_id, primary_number, event.get("status"))
                                db.update_shipment_status(
                                    shipment_id,
                                    cainiao_enabled=0,
                                    bdpost_enabled=1,
                                    handover_detected=1,
                                    handover_event_hash=event["event_hash"],
                                    local_tracking_number=local_tracking_number
                                )
                                handover_detected = True
                                cainiao_enabled = False

                                # Enqueue single handover notification
                                await _notify_subscribers(
                                    context, db, subscribers, shipment_id, primary_number, event,
                                    is_handover=True,
                                    local_tracking_number=local_tracking_number,
                                    tracking_chain=chain_numbers
                                )
                                break

                    new_bdpost_events = db.save_events(primary_number, bdpost_events)
                    if new_bdpost_events:
                        logger.info("Bangladesh Post new event(s) for shipment %d (%s): %d", shipment_id, primary_number, len(new_bdpost_events))
                        has_delivered = False
                        for event in new_bdpost_events:
                            if is_delivered(event.get("status", "")):
                                has_delivered = True
                            await _notify_subscribers(
                                context, db, subscribers, shipment_id, primary_number, event,
                                local_tracking_number=local_tracking_number,
                                tracking_chain=chain_numbers
                            )

                        if has_delivered:
                            logger.info("Shipment %d (%s) has been delivered. Deactivating tracking.", shipment_id, primary_number)
                            db.deactivate_shipment_on_delivery(shipment_id)
                            break

            except BangladeshPostUnavailableError as be:
                logger.warning("Bangladesh Post unavailable for shipment %d (%s): %s", shipment_id, num, be)
            except Exception as e:
                logger.error("Unexpected error checking Bangladesh Post for %s: %s", num, e, exc_info=True)

    for num in chain_numbers:
        db.update_last_checked(num)


async def _notify_subscribers(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    subscribers: List[Dict],
    shipment_id: int,
    primary_tracking_number: str,
    event: Dict,
    is_handover: bool = False,
    local_tracking_number: Optional[str] = None,
    tracking_chain: Optional[List[str]] = None
) -> None:
    for sub in subscribers:
        user_id = sub["telegram_id"]
        label = sub.get("label")

        if is_handover:
            text = format_handover_notification(
                primary_tracking_number, event,
                label=label,
                local_tracking_number=local_tracking_number,
                tracking_chain=tracking_chain
            )
            msg_type = "HANDOVER"
        else:
            text = format_event_notification(
                primary_tracking_number, event,
                label=label,
                tracking_chain=tracking_chain,
                local_tracking_number=local_tracking_number
            )
            msg_type = "DELIVERED" if is_delivered(event.get("status", "")) else "STATUS_UPDATE"

        # Staging into transactional outbox queue
        db.enqueue_notification(
            telegram_id=user_id,
            shipment_id=shipment_id,
            payload_html=text,
            message_type=msg_type
        )

