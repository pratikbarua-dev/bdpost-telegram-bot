import json
import urllib.parse
import httpx
import logging

import config

logger = logging.getLogger(__name__)

SEARCH1_URL = "https://ipsbd.bdpost.gov.bd/app_mail_tracking/search1.php"
SEARCH2_URL = "https://ipsbd.bdpost.gov.bd/app_mail_tracking/search2.php"


class BangladeshPostError(Exception):
    pass


class TrackingNotFoundError(BangladeshPostError):
    pass


class BangladeshPostUnavailableError(BangladeshPostError):
    pass


async def _fetch_endpoint(client: httpx.AsyncClient, url: str, tracking_number: str) -> str:
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://ipsbd.bdpost.gov.bd",
        "Referer": "https://ipsbd.bdpost.gov.bd/mail-tracking.html",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    }
    if config.CF_PROXY_SECRET:
        headers["x-proxy-secret"] = config.CF_PROXY_SECRET

    if config.CF_PROXY_URL:
        req_url = f"{config.CF_PROXY_URL.rstrip('/')}/?url={urllib.parse.quote(url, safe='')}"
        response = await client.post(
            req_url,
            data={"item_id": tracking_number},
            headers=headers
        )
    else:
        response = await client.post(
            url,
            data={"item_id": tracking_number},
            headers=headers
        )

    response.raise_for_status()
    text = response.text

    # If response is a JSON-encoded string (e.g. "\"<table...\""), unwrap it
    stripped = text.strip()
    if (stripped.startswith('"') and stripped.endswith('"')) or stripped.startswith('{') or stripped.startswith('['):
        try:
            decoded = json.loads(stripped)
            if isinstance(decoded, str):
                return decoded
        except json.JSONDecodeError:
            pass

    return text


async def track(tracking_number: str) -> str:
    """
    Queries Bangladesh Post tracking via search1.php (Primary tracking endpoint).
    """
    try:
        async with httpx.AsyncClient(timeout=18.0) as client:
            return await _fetch_endpoint(client, SEARCH1_URL, tracking_number)
    except httpx.TimeoutException:
        logger.warning("Bangladesh Post timeout for %s", tracking_number)
        raise BangladeshPostUnavailableError("Bangladesh Post tracking is temporarily unavailable")
    except httpx.HTTPStatusError as e:
        logger.error("Bangladesh Post HTTP error: %s", e.response.status_code)
        raise BangladeshPostUnavailableError("Bangladesh Post tracking is temporarily unavailable")
    except httpx.RequestError as e:
        logger.error("Bangladesh Post connection error: %s", e)
        raise BangladeshPostUnavailableError("Bangladesh Post tracking is temporarily unavailable")
