import unittest
import os
from bdpost.parser import is_bdpost_handover_event, is_delivered
from database.db import Database


class TestHandoverAndDualTracking(unittest.TestCase):

    def setUp(self):
        self.db_path = "test_handover.db"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        self.db = Database(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_handover_detection_rules(self):
        airport_event = {
            "event_date": "25-08-2026 04:26:14",
            "origin_country": "Maldives",
            "destination_country": "Not Found",
            "location": "DHAKA AIRPORT SORTING OFFICE",
            "status": "Incomming"
        }
        self.assertTrue(is_bdpost_handover_event(airport_event))

        so_event = {
            "event_date": "27-08-2026 13:23:19",
            "origin_country": "Maldives",
            "destination_country": "Bangladesh",
            "location": "Dairy Farm SO",
            "status": "Arrived at post office"
        }
        self.assertTrue(is_bdpost_handover_event(so_event))

        delivered_event = {
            "event_date": "17-08-2026 13:11:07",
            "origin_country": "Maldives",
            "destination_country": "Bangladesh",
            "location": "Bogra HO",
            "status": "Delivered"
        }
        self.assertTrue(is_bdpost_handover_event(delivered_event))
        self.assertTrue(is_delivered(delivered_event["status"]))

        weak_event = {
            "event_date": "10-08-2026 10:00:00",
            "origin_country": "China",
            "destination_country": "Unknown",
            "location": "",
            "status": "Information received"
        }
        self.assertFalse(is_bdpost_handover_event(weak_event))

    def test_database_dual_tracking_lifecycle(self):
        tracking_number = "UG251542831MV"

        # 1. User A & User B subscribe to AliExpress tracking
        self.db.add_or_reactivate_tracking(
            telegram_id=1001,
            tracking_number=tracking_number,
            cainiao_enabled=1,
            bdpost_enabled=1,
            handover_detected=0
        )
        self.db.add_or_reactivate_tracking(
            telegram_id=1002,
            tracking_number=tracking_number,
            cainiao_enabled=1,
            bdpost_enabled=1,
            handover_detected=0
        )

        # Verify active providers
        active = self.db.get_active_trackings_with_providers()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["tracking_number"], tracking_number)
        self.assertEqual(active[0]["cainiao_enabled"], 1)
        self.assertEqual(active[0]["bdpost_enabled"], 1)
        self.assertEqual(active[0]["handover_detected"], 0)

        # 2. Handover occurs: parcel arrives at Dhaka Airport
        self.db.set_handover_detected(tracking_number, "sample_hash_123")

        # Verify Cainiao is now disabled, BD Post is active
        active_after = self.db.get_active_trackings_with_providers()
        self.assertEqual(len(active_after), 1)
        self.assertEqual(active_after[0]["cainiao_enabled"], 0)
        self.assertEqual(active_after[0]["bdpost_enabled"], 1)
        self.assertEqual(active_after[0]["handover_detected"], 1)
        self.assertEqual(active_after[0]["handover_event_hash"], "sample_hash_123")

        # 3. Delivery completes: parcel is delivered
        count = self.db.deactivate_tracking_number(tracking_number)
        self.assertEqual(count, 2)
        self.assertEqual(len(self.db.get_active_trackings_with_providers()), 0)


    def test_tracking_chain_discovery_and_association(self):
        # User 1 enters AP...
        shipment_id = self.db.get_or_create_shipment("AP00839881455575", telegram_id=2001, label="AliExpress Item")
        self.assertIsNotNone(shipment_id)

        # System discovers CNG... and links it
        self.db.link_tracking_number(shipment_id, "CNG0083981455575", source="cainiao", num_type="latest", discovered_from="AP00839881455575")

        # System discovers UG... and links it
        self.db.link_tracking_number(shipment_id, "UG251350054MV", source="bdpost", num_type="local", discovered_from="CNG0083981455575")

        chain = self.db.get_tracking_chain_numbers(shipment_id)
        self.assertEqual(chain, ["AP00839881455575", "CNG0083981455575", "UG251350054MV"])

        # Another user queries by CNG... or UG... -> finds the same shipment!
        shipment_cng = self.db.get_shipment_by_tracking_number("CNG0083981455575")
        self.assertIsNotNone(shipment_cng)
        self.assertEqual(shipment_cng["id"], shipment_id)

        shipment_ug = self.db.get_shipment_by_tracking_number("UG251350054MV")
        self.assertIsNotNone(shipment_ug)
        self.assertEqual(shipment_ug["id"], shipment_id)


if __name__ == "__main__":
    unittest.main()
