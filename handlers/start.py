from telegram import Update
from telegram.ext import ContextTypes
from database.db import Database
from handlers.keyboards import get_main_keyboard
from handlers.cleanup import cleanup_previous_messages


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    await cleanup_previous_messages(update, context)

    # Clear any pending waiting state
    context.user_data.pop("state", None)
    context.user_data.pop("rename_tracking", None)

    db: Database = context.bot_data.get("db")
    if db:
        user = update.effective_user
        db.get_or_create_user(
            user.id,
            username=user.username,
            full_name=user.full_name
        )

    welcome_text = (
        "👋 <b>Welcome to Bangladesh Post & AliExpress Tracker!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Track local Bangladesh Post parcels as well as AliExpress (Cainiao) shipments with automated handover upon arrival in Bangladesh.\n\n"
        "🔘 <b>Quick Guide:</b>\n"
        "• Tap <b>📦 Track Parcel</b> to subscribe for automatic notifications\n"
        "• Tap <b>🔍 Quick Status</b> for an instant lookup without subscribing\n"
        "• Tap <b>📋 My Parcels</b> to view, refresh, or rename (✏️) your parcels\n"
        "• Tap <b>📮 Postcode & Offices</b> to search 1,349 post offices & contacts\n"
        "• Tap <b>💬 Feedback</b> to share ideas, report bugs, or request features\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await cleanup_previous_messages(update, context)
    context.user_data.pop("state", None)
    context.user_data.pop("rename_tracking", None)

    help_text = (
        "ℹ️ <b>Tracker Help & Commands</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Button Actions:</b>\n"
        "• <b>📦 Track Parcel</b> — Enter tracking number(s) to subscribe\n"
        "• <b>🔍 Quick Status</b> — Instant tracking lookup\n"
        "• <b>📋 My Parcels</b> — Manage your active shipments\n"
        "• <b>🛑 Stop Tracking</b> — Unsubscribe from updates\n"
        "• <b>💬 Feedback</b> — Send suggestions or report issues\n\n"
        "<b>Naming Parcels:</b>\n"
        "Tap ✏️ in <b>📋 My Parcels</b> or use <code>/name &lt;tracking_number&gt; &lt;label&gt;</code>\n\n"
        "<b>Commands:</b>\n"
        "• <code>/feedback &lt;message&gt;</code> — Send feedback or report bugs\n\n"
        "<b>Multiple Numbers:</b>\n"
        "You can enter multiple numbers separated by spaces or commas.\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

    await update.message.reply_text(
        help_text,
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )

