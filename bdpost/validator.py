import re
from typing import Optional, List

RESERVED_KEYWORDS = {
    "START", "TRACK", "STOP", "STATUS", "HELP", "MY", "PARCEL", "PARCELS",
    "FEEDBACK", "SUPPORT", "ADMIN", "STATS", "CANCEL", "HOME", "RENAME",
    "POSTCODE", "POSTCODES", "DHAKA", "CHITTAGONG", "SYLHET", "RAJSHAHI",
    "KHULNA", "BARISAL", "RANGPUR", "MYMENSINGH", "KISHORGANJ", "BANGLADESH"
}


def validate_and_normalize_tracking_number(raw_tracking: Optional[str]) -> Optional[str]:
    """
    Validates and normalizes a single tracking number:
    1. Trim whitespace & uppercase.
    2. Reject command keywords, city names, or text words.
    3. Ensure minimum length and structure (must contain at least 4 digits).
    4. Support standard formats:
       - UPU S10 (13 chars): 2 letters + 9 digits + 2 letters (e.g. UG251338889MV, BR006044821MG)
       - Cainiao / AliExpress: CNG..., AP..., LP... + 10-18 digits
       - BD Post domestic / express: BD... + digits, etc.
    """
    if not raw_tracking:
        return None

    cleaned = raw_tracking.strip().upper()

    # Reject keywords
    if cleaned in RESERVED_KEYWORDS:
        return None

    # Length bounds
    if len(cleaned) < 6 or len(cleaned) > 35:
        return None

    # Must be valid alphanumeric characters
    if not re.match(r"^[A-Z0-9\-]+$", cleaned):
        return None

    # Must contain at least 4 digits (rejects pure words like 'PARCEL' or 'DHAKA')
    digit_count = sum(1 for c in cleaned if c.isdigit())
    if digit_count < 4:
        return None

    return cleaned


def extract_tracking_numbers(args: List[str] | str) -> tuple[List[str], List[str]]:
    """
    Extracts multiple tracking numbers from args list or comma/whitespace/newline-separated string.
    Returns:
        (valid_numbers, invalid_numbers)
    """
    if isinstance(args, str):
        # Split by commas, whitespace, or newlines
        tokens = [t.strip() for t in re.split(r"[\s,;\n]+", args) if t.strip()]
    else:
        # If passed as a list of args from telegram command
        tokens = []
        for arg in args:
            for sub in re.split(r"[\s,;\n]+", arg):
                if sub.strip():
                    tokens.append(sub.strip())

    valid_numbers: List[str] = []
    invalid_numbers: List[str] = []
    seen: set[str] = set()

    for token in tokens:
        normalized = validate_and_normalize_tracking_number(token)
        if normalized:
            if normalized not in seen:
                seen.add(normalized)
                valid_numbers.append(normalized)
        else:
            invalid_numbers.append(token)

    return valid_numbers, invalid_numbers

