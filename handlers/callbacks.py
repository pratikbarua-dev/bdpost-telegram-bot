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

                msg = f"🔄 *Updated Status:*\n\n{format_status_message(tracking_number, display_event, label=label, tracking_chain=chain_numbers, local_tracking_number=local_num)}"
                await query.edit_message_text(
                    msg,
                    reply_markup=get_parcel_inline_keyboard(tracking_number),
                    parse_mode="Markdown"
                )
            else:
                await query.message.reply_text(f"🔎 No information found for `{tracking_number}`.")
        except Exception as e:
            logger.error("Error refreshing %s: %s", tracking_number, e)
            await query.message.reply_text(f"⚠️ Could not refresh status for `{tracking_number}` right now.")

    elif data.startswith("rename:"):
        tracking_number = data.split(":", 1)[1]
        current_label = db.get_parcel_label(telegram_id, tracking_number)
        context.user_data["state"] = "waiting_for_rename"
        context.user_data["rename_tracking"] = tracking_number

        label_note = f" (Current name: *{current_label}*)" if current_label else ""
        from handlers.keyboards import get_cancel_keyboard
        from handlers.cleanup import record_prompt_message

        prompt = await query.message.reply_text(
            f"✏️ *Rename Parcel:* `{tracking_number}`{label_note}\n\n"
            "Please send the custom name/label for this parcel (e.g., `Mechanical Keyboard` or `Phone Case`).\n"
            "Type `none` to remove the name.",
            reply_markup=get_cancel_keyboard(),
            parse_mode="Markdown"
        )
        record_prompt_message(context, prompt.message_id)

    elif data.startswith("stop:"):
        tracking_number = data.split(":", 1)[1]
        stopped = db.stop_tracking(telegram_id, tracking_number)
        if stopped:
            await query.edit_message_text(
                f"🛑 *Stopped tracking* `{tracking_number}`.\n\nYou will no longer receive notifications for this parcel.",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text(
                f"⚠️ You are not actively tracking `{tracking_number}`.",
                parse_mode="Markdown"
            )

    elif data == "stop_all_confirm":
        from handlers.keyboards import get_stop_all_confirm_keyboard
        await query.edit_message_text(
            "⚠️ *Are you sure you want to stop tracking all your parcels?*",
            reply_markup=get_stop_all_confirm_keyboard(),
            parse_mode="Markdown"
        )

    elif data == "stop_all_confirmed":
        count = db.stop_all_trackings(telegram_id)
        if count > 0:
            await query.edit_message_text(
                f"🛑 *Stopped tracking all {count} parcel(s).*\n\nYou will not receive notifications.",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text("⚠️ You do not have any active parcels.")

    elif data == "cancel_action":
        trackings = db.get_user_active_trackings(telegram_id)
        if trackings:
            await query.edit_message_text(
                "📦 *Your Tracked Parcels*",
                reply_markup=get_my_parcels_inline_keyboard(trackings),
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text("Action canceled.")

    elif data == "refresh_all":
        trackings = db.get_user_active_trackings(telegram_id)
        if not trackings:
            await query.edit_message_text("📦 You aren't tracking any parcels yet.")
            return

        lines = ["🔄 *Refreshed Tracked Parcels:*\n"]
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
                    lines.append(f"{idx}. *{num}* ({src})\n   📌 {display.get('status', 'N/A')}\n")
                else:
                    lines.append(f"{idx}. *{num}*\n   (No records found)\n")
            except Exception:
                latest = db.get_latest_event_for_tracking(num)
                status = latest.get("status", "N/A") if latest else "N/A"
                lines.append(f"{idx}. *{num}*\n   📌 {status} (Cached)\n")

        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=get_my_parcels_inline_keyboard(trackings),
            parse_mode="Markdown"
        )

    elif data == "go_home":
        welcome_text = (
            "👋 Welcome to *Bangladesh Post & AliExpress Parcel Tracker*!\n\n"
            "Use the buttons below or send commands to track your parcels and get automatic status updates.\n\n"
            "🔘 *Quick Menu:*\n"
            "• *📦 Track Parcel* — Subscribe for updates (AliExpress & BD Post)\n"
            "• *🔍 Quick Status* — Instant tracking check\n"
            "• *📋 My Parcels* — View active tracked parcels\n"
            "• *🛑 Stop Tracking* — Stop notifications"
        )
        await query.edit_message_text(
            welcome_text,
            parse_mode="Markdown"
        )
        await query.message.reply_text(
            "🏠 Returned to Home Menu.",
            reply_markup=get_main_keyboard()
        )
