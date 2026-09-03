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

from database.db import Database
from handlers.admin import admin_command, is_admin


class TestAdminModule(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.db_path = "test_admin_db.sqlite"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        self.db = Database(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_is_admin_check(self):
        with patch("config.ADMIN_CHAT_ID", 6856606568):
            self.assertTrue(is_admin(6856606568))
            self.assertFalse(is_admin(123456789))

    def test_admin_user_and_parcel_control(self):
        user_id = 999888
        tracking_num = "UG251781108MV"

        # 1. Create user and shipment
        self.db.get_or_create_user(user_id, username="testuser", full_name="Test User")
        sid = self.db.get_or_create_shipment(tracking_num, telegram_id=user_id, label="My Item")

        # 2. Verify admin stats
        stats = self.db.get_system_stats()
        self.assertEqual(stats["total_users"], 1)
        self.assertEqual(stats["total_shipments"], 1)
        self.assertEqual(stats["active_shipments"], 1)

        # 3. View user admin profile
        profile = self.db.get_user_admin_profile("999888")
        self.assertIsNotNone(profile)
        self.assertEqual(profile["username"], "testuser")
        self.assertEqual(len(profile["parcels"]), 1)
        self.assertEqual(profile["parcels"][0]["label"], "My Item")

        # 4. Admin force handover
        self.db.admin_force_shipment_state(sid, cainiao_enabled=0, bdpost_enabled=1, handover_detected=1)
        shipment = self.db.get_shipment(sid)
        self.assertEqual(shipment["cainiao_enabled"], 0)
        self.assertEqual(shipment["handover_detected"], 1)

        # 5. Admin ban/unban
        self.db.set_user_ban_status(user_id, is_banned=True)
        self.assertTrue(self.db.is_user_banned(user_id))
        self.db.set_user_ban_status(user_id, is_banned=False)
        self.assertFalse(self.db.is_user_banned(user_id))

        # 6. Admin delete shipment
        deleted = self.db.admin_delete_shipment(sid)
        self.assertTrue(deleted)
        self.assertIsNone(self.db.get_shipment(sid))

    async def test_admin_command_unauthorized_user_ignored(self):
        update = MagicMock()
        update.effective_user.id = 111222  # Not admin
        update.message = AsyncMock()

        context = MagicMock()
        context.args = []
        context.bot_data = {"db": self.db}

        with patch("config.ADMIN_CHAT_ID", 6856606568):
            await admin_command(update, context)

        update.message.reply_text.assert_not_called()

    async def test_admin_command_dashboard_for_authorized_admin(self):
        update = MagicMock()
        update.effective_user.id = 6856606568  # Authorized admin
        update.message = AsyncMock()

        context = MagicMock()
        context.args = []
        context.bot_data = {"db": self.db}

        with patch("config.ADMIN_CHAT_ID", 6856606568):
            with patch("handlers.admin.cleanup_previous_messages", new_callable=AsyncMock):
                await admin_command(update, context)

        update.message.reply_text.assert_called_once()
        self.assertIn("Admin Control Center", update.message.reply_text.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
