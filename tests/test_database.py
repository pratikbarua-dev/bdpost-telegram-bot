import unittest
import os
from database.db import Database


class TestDatabaseOperations(unittest.TestCase):

    def setUp(self):
        self.db_path = "test_bdpost.db"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        self.db = Database(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_user_and_tracking_subscription(self):
        self.db.add_or_reactivate_tracking(telegram_id=12345, tracking_number="UG251338889MV")
        self.db.add_or_reactivate_tracking(telegram_id=67890, tracking_number="UG251338889MV")

        active_numbers = self.db.get_all_active_tracking_numbers()
        self.assertEqual(active_numbers, ["UG251338889MV"])

        subscribers = self.db.get_subscribers_for_tracking("UG251338889MV")
        self.assertEqual(set(subscribers), {12345, 67890})

        # Test stop tracking
        self.db.stop_tracking(12345, "UG251338889MV")
        subscribers_after = self.db.get_subscribers_for_tracking("UG251338889MV")
        self.assertEqual(subscribers_after, [67890])

    def test_event_deduplication(self):
        events = [
            {
                "event_date": "13-08-2026 10:00:00",
                "origin_country": "Maldives",
                "destination_country": "Bangladesh",
                "location": "Mirpur 1",
                "status": "Arrived at post office",
                "event_hash": "hash_123"
            }
        ]
        # First save: should insert
        new_events = self.db.save_events("UG251338889MV", events)
        self.assertEqual(len(new_events), 1)

        # Second save with identical event: should be deduplicated
        new_events_dup = self.db.save_events("UG251338889MV", events)
        self.assertEqual(len(new_events_dup), 0)


    def test_stop_all_trackings(self):
        self.db.add_or_reactivate_tracking(telegram_id=999, tracking_number="NUM1")
        self.db.add_or_reactivate_tracking(telegram_id=999, tracking_number="NUM2")
        self.db.add_or_reactivate_tracking(telegram_id=999, tracking_number="NUM3")
        self.db.add_or_reactivate_tracking(telegram_id=888, tracking_number="NUM1")

        stopped = self.db.stop_all_trackings(telegram_id=999)
        self.assertEqual(stopped, 3)

        trackings_999 = self.db.get_user_active_trackings(999)
        self.assertEqual(len(trackings_999), 0)

        # 888 should still be active for NUM1
        trackings_888 = self.db.get_user_active_trackings(888)
        self.assertEqual(len(trackings_888), 1)


    def test_deactivate_tracking_number_on_delivery(self):
        self.db.add_or_reactivate_tracking(telegram_id=111, tracking_number="UG251350054MV")
        self.db.add_or_reactivate_tracking(telegram_id=222, tracking_number="UG251350054MV")

        self.assertEqual(len(self.db.get_all_active_tracking_numbers()), 1)

        # Deactivate globally upon delivery event
        count = self.db.deactivate_tracking_number("UG251350054MV")
        self.assertEqual(count, 2)
        self.assertEqual(len(self.db.get_all_active_tracking_numbers()), 0)


if __name__ == "__main__":
    unittest.main()
