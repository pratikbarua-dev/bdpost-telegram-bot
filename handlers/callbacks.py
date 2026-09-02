import logging
from telegram import Update
from telegram.ext import ContextTypes

from database.db import Database
from bdpost.client import track, BangladeshPostUnavailableError
from bdpost.parser import parse_tracking_response, get_latest_event
from bdpost.formatter import format_status_message
from handlers.keyboards import get_main_keyboard, get_parcel_inline_keyboard, get_my_parcels_inline_keyboard

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
            html = await track(tracking_number)
            events = parse_tracking_response(html)
            if events:
                db.save_events(tracking_number, events)
                db.update_last_checked(tracking_number)
                latest = get_latest_event(events)
                msg = f"🔄 *Updated Status:*\n\n{format_status_message(tracking_number, latest)}"
                await query.edit_message_text(
                    msg,
                    reply_markup=get_parcel_inline_keyboard(tracking_number)
                )
            else:
                await query.message.reply_text(f"🔎 No information found for `{tracking_number}`.")
        except Exception as e:
            logger.error("Error refreshing %s: %s", tracking_number, e)
            await query.message.reply_text(f"⚠️ Could not refresh status for `{tracking_number}` right now.")

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
                html = await track(num)
                events = parse_tracking_response(html)
                if events:
                    db.save_events(num, events)
                    db.update_last_checked(num)
                    latest = get_latest_event(events)
                    lines.append(f"{idx}. *{num}*\n   📍 {latest.get('location', 'N/A')}\n   📌 {latest.get('status', 'N/A')}\n")
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
            "👋 Welcome to *Bangladesh Post Parcel Tracker*!\n\n"
            "Use the buttons below or send commands to track your parcels and get automatic status updates.\n\n"
            "🔘 *Quick Menu:*\n"
            "• *📦 Track Parcel* — Subscribe for updates\n"
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
