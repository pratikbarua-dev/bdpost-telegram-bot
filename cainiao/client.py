import asyncio
import time
import urllib.parse
import httpx
import logging
from typing import Dict, Any, Optional

import config

logger = logging.getLogger(__name__)

CAINIAO_BASE_URL = "https://global.cainiao.com"
CAINIAO_DETAIL_JSON = "https://global.cainiao.com/global/detail.json"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class CainiaoError(Exception):
    pass


class CainiaoUnavailableError(CainiaoError):
    pass


class CainiaoRateLimitError(CainiaoUnavailableError):
    pass


class CainiaoClient:
    """
    Persistent Cainiao HTTP client that queries the Cainiao Global tracking endpoint
    using modern browser headers, rate limiting, and circuit breaker protection,
    optionally routing through a Cloudflare Worker proxy.
    """
    _instance: Optional["CainiaoClient"] = None

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()
        self._last_request_time: float = 0.0
        self._cooldown_until: float = 0.0
        self._min_delay: float = 1.5  # seconds between consecutive requests

    @classmethod
    def get_instance(cls) -> "CainiaoClient":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _get_browser_headers(self, referer: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "cache-control": "no-cache",
            "pragma": "no-cache",
            "priority": "u=1, i",
            "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": DEFAULT_USER_AGENT,
        }
        if referer:
            headers["referer"] = referer
        if config.CF_PROXY_SECRET:
            headers["x-proxy-secret"] = config.CF_PROXY_SECRET
        return headers

    async def _get_or_create_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=25.0,
                follow_redirects=True,
                headers={"user-agent": DEFAULT_USER_AGENT}
            )
        return self._client

    async def refresh_session(self) -> None:
        """
        Closes current session and starts a fresh client instance.
        """
        async with self._lock:
            if self._client and not self._client.is_closed:
                await self._client.aclose()
            self._client = None

    def trigger_cooldown(self, seconds: int = 180) -> None:
        """
        Activates circuit breaker for Cainiao queries.
        """
        self._cooldown_until = time.time() + seconds
        logger.warning("Cainiao circuit breaker triggered: cooling down for %d seconds", seconds)

    def is_cooling_down(self) -> bool:
        return time.time() < self._cooldown_until

    async def track(self, tracking_number: str, allow_retry: bool = True) -> Dict[str, Any]:
        """
        Sends GET request to Cainiao global tracking endpoint (optionally via CF Worker proxy).
        """
        if self.is_cooling_down():
            remaining = int(self._cooldown_until - time.time())
            raise CainiaoRateLimitError(f"Cainiao circuit breaker active (cooling down for {remaining}s)")

        cleaned_num = tracking_number.strip().upper()
        referer = f"{CAINIAO_BASE_URL}/newDetail.htm?mailNoList={cleaned_num}&otherMailNoList="
        params = {
            "mailNos": cleaned_num,
            "lang": "en-US",
            "language": "en-US"
        }
        headers = self._get_browser_headers(referer=referer)

        async with self._lock:
            # Enforce rate-limit interval
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < self._min_delay:
                await asyncio.sleep(self._min_delay - elapsed)
            self._last_request_time = time.time()

            client = await self._get_or_create_client()

        try:
            if config.CF_PROXY_URL:
                target_url = f"{CAINIAO_DETAIL_JSON}?{urllib.parse.urlencode(params)}"
                req_url = f"{config.CF_PROXY_URL.rstrip('/')}/?url={urllib.parse.quote(target_url, safe='')}"
                response = await client.get(req_url, headers=headers)
            else:
                response = await client.get(
                    CAINIAO_DETAIL_JSON,
                    params=params,
                    headers=headers
                )

            response.raise_for_status()

            try:
                data = response.json()
            except Exception:
                logger.warning("Cainiao returned non-JSON / captcha challenge for %s", cleaned_num)
                self.trigger_cooldown(180)
                raise CainiaoRateLimitError("Cainiao returned non-JSON challenge")

            if not isinstance(data, dict):
                raise CainiaoError("Invalid JSON response received from Cainiao")

            # Check for Alibaba WAF rate limit / challenge in JSON body
            ret = data.get("ret") or []
            is_waf_limited = any(
                "FAIL_SYS_USER_VALIDATE" in str(r) or "RGV587_ERROR" in str(r) for r in ret
            ) or (isinstance(data.get("data"), dict) and "punish" in str(data.get("data", {}).get("url", "")))

            if is_waf_limited:
                logger.warning("Cainiao WAF rate limit triggered for %s", cleaned_num)
                self.trigger_cooldown(180)
                raise CainiaoRateLimitError("Cainiao rate limited (WAF)")

            modules = data.get("module")
            is_empty = (
                data.get("success") is True and
                (
                    not modules or
                    (isinstance(modules, list) and len(modules) > 0 and not modules[0].get("detailList") and not modules[0].get("latestTrace") and modules[0].get("status") == "SELLER_PREPARING")
                )
            )

            if is_empty and allow_retry:
                logger.debug("Cainiao response for %s was empty. Retrying once...", cleaned_num)
                await self.refresh_session()
                return await self.track(cleaned_num, allow_retry=False)

            return data

        except httpx.TimeoutException:
            logger.warning("Cainiao timeout for %s", cleaned_num)
            raise CainiaoUnavailableError("Cainiao tracking is temporarily unavailable")
        except httpx.HTTPStatusError as e:
            if e.response.status_code in [401, 403, 429]:
                logger.warning("Cainiao returned status %d. Entering cooldown...", e.response.status_code)
                self.trigger_cooldown(180)
                raise CainiaoRateLimitError(f"Cainiao returned HTTP {e.response.status_code}")
            logger.error("Cainiao HTTP error: %s", e.response.status_code)
            raise CainiaoUnavailableError("Cainiao tracking is temporarily unavailable")
        except httpx.RequestError as e:
            logger.error("Cainiao connection error: %s", e)
            raise CainiaoUnavailableError("Cainiao tracking is temporarily unavailable")
        except CainiaoError:
            raise
        except Exception as e:
            logger.error("Unexpected Cainiao error for %s: %s", cleaned_num, e)
            raise CainiaoError(f"Cainiao error: {e}")

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# Module-level convenience function preserving backward compatibility
async def track(tracking_number: str) -> Dict[str, Any]:
    return await CainiaoClient.get_instance().track(tracking_number)

