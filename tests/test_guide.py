import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from telegram import Update, User, Message, CallbackQuery
from handlers.guide import (
    get_guide_main_keyboard,
    get_guide_back_keyboard,
    guide_command,
    guide_callback_router
)
from bdpost.formatter import get_delivery_channel_badge, get_status_smart_insight, format_status_message


class TestGuideHandler(unittest.IsolatedAsyncioTestCase):

    async def test_guide_command(self):
        update = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 12345
        update.message = MagicMock()
        update.message.reply_text = AsyncMock()

        context = MagicMock()
        await guide_command(update, context)

        update.message.reply_text.assert_called_once()
        args, kwargs = update.message.reply_text.call_args
        self.assertIn("মেগা গাইড", args[0])
        self.assertEqual(kwargs.get("parse_mode"), "HTML")
        self.assertIsNotNone(kwargs.get("reply_markup"))

    async def test_guide_callbacks(self):
        context = MagicMock()
        for topic in ["menu", "courier", "stages", "postoffice", "customs", "deals", "faq"]:
            update = MagicMock()
            update.effective_user = MagicMock()
            query = MagicMock()
            query.data = f"guide:{topic}"
            query.answer = AsyncMock()
            query.edit_message_text = AsyncMock()
            update.callback_query = query

            handled = await guide_callback_router(update, context)
            self.assertTrue(handled, f"Topic {topic} should be handled")
            query.edit_message_text.assert_called_once()

    def test_delivery_channel_badge(self):
        redx_badge = get_delivery_channel_badge("BR006144481MG")
        self.assertIn("RedX Courier", redx_badge)

        redx_chain_badge = get_delivery_channel_badge("AP00837629440572", ["BR006035782MG"])
        self.assertIn("RedX Courier", redx_chain_badge)

        post_badge = get_delivery_channel_badge("UG251781108MV")
        self.assertIn("Bangladesh Post Office", post_badge)

    def test_smart_insights(self):
        insight_airport = get_status_smart_insight("Arrived at linehaul office", "", "cainiao")
        self.assertIsNotNone(insight_airport)
        self.assertIn("পার্সেল বাংলাদেশে এসে পৌঁছেছে", insight_airport)

        insight_flight = get_status_smart_insight("Awaiting flight", "", "cainiao")
        self.assertIsNotNone(insight_flight)
        self.assertIn("ফ্লাইটের অপেক্ষায়", insight_flight)

        insight_delivered = get_status_smart_insight("Delivered", "", "bdpost")
        self.assertIsNotNone(insight_delivered)
        self.assertIn("পোস্ট অফিসের সিস্টেমে 'Delivered'", insight_delivered)

        insight_wrongly = get_status_smart_insight("Item wrongly directed forward", "", "bdpost")
        self.assertIsNotNone(insight_wrongly)
        self.assertIn("জেলা প্রধান ডাকঘর", insight_wrongly)

    def test_format_status_message_with_insights(self):
        event = {
            "source": "cainiao",
            "status": "Arrived at linehual office",
            "event_date": "2026-09-17 12:00:00",
            "description": "Carrier note: Arrived at linehual office",
            "origin_country": "Mainland China",
            "destination_country": "Bangladesh"
        }
        msg = format_status_message("UG251781108MV", event)
        self.assertIn("Delivery Channel:", msg)
        self.assertIn("Bangladesh Post Office", msg)
        self.assertIn("পার্সেল বাংলাদেশে এসে পৌঁছেছে", msg)


if __name__ == "__main__":
    unittest.main()
