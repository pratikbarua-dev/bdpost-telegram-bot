import httpx
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

CAINIAO_URL = "https://global.cainiao.com/global/detail.json"


class CainiaoError(Exception):
    pass


class CainiaoUnavailableError(CainiaoError):
    pass


async def track(tracking_number: str) -> Dict[str, Any]:
    """
    Sends GET request to Cainiao global tracking endpoint and returns parsed JSON.
    """
    params = {
        "mailNos": tracking_number,
        "lang": "en-US",
        "language": "en-US"
    }
    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://global.cainiao.com/"
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                CAINIAO_URL,
                params=params,
                headers=headers
            )
            response.raise_for_status()
            data = response.json()
            return data

    except httpx.TimeoutException:
        logger.warning("Cainiao timeout for %s", tracking_number)
        raise CainiaoUnavailableError("Cainiao tracking is temporarily unavailable")
    except httpx.HTTPStatusError as e:
        logger.error("Cainiao HTTP error: %s", e.response.status_code)
        raise CainiaoUnavailableError("Cainiao tracking is temporarily unavailable")
    except httpx.RequestError as e:
        logger.error("Cainiao connection error: %s", e)
        raise CainiaoUnavailableError("Cainiao tracking is temporarily unavailable")
    except Exception as e:
        logger.error("Unexpected Cainiao error for %s: %s", tracking_number, e)
        raise CainiaoError(f"Cainiao error: {e}")
