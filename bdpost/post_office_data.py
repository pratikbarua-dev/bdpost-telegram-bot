import json
import re
import os
import logging
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

BN_TO_EN = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def clean_phone_number(raw: Optional[str]) -> Tuple[Optional[str], str]:
    """
    Cleans, normalizes, and validates Bangladesh mobile and landline numbers.
    Returns: (cleaned_number, type) where type in ['MOBILE', 'LANDLINE', 'INVALID']
    """
    if not raw or str(raw).strip() in ["N/A", "None", "-", "", "Not Found"]:
        return None, "EMPTY"

    cleaned = str(raw).translate(BN_TO_EN).strip()
    digits = re.sub(r"[^\d]", "", cleaned)

    # Normalize country codes
    if digits.startswith("880"):
        digits = "0" + digits[3:]
    elif digits.startswith("88"):
        digits = "0" + digits[2:]
    elif len(digits) == 10 and digits.startswith("1") and digits[1] in "3456789":
        # Missing leading 0 (e.g. 1715258986)
        digits = "0" + digits

    # Mobile: 11 digits starting with 013-019
    if len(digits) == 11 and re.match(r"^01[3-9]\d{8}$", digits):
        formatted = f"{digits[:5]}-{digits[5:]}"
        return formatted, "MOBILE"

    # BTCL Standard & NGN Landline (6 to 11 digits)
    if (6 <= len(digits) <= 11) and re.match(r"^(02|03|04|05|06|07|08|09)\d+", digits):
        # Format landline with hyphen
        if digits.startswith("02") and len(digits) >= 9:
            formatted = f"02-{digits[2:]}"
        elif len(digits) >= 9 and digits.startswith("02"):
            formatted = f"{digits[:4]}-{digits[4:]}"
        else:
            formatted = digits
        return formatted, "LANDLINE"

    # Short 6-8 digit local landline
    if 6 <= len(digits) <= 8:
        return digits, "LANDLINE"

    return None, "INVALID"


def get_cleaned_post_offices_data() -> List[Dict[str, Any]]:
    """
    Loads and sanitizes the 1,349 post offices master dataset.
    Prioritizes bd_post_offices_master_complete.json for full coverage (562+ direct numbers).
    """
    candidate_paths = [
        os.path.join(os.path.dirname(__file__), "..", "data", "bd_post_offices_master_complete.json"),
        os.path.join(os.path.dirname(__file__), "..", "data", "bd_post_offices_with_phones.json"),
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "bd_post_offices_master_complete.json"),
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "bd_post_offices_with_phones.json"),
    ]

    raw_list = []
    for p in candidate_paths:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                raw_list = json.load(f)
            if raw_list and any(item.get("phone_number") or item.get("phone") for item in raw_list):
                break

    sanitized = []
    for item in raw_list:
        raw_phone = item.get("phone_number") or item.get("phone")
        clean_ph, ph_type = clean_phone_number(raw_phone)
        po_name = item.get("post_office_name") or item.get("postOffice") or ""
        po_code = item.get("post_code") or item.get("postCode") or ""
        thana = item.get("thana_upazila") or item.get("thana") or ""
        dist = item.get("district") or ""
        div = item.get("division") or ""
        src = item.get("source") or "bdpost"

        sanitized.append({
            "post_office": str(po_name).strip(),
            "post_code": str(po_code).strip(),
            "thana": str(thana).strip(),
            "district": str(dist).strip(),
            "division": str(div).strip(),
            "phone": clean_ph if ph_type in ["MOBILE", "LANDLINE"] else None,
            "source": src
        })
    return sanitized


def get_cleaned_officials_data() -> List[Dict[str, Any]]:
    """
    Loads and sanitizes the 288 government postal officials dataset.
    """
    candidate_paths = [
        os.path.join(os.path.dirname(__file__), "..", "data", "official_portal_contacts.json"),
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "official_portal_contacts.json"),
    ]

    raw_list = []
    for p in candidate_paths:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                raw_list = json.load(f)
            if raw_list:
                break

    sanitized = []
    for item in raw_list:
        clean_mob, _ = clean_phone_number(item.get("mobile"))
        clean_land, _ = clean_phone_number(item.get("phone_office"))

        sanitized.append({
            "portal": str(item.get("portal", "")).strip(),
            "name": str(item.get("name", "")).strip(),
            "designation": str(item.get("designation", "")).strip(),
            "office": str(item.get("office", "")).strip(),
            "email": str(item.get("email", "")).strip() or None,
            "phone_office": clean_land,
            "mobile": clean_mob,
            "fax": str(item.get("fax", "")).strip() or None
        })
    return sanitized
