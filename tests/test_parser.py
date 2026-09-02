import unittest
from bdpost.parser import parse_tracking_response, generate_event_hash, is_delivered, is_dispatched
from bdpost.validator import validate_and_normalize_tracking_number


class TestBangladeshPostParser(unittest.TestCase):

    def test_single_tracking_event(self):
        html = """
        <table>
            <tr>
                <th>Event Date</th><th>Origin Country</th><th>Destination Country</th><th>Location</th><th>Status</th>
            </tr>
            <tr>
                <td>12-08-2026 06:46:51</td>
                <td>Maldives</td>
                <td>Not Found</td>
                <td>DHAKA AIRPORT SORTING OFFICE</td>
                <td>Incomming</td>
            </tr>
        </table>
        """
        events = parse_tracking_response(html)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_date"], "12-08-2026 06:46:51")
        self.assertEqual(events[0]["origin_country"], "Maldives")
        self.assertEqual(events[0]["destination_country"], "Not Found")
        self.assertEqual(events[0]["location"], "DHAKA AIRPORT SORTING OFFICE")
        self.assertEqual(events[0]["status"], "Incomming")
        self.assertTrue(bool(events[0]["event_hash"]))

    def test_multiple_tracking_events(self):
        html = """
        <table>
            <tr><th>Date</th><th>Origin</th><th>Dest</th><th>Location</th><th>Status</th></tr>
            <tr><td>14-08-2026 09:15:22</td><td>Maldives</td><td>Bangladesh</td><td>Mirpur 1</td><td>Dispatched from post office</td></tr>
            <tr><td>13-08-2026 10:20:03</td><td>Maldives</td><td>Bangladesh</td><td>Mirpur 1</td><td>Arrived at post office</td></tr>
        </table>
        """
        events = parse_tracking_response(html)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["status"], "Dispatched from post office")
        self.assertEqual(events[1]["status"], "Arrived at post office")
        self.assertNotEqual(events[0]["event_hash"], events[1]["event_hash"])

    def test_no_tracking_result_or_empty(self):
        html = "<div>No records found</div>"
        events = parse_tracking_response(html)
        self.assertEqual(events, [])

        events_empty = parse_tracking_response("")
        self.assertEqual(events_empty, [])

    def test_malformed_html(self):
        html = "<table><tr><td>incomplete"
        events = parse_tracking_response(html)
        self.assertEqual(events, [])

    def test_same_status_different_location_hash(self):
        event1 = {
            "event_date": "13-08-2026 10:00:00",
            "origin_country": "BD",
            "destination_country": "BD",
            "location": "Location A",
            "status": "Arrived at post office"
        }
        event2 = {
            "event_date": "13-08-2026 10:00:00",
            "origin_country": "BD",
            "destination_country": "BD",
            "location": "Location B",
            "status": "Arrived at post office"
        }
        hash1 = generate_event_hash(event1)
        hash2 = generate_event_hash(event2)
        self.assertNotEqual(hash1, hash2)

    def test_status_helpers(self):
        self.assertTrue(is_delivered("Item Delivered successfully"))
        self.assertTrue(is_delivered("DELIVERED"))
        self.assertFalse(is_delivered("In transit"))

        self.assertTrue(is_dispatched("Dispatched from office"))
        self.assertFalse(is_dispatched("Arrived"))


class TestTrackingValidator(unittest.TestCase):

    def test_validation(self):
        self.assertEqual(validate_and_normalize_tracking_number(" ug251338889mv "), "UG251338889MV")
        self.assertEqual(validate_and_normalize_tracking_number("XX-1234-BD"), "XX-1234-BD")
        self.assertIsNone(validate_and_normalize_tracking_number(""))
        self.assertIsNone(validate_and_normalize_tracking_number("   "))
        self.assertIsNone(validate_and_normalize_tracking_number("AB"))  # too short
        self.assertIsNone(validate_and_normalize_tracking_number("A" * 40))  # too long
        self.assertIsNone(validate_and_normalize_tracking_number("UG2513<script>"))

    def test_extract_multiple_tracking_numbers(self):
        from bdpost.validator import extract_tracking_numbers
        
        # Test space separated list
        valid, invalid = extract_tracking_numbers(["UG251338889MV", "XX123456789BD", "bad!"])
        self.assertEqual(valid, ["UG251338889MV", "XX123456789BD"])
        self.assertEqual(invalid, ["bad!"])

        # Test comma separated string or single arg
        valid, invalid = extract_tracking_numbers(["UG251338889MV,XX123456789BD", "invalid<>"])
        self.assertEqual(valid, ["UG251338889MV", "XX123456789BD"])
        self.assertEqual(invalid, ["invalid<>"])

        # Test duplicates handling
        valid, invalid = extract_tracking_numbers(["UG251338889MV", "ug251338889mv"])
        self.assertEqual(valid, ["UG251338889MV"])
        self.assertEqual(invalid, [])


    def test_real_delivered_html_response(self):
        html = '"<div class=\\"table-responsive\\">\\r\\n\\t\\t\\t\\t\\t    <table id=\\"tbl_result\\" class=\\"table table bordered\\" style=\\"font-size:13px\\" >\\r\\n\\t\\t\\t\\t\\t\\t    <tr bgcolor=\\"#CCCCCC\\">\\r\\n\\t\\t\\t\\t\\t\\t\\t   <th width=\\"160\\">Event Date<\\/th>\\r\\n\\t\\t\\t\\t\\t\\t\\t   <th>Origin Country<\\/th>\\r\\n\\t\\t\\t\\t\\t\\t\\t   <th>Destination Country<\\/th>\\r\\n\\t\\t\\t\\t\\t\\t\\t   <th>Location<\\/th>\\r\\n\\t\\t\\t\\t\\t\\t\\t   <th>Status<\\/th>\\r\\n\\t\\t\\t\\t\\t\\t    <\\/tr>\\r\\n\\t\\t\\t    <tr>\\r\\n\\t\\t\\t\\t   <td>13-08-2026 05:42:27<\\/td>\\r\\n\\t\\t\\t\\t   <td>Maldives<\\/td>\\r\\n\\t\\t\\t\\t   <td>Not Found<\\/td>\\r\\n\\t\\t\\t\\t    <td>DHAKA FOREIGN POST OFFICE<\\/td>\\r\\n\\t\\t\\t\\t   <td>Incomming<\\/td>\\r\\n\\t\\t    \\t<\\/tr>\\r\\n\\t\\t\\t    <tr>\\r\\n\\t\\t\\t\\t   <td>17-08-2026 12:58:56<\\/td>\\r\\n\\t\\t\\t\\t   <td>Maldives<\\/td>\\r\\n\\t\\t\\t\\t   <td>Bangladesh<\\/td>\\r\\n\\t\\t\\t\\t    <td>Bogra HO<\\/td>\\r\\n\\t\\t\\t\\t   <td>Arrived at post office<\\/td>\\r\\n\\t\\t    \\t<\\/tr>\\r\\n\\t\\t\\t    <tr>\\r\\n\\t\\t\\t\\t   <td>17-08-2026 13:11:07<\\/td>\\r\\n\\t\\t\\t\\t   <td>Maldives<\\/td>\\r\\n\\t\\t\\t\\t   <td>Bangladesh<\\/td>\\r\\n\\t\\t\\t\\t    <td>Bogra HO<\\/td>\\r\\n\\t\\t\\t\\t   <td>Delivered<\\/td>\\r\\n\\t\\t    \\t<\\/tr>"'
        events = parse_tracking_response(html)
        self.assertEqual(len(events), 3)
        self.assertEqual(events[0]["status"], "Incomming")
        self.assertEqual(events[1]["status"], "Arrived at post office")
        self.assertEqual(events[2]["status"], "Delivered")
        self.assertEqual(events[2]["location"], "Bogra HO")
        self.assertTrue(is_delivered(events[2]["status"]))

        from bdpost.parser import get_latest_event
        latest = get_latest_event(events)
        self.assertEqual(latest["status"], "Delivered")


if __name__ == "__main__":
    unittest.main()
