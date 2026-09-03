import re
import hashlib
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from bdpost.validator import validate_and_normalize_tracking_number

logger = logging.getLogger(__name__)


def clean_tracking_number_field(val: Optional[str]) -> Optional[str]:
    """
    Strips labels and normalizes tracking number tokens.
    """
    if not val or not isinstance(val, str):
        return None

    cleaned = re.sub(
        r"^(Latest Tracking Number|package tracking number|Tracking Number|New tracking number|Local tracking number)[\s:\t]+",
        "",
        val,
        flags=re.IGNORECASE
    ).strip()

    tokens = re.findall(r"[A-Za-z0-9\-]{4,35}", cleaned)
    for token in tokens:
        normalized = validate_and_normalize_tracking_number(token)
        if normalized:
            return normalized

    return None


def format_iso_timestamp(iso_str: Optional[str]) -> str:
    """
    Converts ISO 8601 timestamp (e.g. '2026-09-02T16:13:25+08:00' or '2026-09-02T08:13:25Z')
    into a clean standard date string 'YYYY-MM-DD HH:MM:SS' while retaining clarity.
    """
    if not iso_str or not isinstance(iso_str, str):
        return ""

    cleaned = iso_str.strip()
    try:
        dt = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        # Fallback to regex cleanup if datetime parsing fails
        cleaned = cleaned.replace("T", " ")
        if "+" in cleaned:
            cleaned = cleaned.split("+")[0]
        elif "-" in cleaned and len(cleaned) > 19:
            cleaned = cleaned[:19]
        return cleaned.rstrip("Z").strip()


def generate_17track_event_hash(tracking_number: str, event: Dict[str, Any]) -> str:
    """
    Generates a deterministic SHA-256 hash for a 17TRACK event.
    """
    data = (
        str(tracking_number) +
        str(event.get("event_date", "")) +
        str(event.get("location", "")) +
        str(event.get("status", "")) +
        str(event.get("description", "")) +
        str(event.get("action_code", "")) +
        "17track"
    )
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def extract_linked_tracking_numbers(data: Dict[str, Any], query_number: str) -> List[Dict[str, str]]:
    """
    Extracts any linked or local tracking numbers reported by 17TRACK,
    such as misc_info.local_number or package numbers in description.
    """
    discovered: List[Dict[str, str]] = []
    seen: set[str] = {query_number.strip().upper()}

    if not data or not isinstance(data, dict):
        return discovered

    shipments = data.get("shipments") or []
    if not isinstance(shipments, list) or not shipments:
        return discovered

    shipment = shipments[0]

    # 1. Check misc_info.local_number & misc_info.local_provider
    misc_info = shipment.get("misc_info") or {}
    if isinstance(misc_info, dict):
        local_num = misc_info.get("local_number")
        cleaned_local = clean_tracking_number_field(local_num)
        if cleaned_local and cleaned_local not in seen:
            seen.add(cleaned_local)
            local_provider = misc_info.get("local_provider") or "local"
            discovered.append({
                "tracking_number": cleaned_local,
                "source": "bdpost" if str(local_provider).lower() in ["bdpost", "bangladesh post", "post"] or cleaned_local.endswith("BD") or cleaned_local.endswith("MV") else "17track",
                "type": "local",
                "discovered_from": query_number
            })

    # 2. Check events for postal tracking pattern matches
    tracking_obj = shipment.get("tracking") or {}
    providers = tracking_obj.get("providers") or []
    for prov in providers:
        events = prov.get("events") or []
        for evt in events:
            desc = str(evt.get("description") or "")
            matches = re.findall(r"\b([A-Z]{2}\d{9}[A-Z]{2})\b", desc)
            for m in matches:
                cleaned_m = validate_and_normalize_tracking_number(m)
                if cleaned_m and cleaned_m not in seen:
                    seen.add(cleaned_m)
                    discovered.append({
                        "tracking_number": cleaned_m,
                        "source": "bdpost" if cleaned_m.endswith("BD") or cleaned_m.endswith("MV") else "17track",
                        "type": "local",
                        "discovered_from": query_number
                    })

    return discovered


def parse_tracking_response(data: Dict[str, Any], query_number: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Parses 17TRACK JSON response into normalized event dictionaries:
    [
        {
            "event_date": "2026-09-02 16:13:25",
            "location": "...",
            "status": "Departed from departure country/region",
            "description": "Departed from departure country/region, Carrier note: Left from departure country/region",
            "origin_country": "",
            "destination_country": "",
            "source": "17track",
            "carrier_name": "AliExpress",
            "action_code": "InTransit_Departure",
            "stage": "Departure",
            "sub_status": "InTransit_Departure",
            "time_iso": "2026-09-02T16:13:25+08:00",
            "time_utc": "2026-09-02T08:13:25Z",
            "event_hash": "..."
        },
        ...
    ]
    Returned in chronological order (oldest -> newest).
    """
    parsed_events: List[Dict[str, Any]] = []

    if not data or not isinstance(data, dict):
        return parsed_events

    shipments = data.get("shipments") or []
    if not isinstance(shipments, list) or not shipments:
        return parsed_events

    shipment = shipments[0]
    tracking_number = shipment.get("number") or (query_number or "")

    tracking_obj = shipment.get("tracking") or {}
    providers = tracking_obj.get("providers") or []

    for prov in providers:
        provider_info = prov.get("provider") or {}
        carrier_name = provider_info.get("name") or "17track"
        carrier_key = provider_info.get("key")
        raw_events = prov.get("events") or []

        for item in raw_events:
            time_iso = item.get("time_iso") or ""
            time_utc = item.get("time_utc") or ""
            event_date = format_iso_timestamp(time_iso or time_utc)
            description = item.get("description") or ""
            location = item.get("location") or ""
            stage = item.get("stage") or ""
            sub_status = item.get("sub_status") or ""

            # Extract a concise status line if description has carrier notes
            status = description
            if "," in description:
                status = description.split(",")[0].strip()
            elif "Carrier note:" in description:
                status = description.split("Carrier note:")[0].strip()

            if not status and stage:
                status = stage

            event_dict = {
                "event_date": event_date,
                "location": location,
                "status": status,
                "description": description,
                "origin_country": "",
                "destination_country": "",
                "source": "17track",
                "carrier_name": carrier_name,
                "carrier_key": carrier_key,
                "action_code": sub_status or stage,
                "stage": stage,
                "sub_status": sub_status,
                "time_iso": time_iso,
                "time_utc": time_utc,
                "address": item.get("address") or {}
            }
            event_dict["event_hash"] = generate_17track_event_hash(tracking_number, event_dict)
            parsed_events.append(event_dict)

    # If no provider events were parsed, fallback to latest_event if present
    if not parsed_events:
        latest = shipment.get("latest_event")
        if latest and isinstance(latest, dict):
            time_iso = latest.get("time_iso") or ""
            event_date = format_iso_timestamp(time_iso)
            description = latest.get("description") or ""
            status = description.split(",")[0].strip() if "," in description else description
            latest_status_obj = shipment.get("latest_status") or {}
            sub_status = latest_status_obj.get("sub_status") or latest_status_obj.get("status") or ""

            event_dict = {
                "event_date": event_date,
                "location": latest.get("location") or "",
                "status": status or sub_status or "In Transit",
                "description": description,
                "origin_country": "",
                "destination_country": "",
                "source": "17track",
                "carrier_name": "17track",
                "action_code": sub_status,
                "stage": latest.get("stage") or "",
                "sub_status": sub_status,
                "time_iso": time_iso,
                "time_utc": latest.get("time_utc") or "",
                "address": latest.get("address") or {}
            }
            event_dict["event_hash"] = generate_17track_event_hash(tracking_number, event_dict)
            parsed_events.append(event_dict)

    # Sort events chronologically (oldest -> newest)
    parsed_events.sort(key=lambda x: x.get("time_iso") or x.get("event_date") or "")

    return parsed_events


def get_17track_summary(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extracts summary fields from 17TRACK response.
    """
    if not data or not isinstance(data, dict):
        return None

    shipments = data.get("shipments") or []
    if not shipments:
        return None

    shipment = shipments[0]
    latest_status = shipment.get("latest_status") or {}
    tracking_obj = shipment.get("tracking") or {}
    providers = tracking_obj.get("providers") or []
    carrier_name = "17track"
    if providers:
        carrier_name = (providers[0].get("provider") or {}).get("name") or "17track"

    return {
        "tracking_number": shipment.get("number", ""),
        "carrier": shipment.get("carrier"),
        "carrier_name": carrier_name,
        "status": latest_status.get("status", ""),
        "sub_status": latest_status.get("sub_status", ""),
        "time_metrics": shipment.get("time_metrics", {}),
        "milestone": shipment.get("milestone", {})
    }
