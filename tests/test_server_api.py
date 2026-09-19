import sys
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

if "aiohttp" not in sys.modules or not hasattr(sys.modules.get("aiohttp"), "__path__"):
    sys.modules["aiohttp"] = MagicMock()
    sys.modules["aiohttp.web"] = MagicMock()

if "telegram" not in sys.modules or not hasattr(sys.modules.get("telegram"), "__path__"):
    sys.modules["telegram"] = MagicMock()
    sys.modules["telegram.error"] = MagicMock()
    sys.modules["telegram.ext"] = MagicMock()
    sys.modules["telegram.constants"] = MagicMock()

from server import cors_middleware, handle_ping, handle_health, handle_api_root, handle_api_track, handle_api_postcode


class TestServerEndpoints(unittest.IsolatedAsyncioTestCase):

    async def test_handle_ping(self):
        req = MagicMock()
        with patch("server.web.json_response") as mock_json:
            mock_json.return_value = MagicMock(status=200)
            res = await handle_ping(req)
            self.assertEqual(res.status, 200)
            mock_json.assert_called_once()
            payload = mock_json.call_args[0][0]
            self.assertEqual(payload["status"], "pong")
            self.assertTrue(payload["healthy"])

    async def test_handle_health(self):
        req = MagicMock()
        with patch("server.web.Response") as mock_resp:
            mock_resp.return_value = MagicMock(status=200)
            res = await handle_health(req)
            self.assertEqual(res.status, 200)

    async def test_handle_api_root(self):
        req = MagicMock()
        with patch("server.web.json_response") as mock_json:
            mock_json.return_value = MagicMock(status=200)
            res = await handle_api_root(req)
            self.assertEqual(res.status, 200)
            payload = mock_json.call_args[0][0]
            self.assertIn("endpoints", payload)
            self.assertIn("track_parcel", payload["endpoints"])

    async def test_handle_api_track_invalid(self):
        req = MagicMock()
        req.match_info = {"tracking_number": "invalid"}
        req.query = {}
        with patch("server.web.json_response") as mock_json:
            mock_json.return_value = MagicMock(status=400)
            res = await handle_api_track(req)
            self.assertEqual(res.status, 400)
            payload = mock_json.call_args[0][0]
            self.assertFalse(payload["success"])
            self.assertIn("Invalid tracking number", payload["error"])

    async def test_handle_api_track_success(self):
        req = MagicMock()
        req.match_info = {"tracking_number": "BR006144481MG"}
        req.query = {}
        mock_db = MagicMock()
        req.app = {"db": mock_db}
        mock_db.get_shipment_by_tracking_number.return_value = {"id": 10}

        mock_cainiao_events = [{
            "event_date": "2026-09-17 10:00:00",
            "status": "Arrived at departure transport hub",
            "description": "Departed hub",
            "source": "cainiao",
            "origin_country": "China",
            "destination_country": "Bangladesh"
        }]

        import handlers.tracking
        with patch.object(handlers.tracking, "discover_and_fetch_chain", new=AsyncMock(return_value=(mock_cainiao_events, [], ["BR006144481MG"], None))), \
             patch("server.web.json_response") as mock_json:
            mock_json.return_value = MagicMock(status=200)
            res = await handle_api_track(req)
            self.assertEqual(res.status, 200)
            payload = mock_json.call_args[0][0]
            self.assertTrue(payload["success"])
            self.assertEqual(payload["tracking_number"], "BR006144481MG")
            self.assertEqual(payload["carrier"], "AliExpress / Cainiao")
            self.assertIn("RedX Courier", payload["delivery_channel"])
            self.assertEqual(payload["events_count"], 1)

    async def test_handle_api_postcode_search(self):
        req = MagicMock()
        req.query = {"query": "1216", "limit": "10"}
        with patch("server.web.json_response") as mock_json:
            mock_json.return_value = MagicMock(status=200)
            res = await handle_api_postcode(req)
            self.assertEqual(res.status, 200)
            payload = mock_json.call_args[0][0]
            self.assertTrue(payload["success"])
            self.assertGreater(payload["count"], 0)
            self.assertEqual(payload["post_offices"][0]["post_code"], "1216")


if __name__ == "__main__":
    unittest.main()
