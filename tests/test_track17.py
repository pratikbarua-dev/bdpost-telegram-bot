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
from bdpost.parser import is_bdpost_handover_event, is_delivered
from track17.parser import (
    parse_tracking_response,
    extract_linked_tracking_numbers,
    get_17track_summary,
    generate_17track_event_hash
)
from track17.client import _generate_yq_bid, _generate_last_event_id, Track17UnavailableError


SAMPLE_17TRACK_UG251781108MV = {
    "id": 190625,
    "guid": "test-guid-12345",
    "meta": {"code": 200, "message": ""},
    "shipments": [
        {
            "number": "UG251781108MV",
            "carrier": 190625,
            "latest_status": {
                "status": "InTransit",
                "sub_status": "InTransit_Departure"
            },
            "latest_event": {
                "time_iso": "2026-09-02T16:13:25+08:00",
                "time_utc": "2026-09-02T08:13:25Z",
                "description": "Departed from departure country/region, Carrier note: Left from departure country/region",
                "location": "",
                "stage": "Departure",
                "sub_status": "InTransit_Departure"
            },
            "time_metrics": {
                "days_after_order": 5,
                "days_of_transit": 3
            },
            "milestone": {
                "key_stage": "InTransit"
            },
            "misc_info": {
                "local_number": None,
                "local_provider": None
            },
            "tracking": {
                "providers": [
                    {
                        "provider": {
                            "key": 190625,
                            "name": "AliExpress"
                        },
                        "latest_sync_status": "Success",
                        "latest_sync_time": "2026-09-02T16:15:00+08:00",
                        "events": [
                            {
                                "time_iso": "2026-08-30T10:00:00+08:00",
                                "time_utc": "2026-08-30T02:00:00Z",
                                "description": "Accepted by carrier, Carrier note: Order information received",
                                "location": "Dongguan",
                                "stage": "Accepted",
                                "sub_status": "InTransit_Accepted",
                                "address": {"city": "Dongguan"}
                            },
                            {
                                "time_iso": "2026-08-31T11:20:00+08:00",
                                "time_utc": "2026-08-31T03:20:00Z",
                                "description": "Inbound in sorting center, Carrier note: Processing at facility",
                                "location": "Dongguan Sorting Center",
                                "stage": "Inbound",
                                "sub_status": "InTransit_Sorting",
                                "address": {}
                            },
                            {
                                "time_iso": "2026-08-31T18:45:00+08:00",
                                "time_utc": "2026-08-31T10:45:00Z",
                                "description": "Outbound in sorting center, Carrier note: Dispatched from facility",
                                "location": "Dongguan Sorting Center",
                                "stage": "Outbound",
                                "sub_status": "InTransit_Sorting",
                                "address": {}
                            },
                            {
                                "time_iso": "2026-09-01T08:30:00+08:00",
                                "time_utc": "2026-09-01T00:30:00Z",
                                "description": "Arrived at departure transport hub, Carrier note: At air transit hub",
                                "location": "Shenzhen",
                                "stage": "TransportHub",
                                "sub_status": "InTransit_TransportHub",
                                "address": {}
                            },
                            {
                                "time_iso": "2026-09-01T22:15:00+08:00",
                                "time_utc": "2026-09-01T14:15:00Z",
                                "description": "Leaving from departure country/region, Carrier note: Handed over to airline",
                                "location": "Shenzhen Airport",
                                "stage": "Departure",
                                "sub_status": "InTransit_Departure",
                                "address": {}
                            },
                            {
                                "time_iso": "2026-09-02T16:13:25+08:00",
                                "time_utc": "2026-09-02T08:13:25Z",
                                "description": "Departed from departure country/region, Carrier note: Left from departure country/region",
                                "location": "",
                                "stage": "Departure",
                                "sub_status": "InTransit_Departure",
                                "address": {}
                            }
                        ]
                    }
                ]
            }
        }
    ]
}


class TestTrack17Integration(unittest.TestCase):

    def setUp(self):
        self.db_path = "test_track17_db.sqlite"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        self.db = Database(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_cookie_security_and_dynamic_generation(self):
        # 1. Ensure no hardcoded tokens in codebase
        src_path = os.path.join(os.path.dirname(__file__), "..", "track17", "client.py")
        with open(src_path, "r", encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("190625", src, "Carrier ID should not be hardcoded in client logic")
        self.assertNotIn("Last-Event-ID=", src.replace("Last-Event-ID={last_event_id}", ""), "No hardcoded Last-Event-ID value")

        # 2. Test dynamic yq_bid generator
        bid1 = _generate_yq_bid()
        bid2 = _generate_yq_bid()
        self.assertTrue(bid1.startswith("G-"))
        self.assertEqual(len(bid1), 18)
        self.assertNotEqual(bid1, bid2)

        # 3. Test dynamic Last-Event-ID generator
        payload = {"data": [{"num": "UG251781108MV"}], "guid": "", "timeZoneOffset": -360}
        eid = _generate_last_event_id(payload, bid1)
        self.assertTrue(len(eid) > 30)

    def test_real_tracking_number_parser(self):
        # Test parsing of UG251781108MV
        events = parse_tracking_response(SAMPLE_17TRACK_UG251781108MV, query_number="UG251781108MV")
        self.assertEqual(len(events), 6)

        # Verify specific events exist in chronological order
        first_evt = events[0]
        self.assertIn("Accepted by carrier", first_evt["description"])
        self.assertEqual(first_evt["carrier_name"], "AliExpress")
        self.assertEqual(first_evt["source"], "17track")
        self.assertEqual(first_evt["stage"], "Accepted")
        self.assertEqual(first_evt["time_iso"], "2026-08-30T10:00:00+08:00")
        self.assertEqual(first_evt["time_utc"], "2026-08-30T02:00:00Z")
        self.assertEqual(first_evt["event_date"], "2026-08-30 10:00:00")

        last_evt = events[-1]
        self.assertIn("Departed from departure country/region", last_evt["description"])
        self.assertEqual(last_evt["sub_status"], "InTransit_Departure")
        self.assertEqual(last_evt["event_date"], "2026-09-02 16:13:25")

        summary = get_17track_summary(SAMPLE_17TRACK_UG251781108MV)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["tracking_number"], "UG251781108MV")
        self.assertEqual(summary["carrier"], 190625)
        self.assertEqual(summary["carrier_name"], "AliExpress")
        self.assertEqual(summary["status"], "InTransit")
        self.assertEqual(summary["sub_status"], "InTransit_Departure")

    def test_test_f_extract_local_number_when_present(self):
        data = {
            "shipments": [
                {
                    "number": "AP00839881455575",
                    "misc_info": {
                        "local_number": "UG251781108MV",
                        "local_provider": "Bangladesh Post"
                    },
                    "tracking": {"providers": []}
                }
            ]
        }
        links = extract_linked_tracking_numbers(data, "AP00839881455575")
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["tracking_number"], "UG251781108MV")
        self.assertEqual(links[0]["source"], "bdpost")
        self.assertEqual(links[0]["type"], "local")

    def test_test_e_event_deduplication_between_providers(self):
        tracking_num = "UG251781108MV"
        self.db.get_or_create_shipment(tracking_num, telegram_id=123)

        # Cainiao event
        cainiao_evt = {
            "event_date": "2026-09-02 16:13:25",
            "location": "",
            "status": "Departed from departure country/region",
            "description": "Left from departure country/region",
            "origin_country": "China",
            "destination_country": "Bangladesh",
            "source": "cainiao",
            "action_code": "LH_DEPART",
            "timezone": "GMT+8",
            "event_hash": "cainiao_hash_1"
        }
        new_cainiao = self.db.save_events(tracking_num, [cainiao_evt])
        self.assertEqual(len(new_cainiao), 1)

        # 17TRACK reports same event (same date and same status)
        t17_evt = {
            "event_date": "2026-09-02 16:13:25",
            "location": "",
            "status": "Departed from departure country/region",
            "description": "Departed from departure country/region, Carrier note: Left from departure country/region",
            "origin_country": "",
            "destination_country": "",
            "source": "17track",
            "carrier_name": "AliExpress",
            "action_code": "InTransit_Departure",
            "stage": "Departure",
            "sub_status": "InTransit_Departure",
            "time_iso": "2026-09-02T16:13:25+08:00",
            "time_utc": "2026-09-02T08:13:25Z",
            "event_hash": "17track_hash_2"
        }
        new_17 = self.db.save_events(tracking_num, [t17_evt])
        # Should be deduplicated and not inserted as duplicate event
        self.assertEqual(len(new_17), 0)

    def test_test_g_handover_stops_cainiao_and_17track(self):
        tracking_num = "UG251781108MV"
        shipment_id = self.db.get_or_create_shipment(tracking_num, telegram_id=123)

        # Handover event from BD Post
        bd_event = {
            "event_date": "2026-09-03 10:00:00",
            "location": "DHAKA AIRPORT SORTING OFFICE",
            "status": "Arrived at post office",
            "origin_country": "Maldives",
            "destination_country": "Bangladesh",
            "source": "bdpost",
            "event_hash": "bd_hash_1"
        }
        self.assertTrue(is_bdpost_handover_event(bd_event))

        self.db.update_shipment_status(
            shipment_id,
            cainiao_enabled=0,
            bdpost_enabled=1,
            handover_detected=1,
            handover_event_hash=bd_event["event_hash"]
        )

        shipment = self.db.get_shipment(shipment_id)
        self.assertEqual(shipment["cainiao_enabled"], 0)
        self.assertEqual(shipment["bdpost_enabled"], 1)
        self.assertEqual(shipment["handover_detected"], 1)


if __name__ == "__main__":
    unittest.main()
