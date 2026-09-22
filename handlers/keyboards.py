from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Dict


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """
    Main persistent reply keyboard layout.
    """
    keyboard = [
        ["📦 Track Parcel", "🔍 Quick Status"],
        ["📋 My Parcels", "📮 Postcode & Offices"],
        ["💡 Shopping Guide", "💬 Feedback"],
        ["ℹ️ Help", "🏠 Home"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    """
    Keyboard shown during an active input prompt.
    """
    keyboard = [
        ["❌ Cancel", "🏠 Back to Home"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_parcel_inline_keyboard(tracking_number: str, location: str = "") -> InlineKeyboardMarkup:
    """
    Inline action buttons for an individual parcel, dynamically offering
    phone update or office lookup based on domestic location matching.
    """
    row1 = [
        InlineKeyboardButton("🔄 Refresh Status", callback_data=f"refresh:{tracking_number}"),
        InlineKeyboardButton("✏️ Rename", callback_data=f"rename:{tracking_number}")
    ]

    middle_rows = []
    if location:
        from bdpost.directory import match_location_to_post_office
        match_info = match_location_to_post_office(location)
        if match_info:
            if match_info.get("tier") in ["match", "exact"] and match_info.get("post_office"):
                po = match_info["post_office"]
                code = po.get("post_code", "")
                if po.get("phone"):
                    middle_rows.append([
                        InlineKeyboardButton("⚠️ Report Wrong Number", callback_data=f"report_phone:{code}")
                    ])
                else:
                    middle_rows.append([
                        InlineKeyboardButton("➕ Add Office Phone", callback_data=f"report_phone:{code}")
                    ])
            elif match_info.get("tier") == "ambiguous":
                middle_rows.append([
                    InlineKeyboardButton("🔍 Find My Post Office", callback_data=f"search_po:{location.strip()}")
                ])

    bottom_row = [
        InlineKeyboardButton("✅ Mark as Delivered", callback_data=f"deliver_user:{tracking_number}"),
        InlineKeyboardButton("🛑 Stop", callback_data=f"stop:{tracking_number}"),
        InlineKeyboardButton("🏠 Home", callback_data="go_home")
    ]

    buttons = [row1] + middle_rows + [bottom_row]
    return InlineKeyboardMarkup(buttons)


def get_my_parcels_inline_keyboard(
    trackings: List[Dict],
    filter_mode: str = "active",
    active_count: int = 0,
    delivered_count: int = 0,
    total_count: int = 0
) -> InlineKeyboardMarkup:
    """
    Inline buttons list for parcels with filter tabs:
    [ 🚚 In Transit ] [ ✅ Delivered ] [ 📦 All ]
    """
    buttons = []

    # Filter navigation tabs
    tab_active = f"{'• ' if filter_mode == 'active' else ''}🚚 In Transit ({active_count}){' •' if filter_mode == 'active' else ''}"
    tab_delivered = f"{'• ' if filter_mode == 'delivered' else ''}✅ Delivered ({delivered_count}){' •' if filter_mode == 'delivered' else ''}"
    tab_all = f"{'• ' if filter_mode == 'all' else ''}📦 All ({total_count}){' •' if filter_mode == 'all' else ''}"

    buttons.append([
        InlineKeyboardButton(tab_active, callback_data="view_parcels:active"),
        InlineKeyboardButton(tab_delivered, callback_data="view_parcels:delivered"),
        InlineKeyboardButton(tab_all, callback_data="view_parcels:all")
    ])

    for item in trackings:
        num = item["tracking_number"]
        label = item.get("label")
        is_deliv = bool(item.get("is_delivered") == 1 or item.get("is_subscribed") == 0)
        btn_text = f"{label} ({num})" if label else num

        if is_deliv:
            buttons.append([
                InlineKeyboardButton(f"✅ {btn_text}", callback_data=f"refresh:{num}"),
                InlineKeyboardButton("🔄 Re-track", callback_data=f"retrack:{num}")
            ])
        else:
            buttons.append([
                InlineKeyboardButton(f"📦 {btn_text}", callback_data=f"refresh:{num}"),
                InlineKeyboardButton("✏️", callback_data=f"rename:{num}"),
                InlineKeyboardButton("✅", callback_data=f"deliver_user:{num}"),
                InlineKeyboardButton("🛑", callback_data=f"stop:{num}")
            ])

    if filter_mode == "active" and trackings:
        buttons.append([
            InlineKeyboardButton("🔄 Refresh All", callback_data="refresh_all"),
            InlineKeyboardButton("🛑 Stop All", callback_data="stop_all_confirm")
        ])
    elif filter_mode == "all" and trackings:
        buttons.append([
            InlineKeyboardButton("🔄 Refresh All", callback_data="refresh_all")
        ])

    buttons.append([
        InlineKeyboardButton("🏠 Back to Home", callback_data="go_home")
    ])
    return InlineKeyboardMarkup(buttons)


def get_stop_all_confirm_keyboard() -> InlineKeyboardMarkup:
    """
    Confirmation buttons for Stop All.
    """
    buttons = [
        [
            InlineKeyboardButton("✅ Yes, Stop All", callback_data="stop_all_confirmed"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")
        ],
        [
            InlineKeyboardButton("🏠 Back to Home", callback_data="go_home")
        ]
    ]
    return InlineKeyboardMarkup(buttons)

