import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError

logger = logging.getLogger(__name__)


def record_prompt_message(context: ContextTypes.DEFAULT_TYPE, message_id: int) -> None:
    """
    Records temporary prompt / helper message IDs to delete them later.
    """
    if "cleanup_message_ids" not in context.user_data:
        context.user_data["cleanup_message_ids"] = []
    context.user_data["cleanup_message_ids"].append(message_id)


async def cleanup_previous_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Deletes recorded temporary bot prompts or user commands to keep the chat clean.
    """
    if not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    message_ids = context.user_data.pop("cleanup_message_ids", [])

    for mid in message_ids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except TelegramError:
            pass
