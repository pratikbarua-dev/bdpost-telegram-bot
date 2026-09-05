from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Dict


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """
    Main persistent reply keyboard layout.
    """
    keyboard = [
        ["📦 Track Parcel", "🔍 Quick Status"],
        ["📋 My Parcels", "📮 Postcode & Offices"],
        ["💬 Feedback", "ℹ️ Help", "🏠 Home"]
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
        InlineKeyboardButton("🛑 Stop Tracking", callback_data=f"stop:{tracking_number}"),
        InlineKeyboardButton("🏠 Home", callback_data="go_home")
    ]

    buttons = [row1] + middle_rows + [bottom_row]
    return InlineKeyboardMarkup(buttons)


def get_my_parcels_inline_keyboard(trackings: List[Dict]) -> InlineKeyboardMarkup:
    """
    Inline buttons list for each parcel in /my, with Rename, Refresh All, Stop All, and Home options.
    """
    buttons = []
    for item in trackings:
        num = item["tracking_number"]
        label = item.get("label")
        btn_text = f"📦 {label} ({num})" if label else f"📦 {num}"
        buttons.append([
            InlineKeyboardButton(btn_text, callback_data=f"refresh:{num}"),
            InlineKeyboardButton("✏️", callback_data=f"rename:{num}"),
            InlineKeyboardButton("🛑", callback_data=f"stop:{num}")
        ])

    buttons.append([
        InlineKeyboardButton("🔄 Refresh All", callback_data="refresh_all"),
        InlineKeyboardButton("🛑 Stop All", callback_data="stop_all_confirm")
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

