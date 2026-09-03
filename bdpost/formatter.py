from typing import Dict, Optional
from bdpost.parser import is_delivered, is_out_for_delivery, is_arrived_at_post_office


def format_country_route(origin: Optional[str], destination: Optional[str]) -> str:
    origin_str = origin.strip() if origin and origin.strip() and origin.strip().lower() != "not found" else "Unknown"
    dest_str = destination.strip() if destination and destination.strip() and destination.strip().lower() != "not found" else "Unknown"
    
    if origin_str != "Unknown" or dest_str != "Unknown":
        return f"🌍 {origin_str} → {dest_str}"
    return ""


from typing import Dict, Optional, List
from bdpost.parser import is_delivered, is_out_for_delivery, is_arrived_at_post_office


def format_country_route(origin: Optional[str], destination: Optional[str]) -> str:
    origin_str = origin.strip() if origin and origin.strip() and origin.strip().lower() != "not found" else "Unknown"
    dest_str = destination.strip() if destination and destination.strip() and destination.strip().lower() != "not found" else "Unknown"
    
    if origin_str != "Unknown" or dest_str != "Unknown":
        return f"🌍 {origin_str} → {dest_str}"
    return ""


def format_tracking_chain(chain_numbers: Optional[List[str]]) -> str:
    if not chain_numbers or len(chain_numbers) <= 1:
        return ""
    # Deduplicate preserving order
    seen = set()
    ordered = []
    for num in chain_numbers:
        if num not in seen:
            seen.add(num)
            ordered.append(f"`{num}`")
    if len(ordered) > 1:
        return "🔗 *Tracking Chain:*\n" + " → ".join(ordered)
    return ""


def format_status_message(
    tracking_number: str,
    event: Dict,
    label: Optional[str] = None,
    tracking_chain: Optional[List[str]] = None,
    local_tracking_number: Optional[str] = None
) -> str:
    source = event.get("source", "bdpost")
    location = event.get("location", "")
    status = event.get("status", "N/A")
    date = event.get("event_date", "N/A")
    desc = event.get("description", "")
    route = format_country_route(event.get("origin_country"), event.get("destination_country"))

    header = f"📦 *Parcel:* `{label}` (`{tracking_number}`)\n" if label else f"📦 *Tracking:* `{tracking_number}`\n"
    lines = [header]

    if source == "cainiao":
        lines.append("🚚 *Provider:* AliExpress / Cainiao")
    else:
        lines.append("🇧🇩 *Provider:* Bangladesh Post")

    if location:
        lines.append(f"📍 *Location:* {location}")

    lines.append(f"📌 *Status:* {status}")

    if desc and desc != status:
        lines.append(f"📝 *Details:* {desc}")

    lines.append(f"🕐 *Date:* {date}")

    if local_tracking_number and local_tracking_number != tracking_number:
        lines.append(f"🇧🇩 *Local Tracking:* `{local_tracking_number}`")

    if route:
        lines.append(f"\n{route}")

    chain_str = format_tracking_chain(tracking_chain)
    if chain_str:
        lines.append(f"\n{chain_str}")

    return "\n".join(lines)


def format_event_notification(
    tracking_number: str,
    event: Dict,
    label: Optional[str] = None,
    tracking_chain: Optional[List[str]] = None,
    local_tracking_number: Optional[str] = None
) -> str:
    source = event.get("source", "bdpost")
    status = event.get("status", "N/A")
    location = event.get("location", "")
    date = event.get("event_date", "N/A")
    desc = event.get("description", "")
    route = format_country_route(event.get("origin_country"), event.get("destination_country"))

    item_title = f"`{label}` (`{tracking_number}`)" if label else f"`{tracking_number}`"

    if is_delivered(status):
        lines = [
            "🎉 *Parcel Delivered!*\n",
            f"📦 Parcel: {item_title}"
        ]
        if local_tracking_number and local_tracking_number != tracking_number:
            lines.append(f"🇧🇩 Local Tracking: `{local_tracking_number}`")
        if location:
            lines.append(f"📍 {location}")
        lines.append(f"📌 {status}")
        lines.append(f"🕐 {date}")
        if route:
            lines.append(f"\n{route}")
        chain_str = format_tracking_chain(tracking_chain)
        if chain_str:
            lines.append(f"\n{chain_str}")
        return "\n".join(lines)

    lines = [
        "📦 *Parcel Update*\n",
        f"Parcel: {item_title}"
    ]

    if source == "cainiao":
        lines.append("🚚 *Source:* AliExpress / Cainiao")
    else:
        lines.append("🇧🇩 *Source:* Bangladesh Post")

    lines.append("🆕 *New tracking event:*\n")
    lines.append(f"📅 {date}")
    if location:
        lines.append(f"📍 {location}")
    lines.append(f"📌 {status}")

    if desc and desc != status:
        lines.append(f"📝 {desc}")

    if route:
        lines.append(f"\n{route}")

    chain_str = format_tracking_chain(tracking_chain)
    if chain_str:
        lines.append(f"\n{chain_str}")

    return "\n".join(lines)


def format_handover_notification(
    tracking_number: str,
    event: Dict,
    label: Optional[str] = None,
    local_tracking_number: Optional[str] = None,
    tracking_chain: Optional[List[str]] = None
) -> str:
    location = event.get("location", "Bangladesh")
    status = event.get("status", "Arrived in Bangladesh")
    date = event.get("event_date", "")
    item_title = f"`{label}` (`{tracking_number}`)" if label else f"`{tracking_number}`"

    lines = [
        "🇧🇩 *Your parcel has entered Bangladesh's local postal network.*\n",
        f"Original tracking: `{tracking_number}`"
    ]
    if local_tracking_number:
        lines.append(f"Local tracking: `{local_tracking_number}`")
    if location:
        lines.append(f"📍 Location: {location}")
    lines.append(f"📌 Status: {status}")
    if date:
        lines.append(f"🕐 Date: {date}")

    lines.append(
        "\n🔄 *International tracking has been handed over to Bangladesh Post.*\n"
        "I'll continue monitoring the parcel for local postal updates."
    )

    chain_str = format_tracking_chain(tracking_chain)
    if chain_str:
        lines.append(f"\n{chain_str}")

    return "\n".join(lines)


def format_pending_status_message(
    tracking_number: str,
    label: Optional[str] = None,
    tracking_chain: Optional[List[str]] = None,
    day_number: int = 1
) -> str:
    header = f"📦 *Parcel:* `{label}` (`{tracking_number}`)\n" if label else f"📦 *Tracking:* `{tracking_number}`\n"
    lines = [
        header,
        f"⏳ *Status:* Awaiting first carrier scan (Day {day_number} of 10)",
        "ℹ️ *Note:* Sellers often generate labels a few days before physical dispatch.",
        "",
        "🤖 *Auto-monitoring:* Active across AliExpress/Cainiao & Bangladesh Post.",
        "You will receive a notification as soon as the first tracking update appears."
    ]

    chain_str = format_tracking_chain(tracking_chain)
    if chain_str:
        lines.append(f"\n{chain_str}")

    return "\n".join(lines)


def format_expiry_notification(
    tracking_number: str,
    label: Optional[str] = None
) -> str:
    item_title = f"`{label}` (`{tracking_number}`)" if label else f"`{tracking_number}`"
    return (
        "⚠️ *Tracking Expired (10 Days Inactive)*\n\n"
        f"Parcel: {item_title}\n\n"
        "No tracking updates appeared from the carrier within 10 days.\n"
        "Automatic background monitoring for this parcel has been stopped."
    )

