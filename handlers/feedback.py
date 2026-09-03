import datetime
import html
import logging
from telegram import Update
from telegram.ext import ContextTypes

import config
from handlers.keyboards import get_main_keyboard, get_cancel_keyboard
from handlers.cleanup import cleanup_previous_messages, record_prompt_message

logger = logging.getLogger(__name__)


async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Prompts the user to send feedback, bug reports, or feature suggestions.
    """
    if not update.effective_user or not update.message:
        return

    await cleanup_previous_messages(update, context)

    # Check if feedback text was passed directly with command: /feedback <message>
    if context.args:
        feedback_text = " ".join(context.args).strip()
        await _process_and_forward_feedback(update, context, feedback_text)
        return

    context.user_data["state"] = "waiting_for_feedback"
    prompt = await update.message.reply_text(
        "💬 <b>Send Us Feedback & Suggestions</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "We'd love to hear from you!\n\n"
        "Please type your message, feedback, feature request, or bug report below.\n"
        "━━━━━━━━━━━━━━━━━━━━",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    record_prompt_message(context, prompt.message_id)


async def handle_feedback_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    await cleanup_previous_messages(update, context)
    context.user_data.pop("state", None)
    await _process_and_forward_feedback(update, context, text)


async def _process_and_forward_feedback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    feedback_text: str
) -> None:
    user = update.effective_user
    username = f"@{user.username}" if user.username else "No username"
    full_name = html.escape(user.full_name or "Anonymous")
    user_id = user.id
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    escaped_feedback = html.escape(feedback_text.strip())

    logger.info("Feedback received from user %d (%s): %s", user_id, username, feedback_text)

    # If ADMIN_CHAT_ID is configured, forward feedback directly to admin's Telegram
    if config.ADMIN_CHAT_ID:
        admin_msg = (
            "📬 <b>New User Feedback</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>From:</b> {full_name} ({username})\n"
            f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
            f"🕐 <b>Date:</b> {now}\n\n"
            f"💬 <b>Message:</b>\n{escaped_feedback}\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
        try:
            await context.bot.send_message(
                chat_id=config.ADMIN_CHAT_ID,
                text=admin_msg,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error("Failed to forward feedback to ADMIN_CHAT_ID %s: %s", config.ADMIN_CHAT_ID, e)

    # Thank the user
    await update.message.reply_text(
        "🙏 <b>Thank You for Your Feedback!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Your message has been received. We appreciate your suggestions and support!\n"
        "━━━━━━━━━━━━━━━━━━━━",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )
