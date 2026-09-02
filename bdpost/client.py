import json
import httpx
import logging

logger = logging.getLogger(__name__)

TRACKING_URL = "https://ipsbd.bdpost.gov.bd/app_mail_tracking/search1.php"


class BangladeshPostError(Exception):
    pass


class TrackingNotFoundError(BangladeshPostError):
    pass


class BangladeshPostUnavailableError(BangladeshPostError):
    pass


async def track(tracking_number: str) -> str:
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://ipsbd.bdpost.gov.bd",
        "Referer": "https://ipsbd.bdpost.gov.bd/mail-tracking.html",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                TRACKING_URL,
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

    except httpx.TimeoutException:
        logger.warning("Bangladesh Post timeout for %s", tracking_number)
        raise BangladeshPostUnavailableError("Bangladesh Post tracking is temporarily unavailable")
    except httpx.HTTPStatusError as e:
        logger.error("Bangladesh Post HTTP error: %s", e.response.status_code)
        raise BangladeshPostUnavailableError("Bangladesh Post tracking is temporarily unavailable")
    except httpx.RequestError as e:
        logger.error("Bangladesh Post connection error: %s", e)
        raise BangladeshPostUnavailableError("Bangladesh Post tracking is temporarily unavailable")
