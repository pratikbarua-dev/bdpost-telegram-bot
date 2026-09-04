import re
import logging
from typing import List, Dict, Any, Optional, Tuple
from bdpost.post_office_data import get_cleaned_post_offices_data, get_cleaned_officials_data

logger = logging.getLogger(__name__)

# Cached in-memory datasets
_POST_OFFICES: List[Dict[str, Any]] = []
_OFFICIALS: List[Dict[str, Any]] = []

DIVISION_TO_CIRCLE_MAP = {
    "dhaka": ["Metro Circle, Dhaka", "Central Circle, Dhaka", "Directorate of Posts, Headquarters"],
    "chittagong": ["Eastern Circle, Chittagong", "Directorate of Posts, Headquarters"],
    "chattogram": ["Eastern Circle, Chittagong", "Directorate of Posts, Headquarters"],
    "rajshahi": ["Northern Circle, Rajshahi", "Postal Academy, Rajshahi", "Directorate of Posts, Headquarters"],
    "khulna": ["Southern Circle, Khulna", "Directorate of Posts, Headquarters"],
    "barisal": ["Southern Circle, Khulna", "Central Circle, Dhaka", "Directorate of Posts, Headquarters"],
    "barishal": ["Southern Circle, Khulna", "Central Circle, Dhaka", "Directorate of Posts, Headquarters"],
    "sylhet": ["Eastern Circle, Chittagong", "Central Circle, Dhaka", "Directorate of Posts, Headquarters"],
    "rangpur": ["PLI Western Circle, Rangpur", "Northern Circle, Rajshahi", "Directorate of Posts, Headquarters"],
    "mymensingh": ["Central Circle, Dhaka", "Directorate of Posts, Headquarters"],
}


def _ensure_data_loaded():
    global _POST_OFFICES, _OFFICIALS
    if not _POST_OFFICES:
        _POST_OFFICES = get_cleaned_post_offices_data()
    if not _OFFICIALS:
        _OFFICIALS = get_cleaned_officials_data()


def search_post_offices(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Searches post offices by 4-digit postcode, name, thana, or district.
    """
    _ensure_data_loaded()
    q = query.strip().lower()
    if not q:
        return []

    results = []
    # 1. Exact postcode match
    if q.isdigit() and len(q) == 4:
        for po in _POST_OFFICES:
            if po["post_code"] == q:
                results.append(po)
        if results:
            return results[:limit]

    # 2. Starts-with or Substring match
    exact_name_matches = []
    partial_matches = []
    query_tokens = [t for t in re.split(r"[\s\-_]+", q) if t]

    for po in _POST_OFFICES:
        po_name = po["post_office"].lower()
        thana = po["thana"].lower()
        dist = po["district"].lower()
        search_blob = f"{po_name} {thana} {dist} {po['post_code']}"

        if q == po_name or q == thana or q == dist:
            exact_name_matches.append(po)
        elif q in search_blob or (query_tokens and all(token in search_blob for token in query_tokens)):
            partial_matches.append(po)
        elif query_tokens and any(token == po_name or token == thana for token in query_tokens):
            partial_matches.append(po)

    combined = exact_name_matches + partial_matches
    # Deduplicate while preserving rank
    seen_keys = set()
    ranked = []
    for item in combined:
        key = (item["post_office"], item["post_code"], item["district"])
        if key not in seen_keys:
            seen_keys.add(key)
            ranked.append(item)
            if len(ranked) >= limit:
                break

    return ranked


def get_fallback_contact_for_office(post_office: Dict[str, Any]) -> Dict[str, Any]:
    """
    Returns verified contact details using the 3-Tier Fallback Hierarchy:
    - Tier 1: Direct sub-office / branch office phone if present.
    - Tier 2: Regional Deputy Postmaster General (DPMG) / Circle Director contact for that division.
    - Tier 3: National Directorate of Posts Central Help Desk.
    """
    _ensure_data_loaded()
    direct_phone = post_office.get("phone")
    if direct_phone:
        return {
            "tier": 1,
            "type": "Direct Office Phone",
            "phone": direct_phone,
            "mobile": None,
            "officer": None,
            "designation": None,
            "office_name": f"{post_office['post_office']} Sub Post Office"
        }

    division = post_office.get("division", "").lower().strip()
    district = post_office.get("district", "").lower().strip()
    target_circles = DIVISION_TO_CIRCLE_MAP.get(division, ["Directorate of Posts, Headquarters"])

    # Search for DPMG / Assistant Postmaster General in that Circle
    candidate = None
    for official in _OFFICIALS:
        portal = official.get("portal", "")
        if portal in target_circles and (official.get("mobile") or official.get("phone_office")):
            # Prefer senior field officer
            desig = official.get("designation", "").lower()
            if "পোস্টমাস্টার" in desig or "পরিচালক" in desig or "ম্যানেজার" in desig or "কর্মকর্তা" in desig:
                candidate = official
                break

    if not candidate and _OFFICIALS:
        candidate = _OFFICIALS[0]

    return {
        "tier": 2 if candidate.get("portal") != "Directorate of Posts, Headquarters" else 3,
        "type": "Regional Circle Helpline" if candidate.get("portal") != "Directorate of Posts, Headquarters" else "Central Directorate Helpline",
        "phone": candidate.get("phone_office"),
        "mobile": candidate.get("mobile"),
        "officer": candidate.get("name"),
        "designation": candidate.get("designation"),
        "office_name": candidate.get("office") or candidate.get("portal")
    }


def match_location_to_post_office(location_str: str) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """
    Extracts post office name from BD Post event location (e.g., "Mirpur 1 SO", "Dairy Farm SO", "Bogra HO")
    and returns (post_office_dict, contact_dict).
    """
    _ensure_data_loaded()
    if not location_str or not isinstance(location_str, str):
        return None

    cleaned = re.sub(r"\b(SO|HO|SPO|BO|TPO|GPO|Sorting Office|Post Office|Airport)\b", "", location_str, flags=re.IGNORECASE)
    cleaned = cleaned.strip()

    matches = search_post_offices(cleaned, limit=1)
    if matches:
        po = matches[0]
        contact = get_fallback_contact_for_office(po)
        return po, contact

    return None
