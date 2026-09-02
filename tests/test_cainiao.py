import unittest
from cainiao.parser import parse_tracking_response, generate_cainiao_event_hash, get_cainiao_summary


class TestCainiaoParser(unittest.TestCase):

    def setUp(self):
        self.sample_cainiao_response = {
            "module": [
                {
                    "mailNo": "UG251542831MV",
                    "originCountry": "Mainland China",
                    "destCountry": "Bangladesh",
                    "mailType": "Economy",
                    "mailTypeDesc": "Economy shipping doesn't include tracking after a package has been handed to a destination country/region's carrier.",
                    "status": "DELIVERING",
                    "statusDesc": "Delivering",
                    "mailNoSource": "AE",
                    "detailList": [
                        {
                            "actionCode": "LH_ARRIVE",
                            "desc": "Arrived at linehual office",
                            "descTitle": "Carrier note:",
                            "standerdDesc": "Arrived at linehaul office",
                            "time": 1787737991000,
                            "timeStr": "2026-08-26 17:53:11",
                            "timeZone": "GMT+6"
                        },
                        {
                            "actionCode": "LH_DEPART",
                            "desc": "Left from departure country/region",
                            "descTitle": "Carrier note:",
                            "standerdDesc": "Departed from departure country/region",
                            "time": 1787052136000,
                            "timeStr": "2026-08-18 19:22:16",
                            "timeZone": "GMT+8"
                        },
                        {
                            "actionCode": "PU_PICKUP_SUCCESS",
                            "desc": "Accepted by carrier",
                            "descTitle": "Carrier note:",
                            "standerdDesc": "Received by logistics company",
                            "time": 1786702238000,
                            "timeStr": "2026-08-14 18:10:38",
                            "timeZone": "GMT+8"
                        }
                    ]
                }
            ],
            "success": True
        }

    def test_parse_valid_response(self):
        events = parse_tracking_response(self.sample_cainiao_response)
        self.assertEqual(len(events), 3)

        # Chronological order: oldest first (2026-08-14) to newest (2026-08-26)
        self.assertEqual(events[0]["event_date"], "2026-08-14 18:10:38")
        self.assertEqual(events[0]["action_code"], "PU_PICKUP_SUCCESS")
        self.assertEqual(events[0]["source"], "cainiao")
        self.assertEqual(events[0]["origin_country"], "Mainland China")
        self.assertEqual(events[0]["destination_country"], "Bangladesh")

        self.assertEqual(events[-1]["event_date"], "2026-08-26 17:53:11")
        self.assertEqual(events[-1]["action_code"], "LH_ARRIVE")
        self.assertEqual(events[-1]["status"], "Arrived at linehaul office")

    def test_cainiao_event_hashes_unique(self):
        events = parse_tracking_response(self.sample_cainiao_response)
        hashes = [e["event_hash"] for e in events]
        self.assertEqual(len(hashes), len(set(hashes)))

    def test_empty_or_failed_response(self):
        self.assertEqual(parse_tracking_response({}), [])
        self.assertEqual(parse_tracking_response({"success": False}), [])
        self.assertEqual(parse_tracking_response({"success": True, "module": []}), [])

    def test_fallback_to_latest_trace(self):
        data = {
            "success": True,
            "module": [
                {
                    "mailNo": "TEST12345",
                    "originCountry": "China",
                    "destCountry": "Bangladesh",
                    "latestTrace": {
                        "actionCode": "LH_ARRIVE",
                        "desc": "Arrived at linehaul office",
                        "timeStr": "2026-08-20 10:00:00",
                        "timeZone": "GMT+6"
                    }
                }
            ]
        }
        events = parse_tracking_response(data)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_date"], "2026-08-20 10:00:00")
        self.assertEqual(events[0]["status"], "Arrived at linehaul office")

    def test_cainiao_summary(self):
        summary = get_cainiao_summary(self.sample_cainiao_response)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["tracking_number"], "UG251542831MV")
        self.assertEqual(summary["origin_country"], "Mainland China")
        self.assertEqual(summary["dest_country"], "Bangladesh")
        self.assertEqual(summary["mail_no_source"], "AE")


    def test_extract_linked_tracking_numbers(self):
        from cainiao.parser import extract_linked_tracking_numbers

        # AP response with copyRealMailNo & copyVirtualMailNo
        ap_response = {
            "success": True,
            "module": [
                {
                    "mailNo": "AP00839881455575",
                    "realMailNo": "Latest Tracking Number:\tCNG00839881455575",
                    "copyRealMailNo": "CNG00839881455575",
                    "virtualMailNo": "package tracking number:\tCNG00839881455575",
                    "copyVirtualMailNo": "CNG00839881455575",
                    "detailList": []
                }
            ]
        }
        discovered = extract_linked_tracking_numbers(ap_response, "AP00839881455575")
        self.assertEqual(len(discovered), 1)
        self.assertEqual(discovered[0]["tracking_number"], "CNG00839881455575")
        self.assertEqual(discovered[0]["type"], "latest")

    def test_extract_local_ug_from_notes(self):
        from cainiao.parser import extract_linked_tracking_numbers

        cng_response = {
            "success": True,
            "module": [
                {
                    "mailNo": "CNG00839881455575",
                    "detailList": [
                        {
                            "desc": "Handed over to local carrier with tracking UG251350054MV",
                            "standerdDesc": "Handed over to destination carrier"
                        }
                    ]
                }
            ]
        }
        discovered = extract_linked_tracking_numbers(cng_response, "CNG00839881455575")
        self.assertEqual(len(discovered), 1)
        self.assertEqual(discovered[0]["tracking_number"], "UG251350054MV")
        self.assertEqual(discovered[0]["type"], "local")


if __name__ == "__main__":
    unittest.main()
