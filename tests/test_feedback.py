import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Mock telegram modules if not installed in testing environment
if "telegram" not in sys.modules or not hasattr(sys.modules.get("telegram"), "__path__"):
    tg = MagicMock()
    sys.modules["telegram"] = tg
    sys.modules["telegram.error"] = MagicMock()
    sys.modules["telegram.ext"] = MagicMock()

from handlers.feedback import feedback_command, handle_feedback_message


class TestFeedback(unittest.IsolatedAsyncioTestCase):

    async def test_feedback_command_prompts_user_when_no_args(self):
        update = MagicMock()
        update.effective_user.id = 12345
        update.effective_user.first_name = "Test"
        update.effective_user.username = "tester"
        update.effective_user.full_name = "Test User"
        message = AsyncMock()
        message.message_id = 101
        update.message = message
        prompt_mock = AsyncMock()
        prompt_mock.message_id = 102
        message.reply_text.return_value = prompt_mock

        context = MagicMock()
        context.user_data = {}
        context.args = []

        with patch("handlers.feedback.cleanup_previous_messages", new_callable=AsyncMock):
            await feedback_command(update, context)

        self.assertEqual(context.user_data.get("state"), "waiting_for_feedback")
        message.reply_text.assert_called_once()
        self.assertIn("Feedback", message.reply_text.call_args[0][0])

    async def test_feedback_command_processes_direct_args(self):
        update = MagicMock()
        update.effective_user.id = 12345
        update.effective_user.first_name = "Test"
        update.effective_user.username = "tester"
        update.effective_user.full_name = "Test User"
        message = AsyncMock()
        update.message = message

        context = MagicMock()
        context.user_data = {}
        context.args = ["Awesome", "bot!"]
        context.bot = AsyncMock()

        with patch("handlers.feedback.cleanup_previous_messages", new_callable=AsyncMock):
            with patch("config.ADMIN_CHAT_ID", 99999):
                await feedback_command(update, context)

        # Should forward to admin chat
        context.bot.send_message.assert_called_once()
        sent_text = context.bot.send_message.call_args.kwargs["text"]
        self.assertIn("Awesome bot!", sent_text)
        self.assertIn("12345", sent_text)

        # Should send thank you message to user
        message.reply_text.assert_called_once()
        self.assertIn("Thank You for Your Feedback", message.reply_text.call_args[0][0])

    async def test_handle_feedback_message(self):
        update = MagicMock()
        update.effective_user.id = 12345
        update.effective_user.first_name = "Test"
        update.effective_user.username = "tester"
        update.effective_user.full_name = "Test User"
        message = AsyncMock()
        update.message = message

        context = MagicMock()
        context.user_data = {"state": "waiting_for_feedback"}
        context.bot = AsyncMock()

        with patch("handlers.feedback.cleanup_previous_messages", new_callable=AsyncMock):
            await handle_feedback_message(update, context, "Here is my suggestion")

        self.assertNotIn("state", context.user_data)
        message.reply_text.assert_called_once()
        self.assertIn("Thank You for Your Feedback", message.reply_text.call_args[0][0])


if __name__ == "__main__":
    unittest.main()

