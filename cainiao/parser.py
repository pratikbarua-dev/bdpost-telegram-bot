import re
import hashlib
import logging
from typing import Dict, Any, List, Optional
from bdpost.validator import validate_and_normalize_tracking_number

logger = logging.getLogger(__name__)


def clean_tracking_number_field(val: Optional[str]) -> Optional[str]:
    """
    Strips labels like 'Latest Tracking Number:\t', 'package tracking number:\t',
    whitespace, etc., and validates as a proper postal/logistics tracking number.
    """
    if not val or not isinstance(val, str):
        return None

    # Strip known label prefixes
    cleaned = re.sub(r"^(Latest Tracking Number|package tracking number|Tracking Number|New tracking number|Local tracking number)[\s:\t]+", "", val, flags=re.IGNORECASE)
    cleaned = cleaned.strip()

    # Find candidate alphanumeric tracking token
    tokens = re.findall(r"[A-Za-z0-9\-]{4,35}", cleaned)
    for token in tokens:
        normalized = validate_and_normalize_tracking_number(token)
        if normalized:
            return normalized

    return None


def extract_linked_tracking_numbers(data: Dict[str, Any], query_number: str) -> List[Dict[str, str]]:
    """
    Extracts secondary/linked tracking numbers discovered from Cainiao response.
    Returns a list of dicts:
    [
        {"tracking_number": "CNG0083981455575", "source": "cainiao", "type": "latest", "discovered_from": query_number},
        ...
    ]
    """
    discovered: List[Dict[str, str]] = []
    seen: set[str] = {query_number.strip().upper()}

    if not data or not data.get("success"):
        return discovered

    modules = data.get("module")
    if not isinstance(modules, list) or not modules:
        return discovered

    item = modules[0]

    # Candidate fields to inspect
    field_mappings = [
        ("copyRealMailNo", "latest"),
        ("copyVirtualMailNo", "package"),
        ("realMailNo", "latest"),
        ("virtualMailNo", "package")
    ]

    for field_name, num_type in field_mappings:
        val = item.get(field_name)
        cleaned_num = clean_tracking_number_field(val)
        if cleaned_num and cleaned_num not in seen:
            seen.add(cleaned_num)
            discovered.append({
                "tracking_number": cleaned_num,
                "source": "cainiao" if cleaned_num.startswith("CNG") or cleaned_num.startswith("AP") else "unknown",
                "type": num_type,
                "discovered_from": query_number
            })

    # Also inspect traces/carrier notes for possible local tracking numbers (e.g. UG... / LP...)
    detail_list = item.get("detailList") or []
    for detail in detail_list:
        desc = detail.get("desc", "") + " " + detail.get("standerdDesc", "")
        # Look for postal tracking patterns like UG123456789MV or BD tracking numbers
        matches = re.findall(r"\b([A-Z]{2}\d{9}[A-Z]{2})\b", desc)
        for m in matches:
            cleaned_m = validate_and_normalize_tracking_number(m)
            if cleaned_m and cleaned_m not in seen:
                seen.add(cleaned_m)
                discovered.append({
                    "tracking_number": cleaned_m,
                    "source": "bdpost" if cleaned_m.endswith("BD") or cleaned_m.endswith("MV") else "cainiao",
                    "type": "local",
                    "discovered_from": query_number
                })

    return discovered


def generate_cainiao_event_hash(tracking_number: str, event: Dict[str, Any]) -> str:
    """
    Generates a deterministic SHA-256 hash for a Cainiao event.
    """
    data = (
        str(tracking_number) +
        str(event.get("event_date", "")) +
        str(event.get("location", "")) +
        str(event.get("status", "")) +
        str(event.get("description", "")) +
        str(event.get("action_code", "")) +
        "cainiao"
    )
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def parse_tracking_response(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Parses Cainiao JSON response into normalized event dictionaries:
    [
        {
            "event_date": "2026-08-26 17:53:11",
            "location": "",
            "status": "Arrived at linehaul office",
            "description": "Carrier note: Arrived at linehual office",
            "origin_country": "Mainland China",
            "destination_country": "Bangladesh",
            "source": "cainiao",
            "action_code": "LH_ARRIVE",
            "timezone": "GMT+6",
            "event_hash": "..."
        },
        ...
    ]
    Returned in chronological order (oldest -> newest).
    """
    events: List[Dict[str, Any]] = []

    if not data or not data.get("success"):
        return events

    modules = data.get("module")
    if not isinstance(modules, list) or not modules:
        return events

    mail_item = modules[0]
    tracking_number = mail_item.get("mailNo", "")
    origin_country = mail_item.get("originCountry", "")
    dest_country = mail_item.get("destCountry", "")

    detail_list = mail_item.get("detailList")
    if not isinstance(detail_list, list) or not detail_list:
        # Fallback to latestTrace or globalCombinedLogisticsTraceDTO if detailList is empty
        single_trace = mail_item.get("latestTrace") or mail_item.get("globalCombinedLogisticsTraceDTO")
        if single_trace and isinstance(single_trace, dict):
            detail_list = [single_trace]
        else:
            return events

    for item in detail_list:
        event_date = item.get("timeStr", "")
        status = item.get("standerdDesc") or item.get("desc") or ""
        desc_title = item.get("descTitle", "")
        raw_desc = item.get("desc", "")
        description = f"{desc_title} {raw_desc}".strip() if desc_title else raw_desc
        action_code = item.get("actionCode", "")
        timezone = item.get("timeZone", "")

        event = {
            "event_date": event_date,
            "location": "",
            "status": status,
            "description": description,
            "origin_country": origin_country,
            "destination_country": dest_country,
            "source": "cainiao",
            "action_code": action_code,
            "timezone": timezone
        }
        event["event_hash"] = generate_cainiao_event_hash(tracking_number, event)
        events.append(event)

    # Cainiao detailList is usually returned newest -> oldest (or vice versa).
    # Sort events chronologically by event_date (or time)
    def parse_time(evt):
        return evt.get("event_date", "")

    events.sort(key=parse_time)

    return events


def get_cainiao_summary(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extracts high-level summary info from Cainiao response.
    """
    if not data or not data.get("success"):
        return None

    modules = data.get("module")
    if not isinstance(modules, list) or not modules:
        return None

    item = modules[0]
    return {
        "tracking_number": item.get("mailNo", ""),
        "origin_country": item.get("originCountry", ""),
        "dest_country": item.get("destCountry", ""),
        "mail_type": item.get("mailType", ""),
        "mail_type_desc": item.get("mailTypeDesc", ""),
        "status": item.get("status", ""),
        "status_desc": item.get("statusDesc", ""),
        "mail_no_source": item.get("mailNoSource", "")
    }
