import re
from typing import Optional, List


def validate_and_normalize_tracking_number(raw_tracking: Optional[str]) -> Optional[str]:
    """
    Validates and normalizes a single tracking number:
    1. Trim whitespace.
    2. Convert to uppercase.
    3. Reject empty or excessively long input.
    4. Allow standard postal alphanumeric characters (e.g. UG251338889MV, CD123456789BD).
    """
    if not raw_tracking:
        return None

    cleaned = raw_tracking.strip().upper()

    # Reject if empty or unreasonably long/short
    if len(cleaned) < 4 or len(cleaned) > 35:
        return None

    # Alphanumeric with optional hyphens
    if not re.match(r"^[A-Z0-9\-]+$", cleaned):
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

