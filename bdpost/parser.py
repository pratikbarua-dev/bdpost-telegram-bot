import json
import hashlib
from bs4 import BeautifulSoup
import logging

logger = logging.getLogger(__name__)


def generate_event_hash(event: dict) -> str:
    data = (
        event.get("event_date", "") +
        event.get("origin_country", "") +
        event.get("destination_country", "") +
        event.get("location", "") +
        event.get("status", "")
    )
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def parse_tracking_response(html: str) -> list[dict]:
    events = []

    if not html or not html.strip():
        return events

    # Check if html is a JSON-encoded string
    stripped = html.strip()
    if stripped.startswith('"') and stripped.endswith('"'):
        try:
            decoded = json.loads(stripped)
            if isinstance(decoded, str):
                html = decoded
        except json.JSONDecodeError:
            pass

    try:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")

        if not table:
            logger.debug("No table found in response")
            return events

        rows = table.find_all("tr")

        if len(rows) <= 1:
            return events

        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) >= 5:
                event = {
                    "event_date": cells[0].get_text(strip=True),
                    "origin_country": cells[1].get_text(strip=True),
                    "destination_country": cells[2].get_text(strip=True),
                    "location": cells[3].get_text(strip=True),
                    "status": cells[4].get_text(strip=True),
                    "source": "bdpost"
                }
                event["event_hash"] = generate_event_hash(event)
                events.append(event)
            elif len(cells) == 4:
                # Some domestic tracking tables have 4 columns: Date, Location, Status, Remarks/Origin
                event = {
                    "event_date": cells[0].get_text(strip=True),
                    "origin_country": "Bangladesh",
                    "destination_country": "Bangladesh",
                    "location": cells[1].get_text(strip=True),
                    "status": cells[2].get_text(strip=True),
                    "source": "bdpost"
                }
                event["event_hash"] = generate_event_hash(event)
                events.append(event)

    except Exception as e:
        logger.error("Parser failure: %s", e)
        raise

    return events


def get_latest_event(events: list[dict]) -> dict | None:
    """
    Returns the latest event. Bangladesh Post lists events chronologically
    with the newest event in the last row of the table.
    """
    if not events:
        return None
    return events[-1]


def is_delivered(status: str) -> bool:
    normalized = status.lower().strip()
    return "delivered" in normalized


def is_out_for_delivery(status: str) -> bool:
    normalized = status.lower().strip()
    return "out for delivery" in normalized


def is_arrived_at_post_office(status: str) -> bool:
    normalized = status.lower().strip()
    return "arrived at post office" in normalized


def is_dispatched(status: str) -> bool:
    normalized = status.lower().strip()
    return "dispatched" in normalized


def is_bdpost_handover_event(event: dict) -> bool:
    """
    Checks if a Bangladesh Post event confirms that the parcel has entered
    the local postal / domestic delivery system.
    Examples of strong handover events:
    - 'Arrived at post office'
    - 'Arrived at inward office'
    - 'Received at destination country'
    - 'Arrival at destination country'
    - 'Received by local carrier'
    - 'Dispatched from post office'
    - 'Out for delivery'
    - 'Delivered'
    - 'Incomming' at airport/sorting office with destination Bangladesh
    """
    if not event:
        return False

    status = (event.get("status") or "").lower().strip()
    location = (event.get("location") or "").lower().strip()

    strong_statuses = [
        "arrived at post office",
        "arrived at inward office",
        "received at destination country",
        "arrival at destination country",
        "received by local carrier",
        "dispatched from post office",
        "out for delivery",
        "delivered",
        "item received",
    ]

    for s in strong_statuses:
        if s in status:
            return True

    # If status is incomming/received and at Dhaka Airport / Sorting office or destination is Bangladesh
    if "incomming" in status or "incoming" in status:
        if "dhaka" in location or "sorting office" in location or "post office" in location:
            return True

    return False
