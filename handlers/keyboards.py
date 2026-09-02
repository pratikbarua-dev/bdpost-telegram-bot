from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Dict


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """
    Main persistent reply keyboard layout.
    """
    keyboard = [
        ["📦 Track Parcel", "🔍 Quick Status"],
        ["📋 My Parcels", "🛑 Stop Tracking"],
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


def get_parcel_inline_keyboard(tracking_number: str) -> InlineKeyboardMarkup:
    """
    Inline action buttons for an individual parcel.
    """
    buttons = [
        [
            InlineKeyboardButton("🔄 Refresh Status", callback_data=f"refresh:{tracking_number}"),
            InlineKeyboardButton("🛑 Stop Tracking", callback_data=f"stop:{tracking_number}")
        ],
        [
            InlineKeyboardButton("🏠 Back to Home", callback_data="go_home")
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def get_my_parcels_inline_keyboard(trackings: List[Dict]) -> InlineKeyboardMarkup:
    """
    Inline buttons list for each parcel in /my, with Refresh All, Stop All, and Home options.
    """
    buttons = []
    for item in trackings:
        num = item["tracking_number"]
        buttons.append([
            InlineKeyboardButton(f"📦 {num}", callback_data=f"refresh:{num}"),
            InlineKeyboardButton("🛑 Stop", callback_data=f"stop:{num}")
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

