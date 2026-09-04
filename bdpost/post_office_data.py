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
    Loads and sanitizes the 1,349 post offices dataset.
    """
    data_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "bd_post_offices_with_phones.json")
    if not os.path.exists(data_path):
        # Alternate path lookup
        data_path = "/home/p4b/Downloads/gtandtrace/data/bd_post_offices_with_phones.json"

    with open(data_path, "r", encoding="utf-8") as f:
        raw_list = json.load(f)

    sanitized = []
    for item in raw_list:
        raw_phone = item.get("phone")
        clean_ph, ph_type = clean_phone_number(raw_phone)
        sanitized.append({
            "post_office": str(item.get("postOffice", "")).strip(),
            "post_code": str(item.get("postCode", "")).strip(),
            "thana": str(item.get("thana", "")).strip(),
            "district": str(item.get("district", "")).strip(),
            "division": str(item.get("division", "")).strip(),
            "phone": clean_ph if ph_type in ["MOBILE", "LANDLINE"] else None,
            "source": item.get("source", "bdpost")
        })
    return sanitized


def get_cleaned_officials_data() -> List[Dict[str, Any]]:
    """
    Loads and sanitizes the 288 government postal officials dataset.
    """
    data_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "official_portal_contacts.json")
    if not os.path.exists(data_path):
        data_path = "/home/p4b/Downloads/gtandtrace/data/official_portal_contacts.json"

    with open(data_path, "r", encoding="utf-8") as f:
        raw_list = json.load(f)

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
