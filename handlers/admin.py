import asyncio
import datetime
import html
import logging
from typing import Dict, Any, List, Optional
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

import config
from database.db import Database
from handlers.cleanup import cleanup_previous_messages
from bdpost.validator import validate_and_normalize_tracking_number
from bdpost.formatter import format_tracking_chain
from bdpost.client import track as track_bdpost
from bdpost.parser import parse_tracking_response as parse_bdpost
from cainiao.client import track as track_cainiao
from cainiao.parser import parse_tracking_response as parse_cainiao
from track17.client import track as track_17track
from track17.parser import parse_tracking_response as parse_17track

logger = logging.getLogger(__name__)


def is_admin(user_id: int) -> bool:
    return user_id == config.ADMIN_CHAT_ID


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Main entrypoint for /admin and /stats commands.
    Strictly verifies admin permission.
    """
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id
    if not is_admin(user_id):
        # Non-admin user gets no response or standard message
        logger.warning("Unauthorized /admin attempt by user %d", user_id)
        return

    await cleanup_previous_messages(update, context)
    args = context.args or []
    db: Database = context.bot_data["db"]

    if not args or args[0].lower() in ["stats", "dashboard", "home"]:
        await show_admin_dashboard(update, context, db)
        return

    subcmd = args[0].lower()

    if subcmd == "users":
        await show_admin_users_list(update, context, db, offset=0)
    elif subcmd == "user" and len(args) >= 2:
        await show_admin_user_profile(update, context, db, identifier=args[1])
    elif subcmd in ["parcel", "shipment"] and len(args) >= 2:
        await show_admin_parcel_details(update, context, db, tracking_number=args[1])
    elif subcmd == "add" and len(args) >= 3:
        await handle_admin_add_parcel(update, context, db, args[1], args[2], " ".join(args[3:]) if len(args) > 3 else None)
    elif subcmd == "remove" and len(args) >= 3:
        await handle_admin_remove_parcel(update, context, db, args[1], args[2])
    elif subcmd == "rename" and len(args) >= 4:
        await handle_admin_rename_parcel(update, context, db, args[1], args[2], " ".join(args[3:]))
    elif subcmd == "purge" and len(args) >= 2:
        await handle_admin_purge_user(update, context, db, args[1])
    elif subcmd == "ban" and len(args) >= 2:
        await handle_admin_ban_user(update, context, db, args[1], ban=True)
    elif subcmd == "unban" and len(args) >= 2:
        await handle_admin_ban_user(update, context, db, args[1], ban=False)
    elif subcmd == "poll":
        await handle_admin_trigger_poll(update, context, db)
    elif subcmd == "test":
        await handle_admin_test_connections(update, context)
    elif subcmd == "broadcast" and len(args) >= 2:
        await handle_admin_broadcast(update, context, db, " ".join(args[1:]))
    elif subcmd == "handover" and len(args) >= 2:
        await handle_admin_force_state(update, context, db, args[1], state="handover")
    elif subcmd == "deliver" and len(args) >= 2:
        await handle_admin_force_state(update, context, db, args[1], state="deliver")
    elif subcmd == "delete" and len(args) >= 2:
        await handle_admin_delete_parcel(update, context, db, args[1])
    else:
        await update.message.reply_text(
            "📖 <b>Admin Command Reference:</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "• <code>/admin</code> — Open Dashboard\n"
            "• <code>/admin users</code> — View all registered users\n"
            "• <code>/admin user &lt;user_id|@username&gt;</code> — View user parcels & details\n"
            "• <code>/admin parcel &lt;tracking_number&gt;</code> — Deep inspect parcel chain & subscribers\n"
            "• <code>/admin add &lt;user_id&gt; &lt;tracking_num&gt; [label]</code> — Add parcel for user\n"
            "• <code>/admin remove &lt;user_id&gt; &lt;tracking_num&gt;</code> — Remove user parcel\n"
            "• <code>/admin rename &lt;user_id&gt; &lt;tracking_num&gt; &lt;label&gt;</code> — Rename parcel\n"
            "• <code>/admin purge &lt;user_id&gt;</code> — Stop all trackings for user\n"
            "• <code>/admin ban &lt;user_id&gt;</code> / <code>unban</code> — Moderate user\n"
            "• <code>/admin poll</code> — Trigger immediate background poll\n"
            "• <code>/admin test</code> — Test Cainiao/17TRACK/BDPost connections\n"
            "• <code>/admin broadcast &lt;message&gt;</code> — Send global broadcast\n"
            "• <code>/admin handover &lt;tracking_num&gt;</code> — Force handover state\n"
            "• <code>/admin deliver &lt;tracking_num&gt;</code> — Force delivered state\n"
            "• <code>/admin delete &lt;tracking_num&gt;</code> — Delete parcel globally\n"
            "━━━━━━━━━━━━━━━━━━━━",
            parse_mode="HTML"
        )


# ---------------------------------------------------------------------
# Dashboard & Views
# ---------------------------------------------------------------------
async def show_admin_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE, db: Database, edit: bool = False) -> None:
    stats = db.get_system_stats()
    proxy_info = f"<code>{html.escape(config.CF_PROXY_URL)}</code>" if config.CF_PROXY_URL else "<i>Direct (No Proxy)</i>"

    text = (
        "👑 <b>Admin Control Center</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 <b>Total Users:</b> <code>{stats['total_users']}</code>\n"
        f"📦 <b>Active Shipments:</b> <code>{stats['active_shipments']}</code>\n"
        f"🇧🇩 <b>Handover Reached:</b> <code>{stats['handover_shipments']}</code>\n"
        f"🎉 <b>Delivered Parcels:</b> <code>{stats['delivered_shipments']}</code>\n"
        f"📊 <b>Total Shipments in DB:</b> <code>{stats['total_shipments']}</code>\n"
        f"🚫 <b>Banned Users:</b> <code>{stats['banned_users']}</code>\n\n"
        f"⏱️ <b>Polling Interval:</b> Every <code>{config.POLL_INTERVAL // 60}</code> mins\n"
        f"🌐 <b>Cloudflare Proxy:</b> {proxy_info}\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

    keyboard = [
        [
            InlineKeyboardButton("👥 User Management", callback_data="admin_users:0"),
            InlineKeyboardButton("📦 All Parcels", callback_data="admin_parcels:0")
        ],
        [
            InlineKeyboardButton("🔄 Trigger Poll Now", callback_data="admin_poll"),
            InlineKeyboardButton("🌐 Test Connections", callback_data="admin_test")
        ],
        [
            InlineKeyboardButton("🔄 Refresh Stats", callback_data="admin_stats")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
    elif update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    elif update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")


async def show_admin_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE, db: Database, offset: int = 0, edit: bool = False) -> None:
    limit = 10
    users = db.get_all_users_admin(limit=limit, offset=offset)
    stats = db.get_system_stats()
    total_users = stats["total_users"]

    lines = [
        f"👥 <b>Registered Users ({total_users} total)</b>",
        "━━━━━━━━━━━━━━━━━━━━"
    ]

    if not users:
        lines.append("<i>No users found in database.</i>")
    else:
        for idx, u in enumerate(users, start=offset + 1):
            uid = u["telegram_id"]
            uname = f"@{u['username']}" if u.get("username") else "No username"
            fname = html.escape(u.get("full_name") or "User")
            active_p = u.get("active_parcels", 0)
            banned_tag = " [🚫 BANNED]" if u.get("is_banned") == 1 else ""
            lines.append(f"<b>{idx}.</b> <code>{uid}</code> — {fname} ({uname}){banned_tag}")
            lines.append(f"   📦 Active: <b>{active_p}</b> | Total: <b>{u.get('total_parcels', 0)}</b>")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <i>Tap a user below or type <code>/admin user &lt;id&gt;</code> to view parcels</i>")

    keyboard = []
    # Add direct buttons for top users on current page
    row = []
    for u in users[:6]:
        uid = u["telegram_id"]
        row.append(InlineKeyboardButton(f"👤 {uid}", callback_data=f"admin_user:{uid}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    nav_row = []
    if offset > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"admin_users:{max(0, offset - limit)}"))
    if offset + limit < total_users:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"admin_users:{offset + limit}"))
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("🏠 Back to Admin Dashboard", callback_data="admin_stats")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = "\n".join(lines)
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
    elif update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    elif update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")


async def show_admin_user_profile(update: Update, context: ContextTypes.DEFAULT_TYPE, db: Database, identifier: str, edit: bool = False) -> None:
    user = db.get_user_admin_profile(identifier)
    if not user:
        msg = f"❌ User <code>{html.escape(identifier)}</code> not found in database."
        if edit and update.callback_query:
            await update.callback_query.edit_message_text(msg, parse_mode="HTML")
        elif update.message:
            await update.message.reply_text(msg, parse_mode="HTML")
        return

    uid = user["telegram_id"]
    uname = f"@{user['username']}" if user.get("username") else "No username"
    fname = html.escape(user.get("full_name") or "User")
    is_banned = user.get("is_banned") == 1
    parcels = user.get("parcels", [])

    lines = [
        "👑 <b>Admin: User Profile</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"👤 <b>Name:</b> {fname}",
        f"🆔 <b>Telegram ID:</b> <code>{uid}</code>",
        f"🔗 <b>Username:</b> {uname}",
        f"📅 <b>Joined:</b> {user.get('created_at', 'N/A')[:19]}",
        f"🛡️ <b>Status:</b> {'🚫 <b>BANNED</b>' if is_banned else '✅ Active'}",
        f"📦 <b>Tracked Parcels ({len(parcels)}):</b>",
        ""
    ]

    if not parcels:
        lines.append("<i>No parcels tracked by this user.</i>")
    else:
        for idx, p in enumerate(parcels, start=1):
            pnum = p["primary_tracking_number"]
            lbl = f"🏷️ <b>{html.escape(p['label'])}</b> — " if p.get("label") else ""
            status = "🎉 Delivered" if p.get("is_delivered") == 1 else ("🇧🇩 Handover" if p.get("handover_detected") == 1 else "🚚 In Transit")
            sub_state = " [Subscribed]" if p.get("is_subscribed") == 1 else " [Stopped]"
            chain = p.get("tracking_chain", [])
            chain_str = f" (Chain: {' → '.join(c['tracking_number'] for c in chain)})" if len(chain) > 1 else ""
            lines.append(f"{idx}. {lbl}<code>{pnum}</code> ({status}){sub_state}{chain_str}")

    lines.append("━━━━━━━━━━━━━━━━━━━━")

    keyboard = [
        [
            InlineKeyboardButton("🛑 Purge All Trackings", callback_data=f"admin_purge:{uid}"),
            InlineKeyboardButton("Unban" if is_banned else "🚫 Ban User", callback_data=f"admin_toggleban:{uid}")
        ],
        [
            InlineKeyboardButton("👥 Back to Users", callback_data="admin_users:0"),
            InlineKeyboardButton("🏠 Dashboard", callback_data="admin_stats")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = "\n".join(lines)
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
    elif update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")


async def show_admin_parcel_details(update: Update, context: ContextTypes.DEFAULT_TYPE, db: Database, tracking_number: str, edit: bool = False) -> None:
    cleaned_num = tracking_number.strip().upper()
    shipment = db.get_shipment_by_tracking_number(cleaned_num)

    if not shipment:
        msg = f"❌ Shipment <code>{html.escape(cleaned_num)}</code> not found in database."
        if edit and update.callback_query:
            await update.callback_query.edit_message_text(msg, parse_mode="HTML")
        elif update.message:
            await update.message.reply_text(msg, parse_mode="HTML")
        return

    sid = shipment["id"]
    p_num = shipment["primary_tracking_number"]
    chain = db.get_tracking_chain_numbers(sid)
    subscribers = db.get_shipment_subscribers(sid)
    latest_event = db.get_latest_event_for_tracking(p_num)

    lines = [
        "👑 <b>Admin: Global Shipment Inspector</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🔢 <b>Primary Number:</b> <code>{p_num}</code>",
        f"🆔 <b>Shipment ID:</b> <code>{sid}</code>",
    ]

    if shipment.get("local_tracking_number"):
        lines.append(f"🇧🇩 <b>Local Number:</b> <code>{shipment['local_tracking_number']}</code>")

    chain_formatted = format_tracking_chain(chain)
    if chain_formatted:
        lines.append(chain_formatted)

    lines.append("")
    lines.append("⚙️ <b>Polling State:</b>")
    lines.append(f"• Cainiao Polling: {'🟢 Active' if shipment.get('cainiao_enabled') == 1 else '🔴 Disabled'}")
    lines.append(f"• BD Post Polling: {'🟢 Active' if shipment.get('bdpost_enabled') == 1 else '🔴 Disabled'}")
    lines.append(f"• Handover Reached: {'✅ Yes' if shipment.get('handover_detected') == 1 else '⏳ No'}")
    lines.append(f"• Delivered: {'🎉 Yes' if shipment.get('is_delivered') == 1 else '⏳ No'}")
    lines.append(f"• Last Checked: <code>{shipment.get('last_checked_at', 'Never')[:19]}</code>")

    if latest_event:
        lines.append("")
        lines.append(f"📌 <b>Latest Status:</b> {html.escape(latest_event.get('status', 'N/A'))}")
        if latest_event.get("location"):
            lines.append(f"📍 <b>Location:</b> {html.escape(latest_event.get('location'))}")
        lines.append(f"🕐 <b>Date:</b> {html.escape(latest_event.get('event_date', 'N/A'))}")

    lines.append("")
    lines.append(f"👥 <b>Active Subscribers ({len(subscribers)}):</b>")
    if not subscribers:
        lines.append("<i>No active subscribers.</i>")
    else:
        for sub in subscribers:
            uid = sub["telegram_id"]
            lbl = f" [🏷️ {html.escape(sub['label'])}]" if sub.get("label") else ""
            lines.append(f"• <code>{uid}</code>{lbl}")

    lines.append("━━━━━━━━━━━━━━━━━━━━")

    keyboard = [
        [
            InlineKeyboardButton("🇧🇩 Force Handover", callback_data=f"admin_handover:{sid}"),
            InlineKeyboardButton("🎉 Force Deliver", callback_data=f"admin_deliver:{sid}")
        ],
        [
            InlineKeyboardButton("🗑️ Delete Shipment", callback_data=f"admin_delete:{sid}"),
            InlineKeyboardButton("📦 All Parcels", callback_data="admin_parcels:0")
        ],
        [
            InlineKeyboardButton("🏠 Admin Dashboard", callback_data="admin_stats")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = "\n".join(lines)
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
    elif update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")


async def show_admin_parcels_list(update: Update, context: ContextTypes.DEFAULT_TYPE, db: Database, offset: int = 0, edit: bool = False) -> None:
    limit = 10
    shipments = db.get_all_shipments_admin(limit=limit, offset=offset)
    stats = db.get_system_stats()
    total_parcels = stats["total_shipments"]

    lines = [
        f"📦 <b>Global Parcels ({total_parcels} total)</b>",
        "━━━━━━━━━━━━━━━━━━━━"
    ]

    if not shipments:
        lines.append("<i>No shipments recorded in database.</i>")
    else:
        for idx, s in enumerate(shipments, start=offset + 1):
            pnum = s["primary_tracking_number"]
            subs_cnt = s.get("subscribers_count", 0)
            status = "🎉 Delivered" if s.get("is_delivered") == 1 else ("🇧🇩 Handover" if s.get("handover_detected") == 1 else "🚚 In Transit")
            lines.append(f"<b>{idx}.</b> <code>{pnum}</code> ({status})")
            lines.append(f"   👥 Subscribers: <b>{subs_cnt}</b> | Updated: <code>{s.get('updated_at', '')[:19]}</code>")

    lines.append("━━━━━━━━━━━━━━━━━━━━")

    keyboard = []
    row = []
    for s in shipments[:6]:
        pnum = s["primary_tracking_number"]
        row.append(InlineKeyboardButton(f"📦 {pnum[:14]}", callback_data=f"admin_parcel:{pnum}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    nav_row = []
    if offset > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"admin_parcels:{max(0, offset - limit)}"))
    if offset + limit < total_parcels:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"admin_parcels:{offset + limit}"))
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("🏠 Back to Admin Dashboard", callback_data="admin_stats")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = "\n".join(lines)
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
    elif update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")


# ---------------------------------------------------------------------
# Action Handlers
# ---------------------------------------------------------------------
async def handle_admin_add_parcel(update: Update, context: ContextTypes.DEFAULT_TYPE, db: Database, user_id_str: str, tracking_number: str, label: Optional[str]) -> None:
    if not user_id_str.isdigit():
        await update.message.reply_text("❌ User ID must be a numeric Telegram ID.", parse_mode="HTML")
        return
    uid = int(user_id_str)
    cleaned = validate_and_normalize_tracking_number(tracking_number)
    if not cleaned:
        await update.message.reply_text(f"❌ Invalid tracking number format: <code>{html.escape(tracking_number)}</code>", parse_mode="HTML")
        return

    db.get_or_create_user(uid)
    sid = db.get_or_create_shipment(cleaned, telegram_id=uid, label=label)
    await update.message.reply_text(
        f"✅ <b>Successfully subscribed user</b> <code>{uid}</code> to <code>{cleaned}</code>"
        f"{f' with label <b>{html.escape(label)}</b>' if label else ''} (Shipment ID: <code>{sid}</code>).",
        parse_mode="HTML"
    )


async def handle_admin_remove_parcel(update: Update, context: ContextTypes.DEFAULT_TYPE, db: Database, user_id_str: str, tracking_number: str) -> None:
    if not user_id_str.isdigit():
        await update.message.reply_text("❌ User ID must be a numeric Telegram ID.", parse_mode="HTML")
        return
    uid = int(user_id_str)
    cleaned = validate_and_normalize_tracking_number(tracking_number) or tracking_number.strip().upper()
    stopped = db.stop_shipment_tracking(uid, cleaned)
    if stopped:
        await update.message.reply_text(f"✅ Stopped tracking <code>{cleaned}</code> for user <code>{uid}</code>.", parse_mode="HTML")
    else:
        await update.message.reply_text(f"⚠️ User <code>{uid}</code> was not actively tracking <code>{cleaned}</code>.", parse_mode="HTML")


async def handle_admin_rename_parcel(update: Update, context: ContextTypes.DEFAULT_TYPE, db: Database, user_id_str: str, tracking_number: str, new_label: str) -> None:
    if not user_id_str.isdigit():
        await update.message.reply_text("❌ User ID must be a numeric Telegram ID.", parse_mode="HTML")
        return
    uid = int(user_id_str)
    cleaned = validate_and_normalize_tracking_number(tracking_number) or tracking_number.strip().upper()
    label_to_set = None if new_label.lower() in ["none", "clear", "remove"] else new_label
    renamed = db.set_shipment_label(uid, cleaned, label_to_set)
    if renamed:
        await update.message.reply_text(f"✅ Renamed parcel <code>{cleaned}</code> for user <code>{uid}</code> to: <b>{html.escape(new_label)}</b>", parse_mode="HTML")
    else:
        await update.message.reply_text(f"⚠️ Could not rename <code>{cleaned}</code> for user <code>{uid}</code>.", parse_mode="HTML")


async def handle_admin_purge_user(update: Update, context: ContextTypes.DEFAULT_TYPE, db: Database, user_id_str: str) -> None:
    if not user_id_str.isdigit():
        await update.message.reply_text("❌ User ID must be a numeric Telegram ID.", parse_mode="HTML")
        return
    uid = int(user_id_str)
    count = db.stop_all_user_shipments(uid)
    await update.message.reply_text(f"🛑 Stopped <b>{count}</b> active tracking(s) for user <code>{uid}</code>.", parse_mode="HTML")


async def handle_admin_ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE, db: Database, user_id_str: str, ban: bool) -> None:
    if not user_id_str.isdigit():
        await update.message.reply_text("❌ User ID must be a numeric Telegram ID.", parse_mode="HTML")
        return
    uid = int(user_id_str)
    db.set_user_ban_status(uid, is_banned=ban)
    action = "Banned 🚫" if ban else "Unbanned ✅"
    await update.message.reply_text(f"🛡️ User <code>{uid}</code> has been <b>{action}</b>.", parse_mode="HTML")


async def handle_admin_force_state(update: Update, context: ContextTypes.DEFAULT_TYPE, db: Database, target: str, state: str) -> None:
    shipment = None
    if target.isdigit():
        shipment = db.get_shipment(int(target))
    if not shipment:
        shipment = db.get_shipment_by_tracking_number(target)

    if not shipment:
        await update.message.reply_text(f"❌ Shipment <code>{html.escape(target)}</code> not found.", parse_mode="HTML")
        return

    sid = shipment["id"]
    pnum = shipment["primary_tracking_number"]

    if state == "handover":
        db.admin_force_shipment_state(sid, cainiao_enabled=0, bdpost_enabled=1, handover_detected=1)
        await update.message.reply_text(f"🇧🇩 Shipment <code>{pnum}</code> marked as <b>Handover Confirmed</b>. International polling stopped.", parse_mode="HTML")
    elif state == "deliver":
        db.admin_force_shipment_state(sid, cainiao_enabled=0, bdpost_enabled=0, is_delivered=1)
        await update.message.reply_text(f"🎉 Shipment <code>{pnum}</code> marked as <b>Delivered</b>. All polling stopped.", parse_mode="HTML")


async def handle_admin_delete_parcel(update: Update, context: ContextTypes.DEFAULT_TYPE, db: Database, target: str) -> None:
    shipment = None
    if target.isdigit():
        shipment = db.get_shipment(int(target))
    if not shipment:
        shipment = db.get_shipment_by_tracking_number(target)

    if not shipment:
        await update.message.reply_text(f"❌ Shipment <code>{html.escape(target)}</code> not found.", parse_mode="HTML")
        return

    sid = shipment["id"]
    pnum = shipment["primary_tracking_number"]
    db.admin_delete_shipment(sid)
    await update.message.reply_text(f"🗑️ Shipment <code>{pnum}</code> (ID: <code>{sid}</code>) and its events were <b>completely deleted</b>.", parse_mode="HTML")


async def handle_admin_trigger_poll(update: Update, context: ContextTypes.DEFAULT_TYPE, db: Database) -> None:
    from scheduler.checker import check_all_trackings
    status_msg = await (update.message.reply_text("⏳ Triggering background scheduler check...") if update.message else update.callback_query.message.reply_text("⏳ Triggering background scheduler check..."))
    try:
        await check_all_trackings(context)
        await status_msg.edit_text("✅ <b>Background scheduler check completed successfully!</b>", parse_mode="HTML")
    except Exception as e:
        logger.error("Admin trigger poll error: %s", e, exc_info=True)
        await status_msg.edit_text(f"❌ Error during poll execution: {e}", parse_mode="HTML")


async def handle_admin_test_connections(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    status_msg = await (update.message.reply_text("🌐 Testing connections to tracking providers...") if update.message else update.callback_query.message.reply_text("🌐 Testing connections to tracking providers..."))
    test_number = "UG251781108MV"
    results = []

    # 1. Cainiao test
    t0 = datetime.datetime.now()
    try:
        c_data = await track_cainiao(test_number)
        c_events = parse_cainiao(c_data)
        elapsed = (datetime.datetime.now() - t0).total_seconds()
        results.append(f"🟢 <b>Cainiao:</b> OK ({len(c_events)} events, {elapsed:.2f}s)")
    except Exception as e:
        results.append(f"🔴 <b>Cainiao:</b> Failed ({e})")

    # 2. 17TRACK test
    t0 = datetime.datetime.now()
    try:
        t_data = await track_17track(test_number)
        t_events = parse_17track(t_data, test_number)
        elapsed = (datetime.datetime.now() - t0).total_seconds()
        results.append(f"🟢 <b>17TRACK:</b> OK ({len(t_events)} events, {elapsed:.2f}s)")
    except Exception as e:
        results.append(f"🔴 <b>17TRACK:</b> Failed ({e})")

    # 3. Bangladesh Post test
    t0 = datetime.datetime.now()
    try:
        b_html = await track_bdpost(test_number)
        b_events = parse_bdpost(b_html)
        elapsed = (datetime.datetime.now() - t0).total_seconds()
        results.append(f"🟢 <b>Bangladesh Post:</b> OK ({len(b_events)} events, {elapsed:.2f}s)")
    except Exception as e:
        results.append(f"🔴 <b>Bangladesh Post:</b> Failed ({e})")

    proxy_info = f"<code>{html.escape(config.CF_PROXY_URL)}</code>" if config.CF_PROXY_URL else "<i>Direct (No Proxy)</i>"
    report = (
        "🌐 <b>Provider Connectivity Diagnostic</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 <b>Cloudflare Proxy:</b> {proxy_info}\n"
        f"🔢 <b>Test Parcel:</b> <code>{test_number}</code>\n\n" +
        "\n".join(results) +
        "\n━━━━━━━━━━━━━━━━━━━━"
    )
    await status_msg.edit_text(report, parse_mode="HTML")


async def handle_admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, db: Database, broadcast_text: str) -> None:
    uids = db.get_all_registered_telegram_ids()
    total = len(uids)
    if not total:
        await update.message.reply_text("No users registered to broadcast to.", parse_mode="HTML")
        return

    progress = await update.message.reply_text(f"📢 Starting broadcast to {total} users...", parse_mode="HTML")
    success_cnt = 0
    failed_cnt = 0

    msg = (
        "📢 <b>System Announcement</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{html.escape(broadcast_text.strip())}\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

    for uid in uids:
        try:
            await context.bot.send_message(chat_id=uid, text=msg, parse_mode="HTML")
            success_cnt += 1
        except Exception:
            failed_cnt += 1
        await asyncio.sleep(0.05)

    await progress.edit_text(
        f"✅ <b>Broadcast Completed!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📤 Total Users: <b>{total}</b>\n"
        f"🟢 Delivered: <b>{success_cnt}</b>\n"
        f"🔴 Failed/Blocked: <b>{failed_cnt}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━",
        parse_mode="HTML"
    )


# ---------------------------------------------------------------------
# Callback Router for Admin Buttons
# ---------------------------------------------------------------------
async def admin_callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Handles inline callback queries starting with admin_.
    Returns True if handled.
    """
    query = update.callback_query
    if not query or not update.effective_user:
        return False

    if not is_admin(update.effective_user.id):
        return False

    data = query.data
    if not data.startswith("admin_"):
        return False

    await query.answer()
    db: Database = context.bot_data["db"]

    if data == "admin_stats":
        await show_admin_dashboard(update, context, db, edit=True)
    elif data.startswith("admin_users:"):
        offset = int(data.split(":", 1)[1])
        await show_admin_users_list(update, context, db, offset=offset, edit=True)
    elif data.startswith("admin_user:"):
        uid = data.split(":", 1)[1]
        await show_admin_user_profile(update, context, db, identifier=uid, edit=True)
    elif data.startswith("admin_parcels:"):
        offset = int(data.split(":", 1)[1])
        await show_admin_parcels_list(update, context, db, offset=offset, edit=True)
    elif data.startswith("admin_parcel:"):
        pnum = data.split(":", 1)[1]
        await show_admin_parcel_details(update, context, db, tracking_number=pnum, edit=True)
    elif data == "admin_poll":
        await handle_admin_trigger_poll(update, context, db)
    elif data == "admin_test":
        await handle_admin_test_connections(update, context)
    elif data.startswith("admin_purge:"):
        uid = int(data.split(":", 1)[1])
        db.stop_all_user_shipments(uid)
        await show_admin_user_profile(update, context, db, identifier=str(uid), edit=True)
    elif data.startswith("admin_toggleban:"):
        uid = int(data.split(":", 1)[1])
        current_banned = db.is_user_banned(uid)
        db.set_user_ban_status(uid, not current_banned)
        await show_admin_user_profile(update, context, db, identifier=str(uid), edit=True)
    elif data.startswith("admin_handover:"):
        sid = int(data.split(":", 1)[1])
        db.admin_force_shipment_state(sid, cainiao_enabled=0, bdpost_enabled=1, handover_detected=1)
        shipment = db.get_shipment(sid)
        if shipment:
            await show_admin_parcel_details(update, context, db, tracking_number=shipment["primary_tracking_number"], edit=True)
    elif data.startswith("admin_deliver:"):
        sid = int(data.split(":", 1)[1])
        db.admin_force_shipment_state(sid, cainiao_enabled=0, bdpost_enabled=0, is_delivered=1)
        shipment = db.get_shipment(sid)
        if shipment:
            await show_admin_parcel_details(update, context, db, tracking_number=shipment["primary_tracking_number"], edit=True)
    elif data.startswith("admin_delete:"):
        sid = int(data.split(":", 1)[1])
        db.admin_delete_shipment(sid)
        await show_admin_parcels_list(update, context, db, offset=0, edit=True)

    return True
