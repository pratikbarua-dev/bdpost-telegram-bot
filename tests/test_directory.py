import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

if "httpx" not in sys.modules:
    sys.modules["httpx"] = MagicMock()

if "telegram" not in sys.modules or not hasattr(sys.modules.get("telegram"), "__path__"):
    sys.modules["telegram"] = MagicMock()
    sys.modules["telegram.error"] = MagicMock()
    sys.modules["telegram.ext"] = MagicMock()

from bdpost.post_office_data import clean_phone_number
from bdpost.directory import (
    search_post_offices,
    get_fallback_contact_for_office,
    match_location_to_post_office
)
from handlers.directory import postcode_command, execute_postcode_search, process_phone_report_submission


class TestDirectoryAndContacts(unittest.IsolatedAsyncioTestCase):

    def test_phone_normalization_and_validation(self):
        # 1. Standard mobile
        ph, ptype = clean_phone_number("01712-345678")
        self.assertEqual(ptype, "MOBILE")
        self.assertEqual(ph, "01712-345678")

        # 2. Mobile with Bengali digits
        ph_bn, ptype_bn = clean_phone_number("০১৯১৫৮৪০৫৩৭")
        self.assertEqual(ptype_bn, "MOBILE")
        self.assertEqual(ph_bn, "01915-840537")

        # 3. Mobile missing leading 0
        ph_lead, ptype_lead = clean_phone_number("1715258986")
        self.assertEqual(ptype_lead, "MOBILE")
        self.assertEqual(ph_lead, "01715-258986")

        # 4. BTCL Landline
        ph_land, ptype_land = clean_phone_number("০২-৫৮১৬০৭৪০")
        self.assertEqual(ptype_land, "LANDLINE")

        # 5. Invalid / broken
        ph_inv, ptype_inv = clean_phone_number("050412467319")
        self.assertEqual(ptype_inv, "INVALID")

    def test_postcode_search(self):
        # Search by exact 4-digit code
        results = search_post_offices("1216", limit=5)
        self.assertTrue(len(results) >= 1)
        self.assertEqual(results[0]["post_code"], "1216")
        self.assertEqual(results[0]["district"], "Dhaka")

        # Search by area name
        results_area = search_post_offices("Mirpur", limit=5)
        self.assertTrue(len(results_area) >= 1)
        self.assertTrue(any("Mirpur" in r["post_office"] or "Mirpur" in r["thana"] for r in results_area))

    def test_fallback_contact_resolution(self):
        # Office without direct phone falls back to Regional Circle / Directorate
        sample_office = {
            "post_office": "Bamna",
            "post_code": "8730",
            "thana": "Bamna",
            "district": "Barguna",
            "division": "Barisal",
            "phone": None
        }
        contact = get_fallback_contact_for_office(sample_office)
        self.assertIn(contact["tier"], [2, 3])
        self.assertIsNotNone(contact.get("phone") or contact.get("mobile"))

    def test_location_matcher(self):
        matched = match_location_to_post_office("Mirpur 1 SO")
        self.assertIsNotNone(matched)
        po, contact = matched
        self.assertEqual(po["post_code"], "1216")

    async def test_postcode_command_execution(self):
        update = MagicMock()
        update.effective_user.id = 12345
        update.message = AsyncMock()

        context = MagicMock()
        context.args = ["1216"]

        with patch("handlers.directory.cleanup_previous_messages", new_callable=AsyncMock):
            await postcode_command(update, context)

        update.message.reply_text.assert_called_once()
        self.assertIn("1216", update.message.reply_text.call_args[0][0])
        self.assertIn("Postcode", update.message.reply_text.call_args[0][0])

    async def test_process_phone_report_submission(self):
        update = MagicMock()
        update.effective_user.id = 12345
        update.effective_user.username = "contributor"
        update.effective_user.full_name = "Good Contributor"
        update.message = AsyncMock()

        context = MagicMock()
        context.user_data = {"report_postcode": "1216"}
        context.bot = AsyncMock()

        with patch("handlers.directory.cleanup_previous_messages", new_callable=AsyncMock):
            with patch("config.ADMIN_CHAT_ID", 6856606568):
                await process_phone_report_submission(update, context, "01700112233")

        context.bot.send_message.assert_called_once()
        admin_call_text = context.bot.send_message.call_args.kwargs["text"]
        self.assertIn("1216", admin_call_text)
        self.assertIn("01700112233", admin_call_text)

        update.message.reply_text.assert_called_once()
        self.assertIn("Thank You for Your Contribution", update.message.reply_text.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
