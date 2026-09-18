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


def get_delivery_channel_badge(tracking_number: str, tracking_chain: Optional[List[str]] = None) -> str:
    """
    Determines whether the parcel is destined for RedX home delivery (BR...MG)
    or Local Bangladesh Post Office based on prefix and known chain.
    """
    all_numbers = [tracking_number] + (tracking_chain or [])
    is_redx = any(
        n.strip().upper().startswith("BR") and n.strip().upper().endswith("MG")
        for n in all_numbers if n
    )
    if is_redx:
        return "🚚 <b>Delivery Channel:</b> RedX Courier (Home Delivery ~10-13 days)"
    return "📮 <b>Delivery Channel:</b> Bangladesh Post Office (~15-30+ days)"


def get_status_smart_insight(status: str, desc: str, source: str) -> Optional[str]:
    """
    Generates actionable, contextual advice based on the carrier and stage.
    """
    st_lower = (status or "").lower()
    desc_lower = (desc or "").lower()

    if source == "cainiao":
        if any(w in st_lower or w in desc_lower for w in ["linehaul", "linehual", "local airport", "destination country"]):
            return "💡 <i>টিপ: পার্সেল বাংলাদেশে এসে পৌঁছেছে। কাস্টমস ছাড়িয়ে ডাকঘর সিস্টেমে এন্ট্রি হতে ২–৪ কার্যদিবস সময় লাগতে পারে।</i>"
        if any(w in st_lower or w in desc_lower for w in ["awaiting flight", "awaiting transit", "departure transport hub"]):
            return "💡 <i>টিপ: পার্সেলটি চায়না বিমানবন্দরে ফ্লাইটের অপেক্ষায় আছে (এ স্টেজে সাধারণত ৪–৬ দিন সময় লাগে)।</i>"
    elif source == "bdpost":
        if "delivered" in st_lower:
            return "💡 <i>জরুরি তথ্য: পোস্ট অফিসের সিস্টেমে 'Delivered' মানে পার্সেলটি আপনার লোকাল ডাকঘরে বুক হয়েছে। পোস্টম্যান যোগাযোগ না করলে সরাসরি শাখায় যোগাযোগ করতে পারেন।</i>"
        if "wrongly directed" in st_lower or "wrongly directed" in desc_lower or "wrongly forwarded" in desc_lower:
            return "💡 <i>টিপ: এটি স্বাভাবিক — জেলা প্রধান ডাকঘর (HO) থেকে পার্সেলটি আপনার স্থানীয় উপজেলা শাখায় পাঠানো হচ্ছে।</i>"
    return None


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

    # Add Delivery Channel Badge
    badge = get_delivery_channel_badge(tracking_number, tracking_chain)
    lines.append(badge)

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

    # Contextual Smart Insight based on stage/carrier
    insight = get_status_smart_insight(status, desc, source)
    if insight:
        extra_meta.append(insight)

    # Attach Post Office & Direct Phone Block for BD Post events
    if source == "bdpost" and location:
        from bdpost.directory import match_location_to_post_office
        match_info = match_location_to_post_office(location)
        if match_info:
            if match_info.get("tier") == "transit_hub":
                extra_meta.append(f"🏢 <b>Facility:</b> {_esc(match_info.get('facility'))}\n   <i>⏳ In transit to your local delivery post office.</i>")
            elif match_info.get("tier") in ["match", "exact"] and match_info.get("post_office"):
                po = match_info["post_office"]
                po_name = _esc(po.get("post_office"))
                po_code = _esc(po.get("post_code"))
                po_dist = _esc(po.get("district"))
                phone = po.get("phone")

                extra_meta.append(f"🏛️ <b>Post Office:</b> {po_name} (Postcode: <code>{po_code}</code>, {po_dist})")
                if phone:
                    extra_meta.append(f"☎️ <b>Office Phone:</b> <code>{_esc(phone)}</code>\n   <i>💡 Tip: Call for early pickup or delivery queries!</i>")
                else:
                    extra_meta.append("ℹ️ <i>Direct office phone not on record yet.</i>\n   <i>💡 Know their number? Tap below to contribute!</i>")
            elif match_info.get("tier") == "ambiguous":
                extra_meta.append(f"💡 <i>Multiple post offices match '{_esc(location)}'. Tap below to find yours.</i>")

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

    # Attach Post Office & Direct Phone Block for BD Post events
    if source == "bdpost" and location:
        from bdpost.directory import match_location_to_post_office
        match_info = match_location_to_post_office(location)
        if match_info:
            if match_info.get("tier") == "transit_hub":
                extra_meta.append(f"🏢 <b>Facility:</b> {_esc(match_info.get('facility'))}\n   <i>⏳ In transit to your local delivery post office.</i>")
            elif match_info.get("tier") in ["match", "exact"] and match_info.get("post_office"):
                po = match_info["post_office"]
                po_name = _esc(po.get("post_office"))
                po_code = _esc(po.get("post_code"))
                po_dist = _esc(po.get("district"))
                phone = po.get("phone")

                extra_meta.append(f"🏛️ <b>Post Office:</b> {po_name} (Postcode: <code>{po_code}</code>, {po_dist})")
                if phone:
                    extra_meta.append(f"☎️ <b>Office Phone:</b> <code>{_esc(phone)}</code>\n   <i>💡 Tip: Call for early pickup or delivery queries!</i>")
                else:
                    extra_meta.append("ℹ️ <i>Direct office phone not on record yet.</i>\n   <i>💡 Know their number? Tap below to contribute!</i>")
            elif match_info.get("tier") == "ambiguous":
                extra_meta.append(f"💡 <i>Multiple post offices match '{_esc(location)}'. Tap below to find yours.</i>")

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
