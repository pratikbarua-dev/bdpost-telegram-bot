import asyncio
import ctypes
import datetime
import hashlib
import json
import logging
import random
import time
import urllib.parse
from typing import Dict, Any, Optional, List
import httpx

import config

logger = logging.getLogger(__name__)

TRACK17_BASE_URL = "https://t.17track.net"
TRACK17_RESTAPI_URL = "https://t.17track.net/track/restapi"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)


class Track17Error(Exception):
    pass


class Track17UnavailableError(Track17Error):
    pass


def _generate_yq_bid() -> str:
    """
    Generates a dynamic _yq_bid cookie value mimicking the 17track client bundle:
    "G-xxxxxxxxxxxxxxxx" with dynamic timestamp-based hex random numbers.
    Never hardcodes any static value.
    """
    now_ms = int(time.time() * 1000)
    chars = []
    template = "G-xxxxxxxxxxxxxxxx"
    for ch in template:
        if ch == "x":
            r = int((now_ms + 16 * random.random()) % 16)
            chars.append(hex(r)[2:].upper())
        elif ch == "y":
            r = int((now_ms + 16 * random.random()) % 16)
            chars.append(hex((r & 7) | 8)[2:].upper())
        else:
            chars.append(ch)
    return "".join(chars)


def _calc_x_hash(s: str) -> int:
    if not s:
        return 0
    a = 5381
    for ch in reversed(s):
        a = ctypes.c_int32((33 * a) ^ ord(ch)).value
    return ctypes.c_uint32(a).value


def _calc_o_hash(e_str: str, t_val: int) -> int:
    if not e_str:
        return 0
    o = ctypes.c_int32(0x4e67c6a7 ^ (t_val << 16)).value
    for ch in reversed(e_str):
        l_code = ord(ch)
        shift5 = ctypes.c_int32(o << 5).value
        shift2 = ctypes.c_int32(o >> 2).value
        sum_val = ctypes.c_int32(shift5 + l_code + shift2).value
        o = ctypes.c_int32(o ^ sum_val).value
    return abs(0x7fffffff & o)


def _pad_hex8(val: int) -> str:
    return hex(val)[2:].zfill(8)


def _generate_last_event_id(payload_dict: Dict[str, Any], yq_bid: str) -> str:
    """
    Dynamically generates the Last-Event-ID header and cookie layout as computed by 17track.
    Never hardcodes any token or timestamp.
    """
    u = ["", "", "", "4", "", ""]
    v_str = json.dumps(payload_dict, separators=(",", ":"))

    # Slot 5: hash of payload body
    a5 = _calc_o_hash(v_str, len(v_str))
    u[5] = _pad_hex8(a5)

    # Slot 4 and Slot 0: canvas / client hash calculation
    canvas_str = "24\r\nen-US\r\n-360\r\n1920x1080"
    i_val = _calc_x_hash(canvas_str)
    s_val = _calc_x_hash(str(payload_dict.get("captcha") or ""))

    a_str = yq_bid or str(i_val)
    a_str += f":false:{i_val}:0:0"
    now_hex = hex(int(time.time() * 1000))[2:]
    a_str = f"{a_str}/{now_hex}/11/true/-360/{i_val}/17/{s_val}"

    a4 = _calc_o_hash(a_str, 0)
    u[4] = _pad_hex8(a4)

    # Slot 0: reverse character hex string
    rev_a = "".join(reversed(a_str))
    hex_a = "".join(hex(ord(c))[2:] for c in rev_a)
    u[0] = hex_a

    return "".join(u)


class Track17Client:
    """
    Persistent 17TRACK HTTP client that dynamically bootstraps and maintains
    its own session, generating dynamic headers and cookies per request without hardcoding secrets.
    """
    _instance: Optional["Track17Client"] = None

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()
        self._bootstrapped = False
        self._guid: str = ""

    @classmethod
    def get_instance(cls) -> "Track17Client":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def _get_or_create_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=25.0,
                follow_redirects=True,
                headers={"user-agent": DEFAULT_USER_AGENT}
            )
            self._bootstrapped = False
        return self._client

    async def bootstrap_session(self) -> None:
        """
        Visits the 17track web page to dynamically acquire session cookies.
        Never hardcodes cookies or tokens.
        """
        client = await self._get_or_create_client()
        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": DEFAULT_USER_AGENT,
        }
        try:
            logger.info("Bootstrapping 17TRACK session via %s/en", TRACK17_BASE_URL)
            response = await client.get(f"{TRACK17_BASE_URL}/en", headers=headers)
            response.raise_for_status()
            self._bootstrapped = True
            cookie_names = list(client.cookies.keys())
            logger.info("17TRACK session bootstrapped. Acquired cookies: %s", cookie_names)
        except Exception as e:
            logger.warning("17TRACK session bootstrap notice: %s", e)

    async def refresh_session(self) -> None:
        """
        Closes current session and starts a fresh session.
        """
        async with self._lock:
            if self._client and not self._client.is_closed:
                await self._client.aclose()
            self._client = None
            self._bootstrapped = False
            self._guid = ""
            await self.bootstrap_session()

    async def track(self, tracking_number: str, allow_retry: bool = True) -> Dict[str, Any]:
        """
        Queries 17TRACK for a tracking number using dynamic headers, cookies, and payload.
        Returns the parsed JSON response.
        """
        cleaned_num = tracking_number.strip().upper()

        async with self._lock:
            client = await self._get_or_create_client()
            if not self._bootstrapped:
                await self.bootstrap_session()

        payload = {
            "data": [
                {
                    "num": cleaned_num,
                    "fc": 0,
                    "sc": 0
                }
            ],
            "guid": self._guid,
            "timeZoneOffset": -360
        }

        yq_bid = _generate_yq_bid()
        last_event_id = _generate_last_event_id(payload, yq_bid)

        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/json;charset=UTF-8",
            "origin": TRACK17_BASE_URL,
            "referer": f"{TRACK17_BASE_URL}/en",
            "user-agent": DEFAULT_USER_AGENT,
            "last-event-id": last_event_id,
            "cookie": f"country=BD; _yq_bid={yq_bid}; Last-Event-ID={last_event_id}"
        }
        if config.CF_PROXY_SECRET:
            headers["x-proxy-secret"] = config.CF_PROXY_SECRET

        try:
            logger.info("Querying 17TRACK for %s", cleaned_num)
            if config.CF_PROXY_URL:
                req_url = f"{config.CF_PROXY_URL.rstrip('/')}/?url={urllib.parse.quote(TRACK17_RESTAPI_URL, safe='')}"
                response = await client.post(
                    req_url,
                    json=payload,
                    headers=headers
                )
            else:
                response = await client.post(
                    TRACK17_RESTAPI_URL,
                    json=payload,
                    headers=headers
                )
            response.raise_for_status()
            data = response.json()

            if not isinstance(data, dict):
                raise Track17Error("Invalid JSON response from 17TRACK")

            # Update guid if returned
            if data.get("guid"):
                self._guid = data["guid"]

            meta = data.get("meta") or {}
            meta_code = meta.get("code")

            # Check for verification / temporary challenge
            if meta_code in [-14, -13, -11, -8]:
                logger.info("17TRACK returned verification code %s for %s", meta_code, cleaned_num)
                # If retry is allowed, try refreshing session once
                if allow_retry:
                    await self.refresh_session()
                    return await self.track(cleaned_num, allow_retry=False)
                raise Track17UnavailableError(f"17TRACK requires verification (code {meta_code})")

            return data

        except httpx.TimeoutException:
            logger.warning("17TRACK timeout for %s", cleaned_num)
            raise Track17UnavailableError("17TRACK tracking request timed out")
        except httpx.HTTPStatusError as e:
            if allow_retry and e.response.status_code in [401, 403, 429]:
                logger.warning("17TRACK returned HTTP %d. Refreshing session...", e.response.status_code)
                await self.refresh_session()
                return await self.track(cleaned_num, allow_retry=False)
            logger.warning("17TRACK HTTP error %s for %s", e.response.status_code, cleaned_num)
            raise Track17UnavailableError(f"17TRACK returned HTTP {e.response.status_code}")
        except httpx.RequestError as e:
            logger.warning("17TRACK request connection error for %s: %s", cleaned_num, e)
            raise Track17UnavailableError(f"17TRACK connection error: {e}")
        except (Track17Error, Track17UnavailableError):
            raise
        except Exception as e:
            logger.error("Unexpected 17TRACK error for %s: %s", cleaned_num, e)
            raise Track17Error(f"17TRACK error: {e}")

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


async def track(tracking_number: str) -> Dict[str, Any]:
    """
    Module-level convenience wrapper.
    """
    return await Track17Client.get_instance().track(tracking_number)
