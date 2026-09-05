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
    Queries Bangladesh Post tracking.
    Attempts search1.php (International / General) first, and if no table is found,
    checks search2.php (Domestic / Bangladesh-to-Bangladesh).
    """
    from bdpost.parser import parse_tracking_response

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # First attempt: search1.php
            try:
                res1 = await _fetch_endpoint(client, SEARCH1_URL, tracking_number)
                events1 = parse_tracking_response(res1)
                if events1:
                    return res1
            except Exception as e:
                logger.debug("search1.php attempt failed or returned no events for %s: %s", tracking_number, e)
                res1 = ""

            # Second attempt: search2.php (Domestic)
            try:
                res2 = await _fetch_endpoint(client, SEARCH2_URL, tracking_number)
                events2 = parse_tracking_response(res2)
                if events2:
                    return res2
            except Exception as e:
                logger.debug("search2.php attempt failed for %s: %s", tracking_number, e)
                res2 = ""

            # If neither returned events, return whichever response was received (or res1/res2)
            return res1 or res2 or ""

    except httpx.TimeoutException:
        logger.warning("Bangladesh Post timeout for %s", tracking_number)
        raise BangladeshPostUnavailableError("Bangladesh Post tracking is temporarily unavailable")
    except httpx.HTTPStatusError as e:
        logger.error("Bangladesh Post HTTP error: %s", e.response.status_code)
        raise BangladeshPostUnavailableError("Bangladesh Post tracking is temporarily unavailable")
    except httpx.RequestError as e:
        logger.error("Bangladesh Post connection error: %s", e)
        raise BangladeshPostUnavailableError("Bangladesh Post tracking is temporarily unavailable")
