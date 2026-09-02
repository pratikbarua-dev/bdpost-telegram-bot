from typing import Dict, Optional
from bdpost.parser import is_delivered, is_out_for_delivery, is_arrived_at_post_office


def format_country_route(origin: Optional[str], destination: Optional[str]) -> str:
    origin_str = origin.strip() if origin and origin.strip() and origin.strip().lower() != "not found" else "Unknown"
    dest_str = destination.strip() if destination and destination.strip() and destination.strip().lower() != "not found" else "Unknown"
    
    if origin_str != "Unknown" or dest_str != "Unknown":
        return f"🌍 {origin_str} → {dest_str}"
    return ""


def format_status_message(tracking_number: str, event: Dict, label: Optional[str] = None) -> str:
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

    if route:
        lines.append(f"\n{route}")

    return "\n".join(lines)


def format_event_notification(tracking_number: str, event: Dict, label: Optional[str] = None) -> str:
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
            f"📦 Parcel: {item_title}\n"
        ]
        if location:
            lines.append(f"📍 {location}")
        lines.append(f"📌 {status}")
        lines.append(f"🕐 {date}")
        if route:
            lines.append(f"\n{route}")
        return "\n".join(lines)

    lines = [
        "📦 *Parcel Update*\n",
        f"Parcel: {item_title}\n"
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

    return "\n".join(lines)


def format_handover_notification(tracking_number: str, event: Dict, label: Optional[str] = None) -> str:
    location = event.get("location", "Bangladesh")
    status = event.get("status", "Arrived in Bangladesh")
    date = event.get("event_date", "")
    item_title = f"`{label}` (`{tracking_number}`)" if label else f"`{tracking_number}`"

    lines = [
        "🇧🇩 *Parcel has reached Bangladesh!*\n",
        f"Parcel: {item_title}\n"
    ]
    if location:
        lines.append(f"📍 Location: {location}")
    lines.append(f"📌 Status: {status}")
    if date:
        lines.append(f"🕐 Date: {date}")

    lines.append(
        "\n🔄 *Tracking has been switched to Bangladesh Post.*\n"
        "I'll continue monitoring the parcel for local postal updates."
    )
    return "\n".join(lines)

