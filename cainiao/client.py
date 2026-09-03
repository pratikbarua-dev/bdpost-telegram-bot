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


import asyncio
import httpx
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

CAINIAO_BASE_URL = "https://global.cainiao.com"
CAINIAO_DETAIL_JSON = "https://global.cainiao.com/global/detail.json"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)


class CainiaoError(Exception):
    pass


class CainiaoUnavailableError(CainiaoError):
    pass


class CainiaoClient:
    """
    Persistent Cainiao HTTP client that queries the Cainiao Global tracking endpoint
    using standard browser headers with automatic retry on temporary failures.
    """
    _instance: Optional["CainiaoClient"] = None

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()

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
            "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Linux"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
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
        return self._client

    async def refresh_session(self) -> None:
        """
        Closes current session and starts a fresh client instance.
        """
        async with self._lock:
            if self._client and not self._client.is_closed:
                await self._client.aclose()
            self._client = None

    async def track(self, tracking_number: str, allow_retry: bool = True) -> Dict[str, Any]:
        """
        Sends GET request to Cainiao global tracking endpoint.
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

        try:
            response = await client.get(
                CAINIAO_DETAIL_JSON,
                params=params,
                headers=headers
            )
            response.raise_for_status()
            data = response.json()

            if not isinstance(data, dict):
                raise CainiaoError("Invalid JSON response received from Cainiao")

            modules = data.get("module")
            is_empty = (
                not data.get("success") or
                not modules or
                (isinstance(modules, list) and len(modules) > 0 and not modules[0].get("detailList") and not modules[0].get("latestTrace") and modules[0].get("status") == "SELLER_PREPARING")
            )

            if is_empty and allow_retry:
                logger.info("Cainiao response for %s was empty/stale. Refreshing session and retrying once...", cleaned_num)
                await self.refresh_session()
                return await self.track(cleaned_num, allow_retry=False)

            return data

        except httpx.TimeoutException:
            logger.warning("Cainiao timeout for %s", cleaned_num)
            raise CainiaoUnavailableError("Cainiao tracking is temporarily unavailable")
        except httpx.HTTPStatusError as e:
            if allow_retry and e.response.status_code in [401, 403, 429]:
                logger.warning("Cainiao returned status %d. Refreshing session...", e.response.status_code)
                await self.refresh_session()
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
