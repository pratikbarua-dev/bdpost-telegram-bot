import unittest
from unittest.mock import MagicMock, patch
import httpx
from database.supabase_db import SupabaseDatabase


class TestSupabaseDatabase(unittest.TestCase):

    def setUp(self):
        self.url = "https://fake.supabase.co"
        self.key = "fake-key"
        with patch("httpx.Client"):
            self.sb = SupabaseDatabase(self.url, self.key)

    def test_init_and_seed_compatibility(self):
        # Should execute without errors
        self.sb.init_db()
        with patch.object(self.sb.client, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, json=lambda: [{"id": 1}])
            self.sb.seed_post_office_directory_if_needed()

    def test_update_post_office_phone_success(self):
        with patch.object(self.sb, "_req") as mock_req:
            mock_patch_res = MagicMock(status_code=200, json=lambda: [{"id": 1, "phone": "01712-345678"}])
            mock_req.return_value = mock_patch_res

            res = self.sb.update_post_office_phone("1216", "01712-345678", source="test")
            self.assertTrue(res)
            mock_req.assert_called_once()
            call_args = mock_req.call_args
            self.assertEqual(call_args[0][0], "PATCH")
            self.assertIn("post_code=eq.1216", call_args[0][1])

    def test_update_post_office_phone_fallback_insert(self):
        # When PATCH returns empty list (postcode not found), inserts from directory
        with patch.object(self.sb, "_req") as mock_req:
            mock_patch_res = MagicMock(status_code=200, json=lambda: [])
            mock_post_res = MagicMock(status_code=201, json=lambda: [{"id": 2}])
            mock_req.side_effect = [mock_patch_res, mock_post_res]

            res = self.sb.update_post_office_phone("1216", "01712-345678", source="test")
            self.assertTrue(res)
            self.assertEqual(mock_req.call_count, 2)
            second_call = mock_req.call_args_list[1]
            self.assertEqual(second_call[0][0], "POST")
            self.assertIn("on_conflict=post_office,post_code,district", second_call[0][1])

    def test_update_post_office_phone_handles_error(self):
        with patch.object(self.sb, "_req") as mock_req:
            mock_req.side_effect = Exception("Supabase network error")
            res = self.sb.update_post_office_phone("9999", "01712-345678")
            self.assertFalse(res)

    def test_get_or_create_shipment_on_conflict(self):
        with patch.object(self.sb, "_req") as mock_req, patch.object(self.sb.client, "post") as mock_post:
            # 1. shipment_tracking_numbers lookup -> found
            mock_req.return_value = MagicMock(json=lambda: [{"shipment_id": 42}])

            sid = self.sb.get_or_create_shipment("UG251542831MV", telegram_id=12345, label="Test")
            self.assertEqual(sid, 42)

            # Check that shipment_subscribers used on_conflict=shipment_id,telegram_id
            sub_calls = [c for c in mock_req.call_args_list if "shipment_subscribers" in c[0][1]]
            self.assertTrue(len(sub_calls) >= 1)
            self.assertIn("on_conflict=shipment_id,telegram_id", sub_calls[0][0][1])

    def test_save_events_on_conflict(self):
        with patch.object(self.sb, "_req") as mock_req, patch.object(self.sb, "get_known_event_hashes", return_value=set()):
            mock_req.return_value = MagicMock(json=lambda: [])
            events = [{
                "event_hash": "hash_abc",
                "event_date": "2026-09-13 12:00",
                "status": "In Transit",
                "description": "Item forwarded",
                "source": "bdpost"
            }]

            saved = self.sb.save_events("UG251542831MV", events)
            self.assertEqual(len(saved), 1)

            post_calls = [c for c in mock_req.call_args_list if c[0][0] == "POST" and "events" in c[0][1]]
            self.assertTrue(len(post_calls) >= 1)
            self.assertIn("on_conflict=event_hash", post_calls[0][0][1])

    def test_link_tracking_number_safe_merge(self):
        with patch.object(self.sb, "_req") as mock_req:
            # 1. Lookup finds other shipment id 372
            # 2. Existing stns for shipment 390 -> ['CNG123']
            # 3. Other stns for shipment 372 -> [{'id': 10, 'tracking_number': 'CNG123'}, {'id': 11, 'tracking_number': 'BR999'}]
            # 4. Existing subs for shipment 390 -> [{'telegram_id': 111}]
            # 5. Other subs for shipment 372 -> [{'id': 20, 'telegram_id': 111}, {'id': 21, 'telegram_id': 222}]
            # 6. Delete shipment 372
            responses = [
                MagicMock(json=lambda: [{"shipment_id": 372}]), # lookup
                MagicMock(json=lambda: [{"tracking_number": "CNG123"}]), # existing stns
                MagicMock(json=lambda: [{"id": 10, "tracking_number": "CNG123"}, {"id": 11, "tracking_number": "BR999"}]), # other stns
                MagicMock(json=lambda: {}), # DELETE duplicate stn 10
                MagicMock(json=lambda: {}), # PATCH stn 11
                MagicMock(json=lambda: [{"telegram_id": 111}]), # existing subs
                MagicMock(json=lambda: [{"id": 20, "telegram_id": 111}, {"id": 21, "telegram_id": 222}]), # other subs
                MagicMock(json=lambda: {}), # DELETE duplicate sub 20
                MagicMock(json=lambda: {}), # PATCH sub 21
                MagicMock(json=lambda: {}), # DELETE shipment 372
            ]
            mock_req.side_effect = responses

            result = self.sb.link_tracking_number(390, "BR999")
            self.assertFalse(result)

            # Check that DELETE was called for duplicate stn 10 and duplicate sub 20
            calls = [c[0] for c in mock_req.call_args_list]
            self.assertIn(("DELETE", "/shipment_tracking_numbers?id=eq.10"), calls)
            self.assertIn(("PATCH", "/shipment_tracking_numbers?id=eq.11"), calls)
            self.assertIn(("DELETE", "/shipment_subscribers?id=eq.20"), calls)
            self.assertIn(("PATCH", "/shipment_subscribers?id=eq.21"), calls)
            self.assertIn(("DELETE", "/shipments?id=eq.372"), calls)


if __name__ == "__main__":
    unittest.main()
