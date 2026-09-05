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


TRANSIT_HUBS = ['airport', 'sorting', 'impc', 'foreign post', 'ded exch', 'inward', 'transit', 'exchange']
STOP_WORDS = {'model', 'town', 'sub', 'office', 'branch', 'bazar', 'sadar', 'road', 'area'}


def match_location_to_post_office(location_str: str) -> Optional[Dict[str, Any]]:
    """
    Extracts and maps a BD Post event location (e.g., 'Mirpur 1', 'DHAKA AIRPORT SORTING OFFICE', 'Agrabad')
    into a structured Post Office match with 4-tier fallback handling:
    - Tier 1: Exact / Confident Sub-Office Match (with direct phone if available)
    - Tier 2: Transit Hub (Airport Sorting / IMPC / Hub)
    - Tier 3: Ambiguous Location (multiple matching districts)
    - Tier 4: Unrecognized / None
    """
    _ensure_data_loaded()
    if not location_str or not isinstance(location_str, str):
        return None

    norm = location_str.strip().lower()

    # Tier 2: Transit / Sorting Facilities
    if any(hub in norm for hub in TRANSIT_HUBS):
        return {
            "tier": "transit_hub",
            "facility": location_str.strip(),
            "post_office": None,
            "contact": None
        }

    cleaned = re.sub(r"\b(so|ho|spo|bo|tpo|gpo|tso|edso|post office|sub office|branch office)\b", "", norm, flags=re.I).strip()
    cleaned = re.sub(r"[\-_/]+", " ", cleaned).strip()

    # 1. Exact match on post_office name
    for po in _POST_OFFICES:
        po_name = po["post_office"].lower()
        if norm == po_name or (cleaned and cleaned == po_name):
            contact = get_fallback_contact_for_office(po)
            return {"tier": "match", "post_office": po, "contact": contact}

    # Mirpur sub-area heuristic (Mirpur 1, 2, 6, 10, 11, 12, 14 -> Mirpur TSO 1216)
    if "mirpur" in norm:
        for po in _POST_OFFICES:
            if po["post_office"] == "Mirpur TSO" and po["district"] == "Dhaka":
                contact = get_fallback_contact_for_office(po)
                return {"tier": "match", "post_office": po, "contact": contact}

    tokens = [t for t in re.split(r"\s+", cleaned) if t and t not in STOP_WORDS]

    candidates = []
    for po in _POST_OFFICES:
        po_name = po["post_office"].lower()
        thana = po["thana"].lower()

        # Starts-with / exact token match
        if tokens and any(po_name.startswith(t) or thana.startswith(t) for t in tokens):
            candidates.append((5, po))
        elif cleaned and cleaned in po_name:
            candidates.append((4, po))
        elif thana and cleaned and (cleaned == thana or cleaned in thana):
            candidates.append((3, po))
        elif tokens and any(t in po_name or t in thana for t in tokens):
            candidates.append((2, po))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    best_score = candidates[0][0]
    best_matches = [c[1] for c in candidates if c[0] == best_score]

    if len(best_matches) == 1:
        po = best_matches[0]
        contact = get_fallback_contact_for_office(po)
        return {"tier": "match", "post_office": po, "contact": contact}

    dists = {m["district"] for m in best_matches}
    if len(dists) > 1 and len(best_matches) > 3:
        return {
            "tier": "ambiguous",
            "count": len(best_matches),
            "query": location_str.strip(),
            "post_office": None,
            "contact": None
        }

    po = best_matches[0]
    contact = get_fallback_contact_for_office(po)
    return {"tier": "match", "post_office": po, "contact": contact}
