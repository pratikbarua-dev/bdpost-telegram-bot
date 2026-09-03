import uuid
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
    Sends GET request to Cainiao global tracking endpoint reproducing exact browser headers
    and required session tokens to prevent empty responses / anti-bot caching.
    """
    cleaned_num = tracking_number.strip().upper()

    params = {
        "mailNos": cleaned_num,
        "lang": "en-US",
        "language": "en-US"
    }

    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.8",
        "priority": "u=1, i",
        "referer": f"https://global.cainiao.com/newDetail.htm?mailNoList={cleaned_num}&otherMailNoList=",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Brave";v="146"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Linux"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "sec-gpc": "1",
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
    }

    # Unique device / XSRF token simulation
    xsrf_token = str(uuid.uuid4())
    arms_uid = str(uuid.uuid4())

    cookies = {
        "XSRF-TOKEN": xsrf_token,
        "_lang": "en-US",
        "arms_uid": arms_uid,
        "x-hng": "lang=zh-CN&language=zh-CN"
    }

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(
                CAINIAO_URL,
                params=params,
                headers=headers,
                cookies=cookies
            )
            response.raise_for_status()
            data = response.json()
            return data

    except httpx.TimeoutException:
        logger.warning("Cainiao timeout for %s", cleaned_num)
        raise CainiaoUnavailableError("Cainiao tracking is temporarily unavailable")
    except httpx.HTTPStatusError as e:
        logger.error("Cainiao HTTP error: %s", e.response.status_code)
        raise CainiaoUnavailableError("Cainiao tracking is temporarily unavailable")
    except httpx.RequestError as e:
        logger.error("Cainiao connection error: %s", e)
        raise CainiaoUnavailableError("Cainiao tracking is temporarily unavailable")
    except Exception as e:
        logger.error("Unexpected Cainiao error for %s: %s", cleaned_num, e)
        raise CainiaoError(f"Cainiao error: {e}")

