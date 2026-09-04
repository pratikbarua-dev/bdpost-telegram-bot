import html
from typing import Dict, Optional, List
from bdpost.parser import is_delivered


def _esc(val: Optional[str]) -> str:
    if not val:
        return ""
    return html.escape(str(val).strip())


def format_country_route(origin: Optional[str], destination: Optional[str]) -> str:
    origin_str = origin.strip() if origin and origin.strip() and origin.strip().lower() != "not found" else ""
    dest_str = destination.strip() if destination and destination.strip() and destination.strip().lower() != "not found" else ""

    if origin_str and dest_str:
        return f"🌍 <b>Route:</b> {_esc(origin_str)} → {_esc(dest_str)}"
    elif origin_str:
        return f"🌍 <b>Origin:</b> {_esc(origin_str)}"
    elif dest_str:
        return f"🌍 <b>Destination:</b> {_esc(dest_str)}"
    return ""


def format_tracking_chain(chain_numbers: Optional[List[str]]) -> str:
    if not chain_numbers or len(chain_numbers) <= 1:
        return ""
    seen = set()
    ordered = []
    for num in chain_numbers:
        if num not in seen:
            seen.add(num)
            ordered.append(f"<code>{_esc(num)}</code>")
    if len(ordered) > 1:
        return "🔗 <b>Chain:</b> " + " → ".join(ordered)
    return ""


def format_status_message(
    tracking_number: str,
    event: Dict,
    label: Optional[str] = None,
    tracking_chain: Optional[List[str]] = None,
    local_tracking_number: Optional[str] = None,
    header_title: Optional[str] = None
) -> str:
    source = event.get("source", "bdpost")
    location = event.get("location", "")
    status = event.get("status", "N/A")
    date = event.get("event_date", "N/A")
    desc = event.get("description", "")
    route = format_country_route(event.get("origin_country"), event.get("destination_country"))

    title = header_title if header_title else "📦 <b>Parcel Status</b>"
    lines = [
        title,
        "━━━━━━━━━━━━━━━━━━━━"
    ]

    if label:
        lines.append(f"🏷️ <b>Item:</b> {_esc(label)}")

    lines.append(f"🔢 <b>Tracking:</b> <code>{_esc(tracking_number)}</code>")

    if source == "cainiao":
        carrier_name = event.get("carrier_name") or "AliExpress / Cainiao"
        lines.append(f"🚚 <b>Carrier:</b> {_esc(carrier_name)}")
    else:
        lines.append("🇧🇩 <b>Carrier:</b> Bangladesh Post")

    if local_tracking_number and local_tracking_number != tracking_number:
        lines.append(f"🇧🇩 <b>Local Tracking:</b> <code>{_esc(local_tracking_number)}</code>")

    lines.append("")
    lines.append(f"📌 <b>Status:</b> {_esc(status)}")

    if location:
        lines.append(f"📍 <b>Location:</b> {_esc(location)}")

    if desc and desc != status:
        lines.append(f"📝 <b>Details:</b> <i>{_esc(desc)}</i>")

    lines.append(f"🕐 <b>Date:</b> {_esc(date)}")

    extra_meta = []
    if route:
        extra_meta.append(route)

    chain_str = format_tracking_chain(tracking_chain)
    if chain_str:
        extra_meta.append(chain_str)

    if extra_meta:
        lines.append("")
        lines.extend(extra_meta)

    lines.append("━━━━━━━━━━━━━━━━━━━━")
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

    if is_delivered(status):
        lines = [
            "🎉 <b>Parcel Delivered!</b>",
            "━━━━━━━━━━━━━━━━━━━━"
        ]
        if label:
            lines.append(f"🏷️ <b>Item:</b> {_esc(label)}")
        lines.append(f"🔢 <b>Tracking:</b> <code>{_esc(tracking_number)}</code>")
        if local_tracking_number and local_tracking_number != tracking_number:
            lines.append(f"🇧🇩 <b>Local Tracking:</b> <code>{_esc(local_tracking_number)}</code>")
        if location:
            lines.append(f"📍 <b>Location:</b> {_esc(location)}")
        lines.append(f"📌 <b>Status:</b> {_esc(status)}")
        lines.append(f"🕐 <b>Date:</b> {_esc(date)}")
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)

    lines = [
        "📦 <b>Parcel Update</b>",
        "━━━━━━━━━━━━━━━━━━━━"
    ]

    if label:
        lines.append(f"🏷️ <b>Item:</b> {_esc(label)}")
    lines.append(f"🔢 <b>Tracking:</b> <code>{_esc(tracking_number)}</code>")

    if source == "cainiao":
        carrier_name = event.get("carrier_name") or "AliExpress / Cainiao"
        lines.append(f"🚚 <b>Source:</b> {_esc(carrier_name)}")
    else:
        lines.append("🇧🇩 <b>Source:</b> Bangladesh Post")

    lines.append("")
    lines.append(f"📌 <b>Status:</b> {_esc(status)}")
    if location:
        lines.append(f"📍 <b>Location:</b> {_esc(location)}")
    lines.append(f"📅 <b>Date:</b> {_esc(date)}")

    if desc and desc != status:
        lines.append(f"📝 <b>Details:</b> <i>{_esc(desc)}</i>")

    extra_meta = []
    if route:
        extra_meta.append(route)
    chain_str = format_tracking_chain(tracking_chain)
    if chain_str:
        extra_meta.append(chain_str)

    if extra_meta:
        lines.append("")
        lines.extend(extra_meta)

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def format_handover_notification(
    tracking_number: str,
    event: Dict,
    label: Optional[str] = None,
    local_tracking_number: Optional[str] = None,
    tracking_chain: Optional[List[str]] = None
) -> str:
    location = event.get("location", "")
    status = event.get("status", "Arrived in destination country")
    date = event.get("event_date", "")

    lines = [
        "🇧🇩 <b>Parcel Reached Bangladesh!</b>",
        "━━━━━━━━━━━━━━━━━━━━"
    ]
    if label:
        lines.append(f"🏷️ <b>Item:</b> {_esc(label)}")
    lines.append(f"🔢 <b>Original Tracking:</b> <code>{_esc(tracking_number)}</code>")
    if local_tracking_number:
        lines.append(f"🇧🇩 <b>Local Tracking:</b> <code>{_esc(local_tracking_number)}</code>")

    lines.append("")
    lines.append(f"📌 <b>Status:</b> {_esc(status)}")
    if location:
        lines.append(f"📍 <b>Location:</b> {_esc(location)}")
    if date:
        lines.append(f"🕐 <b>Date:</b> {_esc(date)}")

    lines.append("")
    lines.append("🔄 <i>Tracking automatically switched to Bangladesh Post for local delivery.</i>")

    chain_str = format_tracking_chain(tracking_chain)
    if chain_str:
        lines.append("")
        lines.append(chain_str)

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def format_pending_status_message(
    tracking_number: str,
    label: Optional[str] = None,
    tracking_chain: Optional[List[str]] = None,
    day_number: int = 1
) -> str:
    lines = [
        "⏳ <b>Tracking Registered</b>",
        "━━━━━━━━━━━━━━━━━━━━"
    ]
    if label:
        lines.append(f"🏷️ <b>Item:</b> {_esc(label)}")
    lines.append(f"🔢 <b>Tracking:</b> <code>{_esc(tracking_number)}</code>")
    lines.append(f"📊 <b>Status:</b> Awaiting first scan (Day {day_number} of 10)")
    lines.append("")
    lines.append("💡 <i>Sellers often generate shipping labels a few days before physical dispatch.</i>")
    lines.append("🤖 <i>Auto-monitoring active. You'll be notified automatically on the first scan.</i>")

    chain_str = format_tracking_chain(tracking_chain)
    if chain_str:
        lines.append("")
        lines.append(chain_str)

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def format_expiry_notification(
    tracking_number: str,
    label: Optional[str] = None
) -> str:
    item_title = f"<b>{_esc(label)}</b> (<code>{_esc(tracking_number)}</code>)" if label else f"<code>{_esc(tracking_number)}</code>"
    return (
        "⚠️ <b>Tracking Expired (10 Days Inactive)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Parcel: {item_title}\n\n"
        "No tracking updates appeared from the carrier within 10 days.\n"
        "Automatic background monitoring for this parcel has been stopped.\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )
