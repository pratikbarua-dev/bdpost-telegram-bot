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
        db.get_or_create_user(update.effective_user.id)

    welcome_text = (
        "👋 Welcome to *Bangladesh Post & AliExpress Parcel Tracker*!\n\n"
        "Track local Bangladesh Post parcels as well as AliExpress (Cainiao) shipments with automated handover upon arrival in Bangladesh.\n\n"
        "🔘 *How to use:*\n"
        "• Tap *📦 Track Parcel* to subscribe for background notifications\n"
        "• Tap *🔍 Quick Status* to check tracking without subscribing\n"
        "• Tap *📋 My Parcels* to manage, rename (✏️), or stop parcels\n"
        "• Tap *🛑 Stop Tracking* to unsubscribe from updates"
    )

    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await cleanup_previous_messages(update, context)
    context.user_data.pop("state", None)
    context.user_data.pop("rename_tracking", None)

    help_text = (
        "ℹ️ *Bangladesh Post Tracker — Help & Guide*\n\n"
        "*Button Actions:*\n"
        "📦 *Track Parcel* — Enter tracking number(s) to subscribe to automatic updates.\n"
        "🔍 *Quick Status* — Instant tracking lookup without subscribing.\n"
        "📋 *My Parcels* — View all your active parcels with quick actions (Refresh, Rename ✏️, Stop 🛑).\n"
        "🛑 *Stop Tracking* — Unsubscribe from one or all parcels.\n\n"
        "*Naming Parcels:*\n"
        "You can rename any parcel using the ✏️ button in `📋 My Parcels` or with `/name <tracking_number> <custom name>`.\n\n"
        "*Multiple tracking numbers:*\n"
        "You can enter multiple numbers separated by spaces or commas (e.g. `UG251338889MV XX123456789BD`).\n\n"
        "*Commands (Optional):*\n"
        "`/track <number>` • `/status <number>` • `/name <number> <label>` • `/my` • `/stop <number>`"
    )

    await update.message.reply_text(
        help_text,
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )

