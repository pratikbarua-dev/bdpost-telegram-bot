from typing import Dict, Optional
from bdpost.parser import is_delivered, is_out_for_delivery, is_arrived_at_post_office, is_dispatched


def format_country_route(origin: Optional[str], destination: Optional[str]) -> str:
    origin_str = origin.strip() if origin and origin.strip() and origin.strip().lower() != "not found" else "Unknown"
    dest_str = destination.strip() if destination and destination.strip() and destination.strip().lower() != "not found" else "Unknown"
    
    if origin_str != "Unknown" or dest_str != "Unknown":
        return f"🌍 {origin_str} → {dest_str}"
    return ""


def format_status_message(tracking_number: str, event: Dict) -> str:
    location = event.get("location", "N/A")
    status = event.get("status", "N/A")
    date = event.get("event_date", "N/A")
    route = format_country_route(event.get("origin_country"), event.get("destination_country"))

    lines = [
        f"📦 Tracking: {tracking_number}\n",
        f"📍 Location: {location}",
        f"📌 Status: {status}",
        f"🕐 Date: {date}"
    ]
    if route:
        lines.append(f"\n{route}")

    return "\n".join(lines)


def format_event_notification(tracking_number: str, event: Dict) -> str:
    status = event.get("status", "N/A")
    location = event.get("location", "N/A")
    date = event.get("event_date", "N/A")
    route = format_country_route(event.get("origin_country"), event.get("destination_country"))

    if is_delivered(status):
        lines = [
            "🎉 Parcel Delivered!\n",
            f"Tracking: {tracking_number}\n",
            f"📍 {location}",
            f"📌 {status}",
            f"🕐 {date}"
        ]
        if route:
            lines.append(f"\n{route}")
        return "\n".join(lines)

    lines = [
        "📦 Parcel Update\n",
        f"Tracking: {tracking_number}\n",
        "🆕 New tracking event\n",
        f"📅 {date}",
        f"📍 {location}",
        f"📌 {status}"
    ]
    if route:
        lines.append(f"\n{route}")

    return "\n".join(lines)
