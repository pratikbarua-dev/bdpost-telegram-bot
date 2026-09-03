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
from track17.client import track as track_17track, Track17UnavailableError, Track17Error
from track17.parser import parse_tracking_response as parse_17track, extract_linked_tracking_numbers as extract_linked_17track

logger = logging.getLogger(__name__)


async def check_all_trackings(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Periodic job executed by JobQueue.
    Fetches updates for all unique active shipments across their tracking chain (AP -> CNG -> UG -> BD Post)
    and handles automatic discovery, handover, and delivery.
    """
    db: Database = context.bot_data["db"]
    active_shipments = db.get_all_active_shipments()

    if not active_shipments:
        logger.debug("No active shipments to check.")
        return

    logger.info("Starting periodic check for %d active shipment(s)", len(active_shipments))

    for shipment in active_shipments:
        shipment_id = shipment["id"]
        primary_number = shipment["primary_tracking_number"]
        cainiao_enabled = bool(shipment.get("cainiao_enabled", 1))
        bdpost_enabled = bool(shipment.get("bdpost_enabled", 1))
        handover_detected = bool(shipment.get("handover_detected", 0))
        local_tracking_number = shipment.get("local_tracking_number")

        subscribers = db.get_shipment_subscribers(shipment_id)
        if not subscribers:
            continue

        chain_numbers = db.get_tracking_chain_numbers(shipment_id)
        if not chain_numbers:
            chain_numbers = [primary_number]

        # -------------------------------------------------------------
        # 1. Check International Tracking (Cainiao primary, 17TRACK fallback)
        # -------------------------------------------------------------
        if cainiao_enabled:
            for num in list(chain_numbers):
                cainiao_success = False
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
                        cainiao_success = True
                        for ce in cainiao_events:
                            ce["tracking_number"] = num
                        new_cainiao_events = db.save_events(primary_number, cainiao_events)
                        if new_cainiao_events:
                            logger.info("Cainiao new event(s) for shipment %d (%s): %d", shipment_id, primary_number, len(new_cainiao_events))
                            for event in new_cainiao_events:
                                await _notify_subscribers(
                                    context, db, subscribers, primary_number, event,
                                    local_tracking_number=local_tracking_number,
                                    tracking_chain=chain_numbers
                                )
                except (CainiaoUnavailableError, CainiaoError) as ce:
                    logger.warning("Cainiao check failed for shipment %d (%s): %s", shipment_id, num, ce)
                except Exception as e:
                    logger.error("Unexpected error checking Cainiao for %s: %s", num, e, exc_info=True)

                # Fallback to 17TRACK if Cainiao failed or returned no events
                if not cainiao_success:
                    try:
                        logger.info("Checking 17TRACK fallback for shipment %d (%s)", shipment_id, num)
                        t17_data = await track_17track(num)
                        t17_events = parse_17track(t17_data, query_number=num)

                        discovered_17 = extract_linked_17track(t17_data, num)
                        for link in discovered_17:
                            new_num = link["tracking_number"]
                            if new_num not in chain_numbers:
                                chain_numbers.append(new_num)
                                db.link_tracking_number(
                                    shipment_id=shipment_id,
                                    tracking_number=new_num,
                                    source=link.get("source", "17track"),
                                    num_type=link.get("type", "local"),
                                    discovered_from=num
                                )
                                logger.info("17TRACK discovered linked tracking number for shipment %d: %s -> %s", shipment_id, num, new_num)

                        if t17_events:
                            for te in t17_events:
                                te["tracking_number"] = num
                            new_17_events = db.save_events(primary_number, t17_events)
                            if new_17_events:
                                logger.info("17TRACK new event(s) for shipment %d (%s): %d", shipment_id, primary_number, len(new_17_events))
                                for event in new_17_events:
                                    await _notify_subscribers(
                                        context, db, subscribers, primary_number, event,
                                        local_tracking_number=local_tracking_number,
                                        tracking_chain=chain_numbers
                                    )
                    except (Track17UnavailableError, Track17Error) as te:
                        logger.warning("17TRACK check notice for shipment %d (%s): %s", shipment_id, num, te)
                    except Exception as e:
                        logger.error("Unexpected error checking 17TRACK for %s: %s", num, e, exc_info=True)

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

                                    # Send single handover notification
                                    await _notify_subscribers(
                                        context, db, subscribers, primary_number, event,
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
                                    context, db, subscribers, primary_number, event,
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
        await asyncio.sleep(3.5)

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
            try:
                await context.bot.send_message(chat_id=uid, text=msg, parse_mode="HTML")
            except Exception as e:
                logger.debug("Failed to send expiry notification to %s: %s", uid, e)


async def _notify_subscribers(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    subscribers: List[Dict],
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
        else:
            text = format_event_notification(
                primary_tracking_number, event,
                label=label,
                tracking_chain=tracking_chain,
                local_tracking_number=local_tracking_number
            )

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode="HTML"
            )
        except Forbidden:
            logger.warning("Bot was blocked by user %s. Stopping tracking.", user_id)
            db.stop_shipment_tracking(user_id, primary_tracking_number)
        except TelegramError as te:
            logger.error("Failed to send Telegram notification to %s: %s", user_id, te)

