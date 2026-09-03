import logging
from telegram import Update
from telegram.ext import ContextTypes

from database.db import Database
from bdpost.parser import get_latest_event, is_bdpost_handover_event
from bdpost.formatter import format_status_message
from handlers.keyboards import get_main_keyboard, get_parcel_inline_keyboard, get_my_parcels_inline_keyboard
from handlers.tracking import fetch_tracking_sources

logger = logging.getLogger(__name__)


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return

    await query.answer()
    data = query.data
    telegram_id = update.effective_user.id
    db: Database = context.bot_data["db"]

    if data.startswith("refresh:"):
        tracking_number = data.split(":", 1)[1]
        try:
            cainiao_events, bdpost_events = await fetch_tracking_sources(tracking_number)
            all_events = cainiao_events + bdpost_events
            if all_events:
                db.save_events(tracking_number, all_events)
                db.update_last_checked(tracking_number)

                latest_bdpost = get_latest_event(bdpost_events)
                latest_cainiao = get_latest_event(cainiao_events)

                if latest_bdpost and any(is_bdpost_handover_event(e) for e in bdpost_events):
                    display_event = latest_bdpost
                elif latest_bdpost and not latest_cainiao:
                    display_event = latest_bdpost
                else:
                    display_event = latest_cainiao or latest_bdpost

                label = db.get_parcel_label(telegram_id, tracking_number)
                shipment = db.get_shipment_by_tracking_number(tracking_number)
                chain_numbers = [t["tracking_number"] for t in shipment.get("tracking_chain", [])] if shipment else None
                local_num = shipment.get("local_tracking_number") if shipment else None

                msg = format_status_message(
                    tracking_number, display_event,
                    label=label,
                    tracking_chain=chain_numbers,
                    local_tracking_number=local_num,
                    header_title="🔄 <b>Updated Status</b>"
                )
                await query.edit_message_text(
                    msg,
                    reply_markup=get_parcel_inline_keyboard(tracking_number),
                    parse_mode="HTML"
                )
            else:
                await query.message.reply_text(f"🔎 No information found for <code>{tracking_number}</code>.", parse_mode="HTML")
        except Exception as e:
            logger.error("Error refreshing %s: %s", tracking_number, e)
            await query.message.reply_text(f"⚠️ Could not refresh status for <code>{tracking_number}</code> right now.", parse_mode="HTML")

    elif data.startswith("rename:"):
        tracking_number = data.split(":", 1)[1]
        current_label = db.get_parcel_label(telegram_id, tracking_number)
        context.user_data["state"] = "waiting_for_rename"
        context.user_data["rename_tracking"] = tracking_number

        label_note = f" (Current name: <b>{current_label}</b>)" if current_label else ""
        from handlers.keyboards import get_cancel_keyboard
        from handlers.cleanup import record_prompt_message

        prompt = await query.message.reply_text(
            f"✏️ <b>Rename Parcel:</b> <code>{tracking_number}</code>{label_note}\n\n"
            "Please send the custom name for this parcel (e.g., <code>Mechanical Keyboard</code> or <code>Phone Case</code>).\n"
            "Type <code>none</code> to remove the custom name.",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
        record_prompt_message(context, prompt.message_id)

    elif data.startswith("stop:"):
        tracking_number = data.split(":", 1)[1]
        stopped = db.stop_tracking(telegram_id, tracking_number)
        if stopped:
            await query.edit_message_text(
                f"🛑 <b>Stopped tracking</b> <code>{tracking_number}</code>.\n\nYou will no longer receive notifications for this parcel.",
                parse_mode="HTML"
            )
        else:
            await query.edit_message_text(
                f"⚠️ You are not actively tracking <code>{tracking_number}</code>.",
                parse_mode="HTML"
            )

    elif data == "stop_all_confirm":
        from handlers.keyboards import get_stop_all_confirm_keyboard
        await query.edit_message_text(
            "⚠️ <b>Are you sure you want to stop tracking all your parcels?</b>",
            reply_markup=get_stop_all_confirm_keyboard(),
            parse_mode="HTML"
        )

    elif data == "stop_all_confirmed":
        count = db.stop_all_trackings(telegram_id)
        if count > 0:
            await query.edit_message_text(
                f"🛑 <b>Stopped tracking all {count} parcel(s).</b>\n\nYou will not receive notifications.",
                parse_mode="HTML"
            )
        else:
            await query.edit_message_text("⚠️ You do not have any active parcels.")

    elif data == "cancel_action":
        trackings = db.get_user_active_trackings(telegram_id)
        if trackings:
            await query.edit_message_text(
                "📦 <b>Your Tracked Parcels</b>",
                reply_markup=get_my_parcels_inline_keyboard(trackings),
                parse_mode="HTML"
            )
        else:
            await query.edit_message_text("Action canceled.")

    elif data == "refresh_all":
        trackings = db.get_user_active_trackings(telegram_id)
        if not trackings:
            await query.edit_message_text("📦 You aren't tracking any parcels yet.")
            return

        lines = [
            "🔄 <b>Refreshed Active Parcels</b>",
            "━━━━━━━━━━━━━━━━━━━━"
        ]
        for idx, item in enumerate(trackings, 1):
            num = item["tracking_number"]
            try:
                cainiao_events, bdpost_events = await fetch_tracking_sources(num)
                all_events = cainiao_events + bdpost_events
                if all_events:
                    db.save_events(num, all_events)
                    db.update_last_checked(num)

                    latest_bdpost = get_latest_event(bdpost_events)
                    latest_cainiao = get_latest_event(cainiao_events)
                    display = latest_bdpost or latest_cainiao
                    src = "🇧🇩 BD Post" if display.get("source") == "bdpost" else "🚚 Cainiao"
                    lines.append(f"{idx}. <code>{num}</code> [{src}]\n   📌 {display.get('status', 'N/A')}\n")
                else:
                    lines.append(f"{idx}. <code>{num}</code>\n   ⏳ Awaiting scan\n")
            except Exception:
                latest = db.get_latest_event_for_tracking(num)
                status = latest.get("status", "N/A") if latest else "N/A"
                lines.append(f"{idx}. <code>{num}</code>\n   📌 {status} (Cached)\n")

        lines.append("━━━━━━━━━━━━━━━━━━━━")

        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=get_my_parcels_inline_keyboard(trackings),
            parse_mode="HTML"
        )

    elif data == "go_home":
        welcome_text = (
            "👋 <b>Welcome to Bangladesh Post & AliExpress Tracker!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Track local Bangladesh Post parcels as well as AliExpress (Cainiao) shipments with automated handover upon arrival in Bangladesh.\n\n"
            "🔘 <b>Quick Guide:</b>\n"
            "• Tap <b>📦 Track Parcel</b> to subscribe for automatic notifications\n"
            "• Tap <b>🔍 Quick Status</b> for an instant lookup without subscribing\n"
            "• Tap <b>📋 My Parcels</b> to view, refresh, or rename (✏️) your parcels\n"
            "• Tap <b>🛑 Stop Tracking</b> to unsubscribe from updates\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
        await query.edit_message_text(
            welcome_text,
            parse_mode="HTML"
        )
        await query.message.reply_text(
            "🏠 Returned to Home Menu.",
            reply_markup=get_main_keyboard()
        )
