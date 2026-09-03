import asyncio
import httpx
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

CAINIAO_BASE_URL = "https://global.cainiao.com"
CAINIAO_DETAIL_JSON = "https://global.cainiao.com/global/detail.json"
DEFAULT_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"


class CainiaoError(Exception):
    pass


class CainiaoUnavailableError(CainiaoError):
    pass


class CainiaoClient:
    """
    Persistent Cainiao HTTP client that dynamically bootstraps and maintains
    its own browser-like session and cookies without hardcoding any session values.
    """
    _instance: Optional["CainiaoClient"] = None

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()
        self._bootstrapped = False

    @classmethod
    def get_instance(cls) -> "CainiaoClient":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _get_browser_headers(self, referer: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "priority": "u=1, i",
            "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Brave";v="146"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Linux"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "sec-gpc": "1",
            "user-agent": DEFAULT_USER_AGENT,
        }
        if referer:
            headers["referer"] = referer
        return headers

    async def _get_or_create_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={"user-agent": DEFAULT_USER_AGENT}
            )
            self._bootstrapped = False
        return self._client

    async def bootstrap_session(self, tracking_number: Optional[str] = None) -> None:
        """
        Visits the Cainiao web page to dynamically obtain and store session cookies.
        Never hardcodes cookies.
        """
        client = await self._get_or_create_client()

        url = (
            f"{CAINIAO_BASE_URL}/newDetail.htm?mailNoList={tracking_number}&otherMailNoList="
            if tracking_number
            else f"{CAINIAO_BASE_URL}/"
        )

        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": DEFAULT_USER_AGENT,
        }

        try:
            logger.info("Bootstrapping Cainiao session via %s", url)
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            self._bootstrapped = True
            # Log only cookie names (never log secret cookie values)
            cookie_names = list(client.cookies.keys())
            logger.info("Cainiao session bootstrapped. Acquired cookies: %s", cookie_names)
        except Exception as e:
            logger.warning("Cainiao session bootstrap notice: %s", e)

    async def refresh_session(self, tracking_number: Optional[str] = None) -> None:
        """
        Closes current session and starts a fresh bootstrapped session.
        """
        async with self._lock:
            if self._client and not self._client.is_closed:
                await self._client.aclose()
            self._client = None
            self._bootstrapped = False
            await self.bootstrap_session(tracking_number)

    async def track(self, tracking_number: str, allow_retry: bool = True) -> Dict[str, Any]:
        """
        Sends GET request to Cainiao global tracking endpoint using the persistent session.
        If the session is stale or returns an incomplete response, refreshes session and retries once.
        """
        cleaned_num = tracking_number.strip().upper()
        referer = f"{CAINIAO_BASE_URL}/newDetail.htm?mailNoList={cleaned_num}&otherMailNoList="
        params = {
            "mailNos": cleaned_num,
            "lang": "en-US",
            "language": "en-US"
        }
        headers = self._get_browser_headers(referer=referer)

        async with self._lock:
            client = await self._get_or_create_client()
            if not self._bootstrapped:
                await self.bootstrap_session(cleaned_num)

        try:
            response = await client.get(
                CAINIAO_DETAIL_JSON,
                params=params,
                headers=headers
            )
            response.raise_for_status()
            data = response.json()

            # Check if response is valid JSON
            if not isinstance(data, dict):
                raise CainiaoError("Invalid JSON response received from Cainiao")

            # Check if session expired / empty response that needs a refresh retry
            modules = data.get("module")
            is_empty_or_stale = (
                not data.get("success") or
                not modules or
                (isinstance(modules, list) and len(modules) > 0 and not modules[0].get("detailList") and not modules[0].get("latestTrace") and modules[0].get("status") == "SELLER_PREPARING")
            )

            # If the response returned empty/unauthenticated and retry is allowed, refresh session once
            if is_empty_or_stale and allow_retry:
                logger.info("Cainiao response for %s was empty/stale. Refreshing session and retrying once...", cleaned_num)
                await self.refresh_session(cleaned_num)
                return await self.track(cleaned_num, allow_retry=False)

            return data

        except httpx.TimeoutException:
            logger.warning("Cainiao timeout for %s", cleaned_num)
            raise CainiaoUnavailableError("Cainiao tracking is temporarily unavailable")
        except httpx.HTTPStatusError as e:
            if allow_retry and e.response.status_code in [401, 403, 429]:
                logger.warning("Cainiao returned status %d. Refreshing session...", e.response.status_code)
                await self.refresh_session(cleaned_num)
                return await self.track(cleaned_num, allow_retry=False)
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
