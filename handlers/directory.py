import html
import logging
from typing import Optional
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

import config
from database.db import Database
from bdpost.directory import search_post_offices, get_fallback_contact_for_office
from handlers.cleanup import cleanup_previous_messages, record_prompt_message
from handlers.keyboards import get_main_keyboard, get_cancel_keyboard

logger = logging.getLogger(__name__)


async def postcode_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Looks up Bangladesh post offices by postcode or area name with 3-tier verified contacts.
    """
    if not update.message or not update.effective_user:
        return

    await cleanup_previous_messages(update, context)
    args = context.args or []

    if not args:
        context.user_data["state"] = "waiting_for_postcode_query"
        prompt = await update.message.reply_text(
            "📮 <b>Bangladesh Post Office & Postcode Finder</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Search across 1,349 post offices nationwide.\n\n"
            "Please send a <b>4-digit Postcode</b> or <b>Area/District Name</b>\n"
            "<i>(e.g., <code>1216</code>, <code>Mirpur</code>, <code>Uttara</code>, <code>Agrabad</code>, <code>Sylhet</code>)</i>:",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
        record_prompt_message(context, prompt.message_id)
        return

    query = " ".join(args).strip()
    await execute_postcode_search(update, context, query)


async def execute_postcode_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str) -> None:
    results = search_post_offices(query, limit=5)

    if not results:
        await update.message.reply_text(
            f"🔍 No post offices found matching <code>{html.escape(query)}</code>.\n"
            "Please check the spelling or try searching by district name (e.g. <code>Dhaka</code>, <code>Chittagong</code>).",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )
        return

    for po in results:
        contact = get_fallback_contact_for_office(po)
        name = html.escape(po["post_office"])
        code = html.escape(po["post_code"])
        thana = html.escape(po["thana"])
        dist = html.escape(po["district"])
        div = html.escape(po["division"])

        lines = [
            f"📮 <b>{name} Sub Post Office</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"📌 <b>Postcode:</b> <code>{code}</code>",
            f"📍 <b>Thana:</b> {thana} | <b>District:</b> {dist}",
            f"🌍 <b>Division:</b> {div}",
            ""
        ]

        if contact["tier"] == 1:
            lines.append(f"📞 <b>Direct Office Phone:</b> <code>{contact['phone']}</code>")
        else:
            lines.append(f"📞 <b>Direct Phone:</b> <i>No direct landline listed</i>")
            lines.append(f"🏛️ <b>{contact['type']}:</b>")
            if contact.get("officer"):
                lines.append(f"• <b>Officer:</b> {html.escape(contact['officer'])} ({html.escape(contact.get('designation', ''))})")
            if contact.get("office_name"):
                lines.append(f"• <b>Office:</b> {html.escape(contact['office_name'])}")
            if contact.get("mobile"):
                lines.append(f"• <b>Mobile:</b> <code>{contact['mobile']}</code>")
            if contact.get("phone"):
                lines.append(f"• <b>Landline:</b> <code>{contact['phone']}</code>")

        lines.append("━━━━━━━━━━━━━━━━━━━━")

        keyboard = [
            [
                InlineKeyboardButton("⚠️ Report / Update Phone", callback_data=f"report_phone:{code}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "\n".join(lines),
            reply_markup=reply_markup,
            parse_mode="HTML"
        )


async def handle_report_phone_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    await query.answer()
    postcode = query.data.split(":", 1)[1] if ":" in query.data else ""
    context.user_data["state"] = "waiting_for_phone_report"
    context.user_data["report_postcode"] = postcode

    prompt = await query.message.reply_text(
        f"📝 <b>Submit Phone Number Update (Postcode: {postcode})</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Please send the correct or updated phone/mobile number for this post office.\n"
        "Our team will verify and update the database.\n"
        "━━━━━━━━━━━━━━━━━━━━",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    record_prompt_message(context, prompt.message_id)


async def process_phone_report_submission(update: Update, context: ContextTypes.DEFAULT_TYPE, submitted_text: str) -> None:
    await cleanup_previous_messages(update, context)
    context.user_data.pop("state", None)
    postcode = context.user_data.pop("report_postcode", "Unknown")
    user = update.effective_user
    db: Database = context.bot_data["db"]

    uid = user.id
    uname = f"@{user.username}" if user.username else "No username"
    fname = html.escape(user.full_name or "User")
    clean_phone = submitted_text.strip()

    # Update database immediately
    db.update_post_office_phone(postcode, clean_phone, source=f"crowdsourced_by_{uid}")

    # Forward correction to Admin directly
    admin_msg = (
        "📢 <b>Post Office Phone Contribution Submitted</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📮 <b>Postcode:</b> <code>{postcode}</code>\n"
        f"👤 <b>Submitted By:</b> {fname} ({uname}) [ID: <code>{uid}</code>]\n"
        f"📞 <b>Phone Number:</b> <code>{html.escape(clean_phone)}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )
    try:
        await context.bot.send_message(
            chat_id=config.ADMIN_CHAT_ID,
            text=admin_msg,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error("Failed to forward phone report to admin: %s", e)

    await update.message.reply_text(
        "🙏 <b>Thank You for Your Contribution!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"The phone number for Postcode <code>{postcode}</code> has been recorded and updated.\n"
        "━━━━━━━━━━━━━━━━━━━━",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )
