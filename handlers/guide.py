"""
AliExpress Shopping & Tracking Mega Guide Handler.
Provides interactive in-depth advice on delivery methods (RedX vs Post Office),
tracking stages, customs/tax, post office procedures, and FAQs.
"""
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


def get_guide_main_keyboard() -> InlineKeyboardMarkup:
    """
    Main navigation menu for AliExpress & BD Post shopping guides.
    """
    buttons = [
        [
            InlineKeyboardButton("🚚 RedX vs পোস্ট অফিস", callback_data="guide:courier"),
            InlineKeyboardButton("⏳ ট্র্যাকিং টাইমলাইন", callback_data="guide:stages")
        ],
        [
            InlineKeyboardButton("📮 পোস্ট অফিস থেকে রিসিভ", callback_data="guide:postoffice"),
            InlineKeyboardButton("💰 কাস্টমস ও ট্যাক্স", callback_data="guide:customs")
        ],
        [
            InlineKeyboardButton("🎁 ওয়েলকাম ডিল ও রিফান্ড", callback_data="guide:deals"),
            InlineKeyboardButton("❓ সাধারণ প্রশ্ন (FAQ)", callback_data="guide:faq")
        ],
        [
            InlineKeyboardButton("🏠 মেইন মেনু", callback_data="go_home")
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def get_guide_back_keyboard() -> InlineKeyboardMarkup:
    """
    Back button to return to the Guide menu.
    """
    buttons = [
        [
            InlineKeyboardButton("🔙 গাইড মেনু", callback_data="guide:menu"),
            InlineKeyboardButton("🏠 মেইন মেনু", callback_data="go_home")
        ]
    ]
    return InlineKeyboardMarkup(buttons)


async def guide_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Command handler for /guide or tapping '💡 Shopping Guide'.
    """
    if not update.effective_user or not update.message:
        return

    text = (
        "💡 <b>আলিএক্সপ্রেস ও পোস্ট অফিস মেগা গাইড</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "আলিএক্সপ্রেস থেকে পণ্য অর্ডার করার পর কীভাবে দ্রুত হাতে পাবেন, "
        "কোন কুরিয়ারে আসবে, কাস্টমস ট্যাক্স কেমন হতে পারে এবং পোস্ট অফিসে এলে করণীয় কী — "
        "সব বিস্তারিত জানতে নিচের যেকোনো বিষয় নির্বাচন করুন:\n"
    )
    await update.message.reply_text(
        text,
        reply_markup=get_guide_main_keyboard(),
        parse_mode="HTML"
    )


async def guide_callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Routes callback queries starting with 'guide:'.
    """
    query = update.callback_query
    if not query or not query.data or not query.data.startswith("guide:"):
        return False

    await query.answer()
    topic = query.data.split(":", 1)[1]

    if topic == "menu":
        text = (
            "💡 <b>আলিএক্সপ্রেস ও পোস্ট অফিস মেগা গাইড</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "নিচের যেকোনো বিষয়ে বিস্তারিত জানতে বাটনে ট্যাপ করুন:\n"
        )
        await query.edit_message_text(
            text,
            reply_markup=get_guide_main_keyboard(),
            parse_mode="HTML"
        )
        return True

    elif topic == "courier":
        text = (
            "🚚 <b>RedX হোম ডেলিভারি নাকি পোস্ট অফিস?</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "<b>১. ট্র্যাকিং কোড দেখে বোঝার উপায়:</b>\n"
            "• শুরুতে <code>BR</code> এবং শেষে <code>MG</code> থাকলে (যেমন <code>BR0060...MG</code>): "
            "এটি সাধারণত <b>১০–১৩ দিনের মধ্যে লোকাল কুরিয়ারে (RedX) সরাসরি বাসায় হোম ডেলিভারি</b> হবে।\n"
            "• শুরুতে <code>BR</code> বাদে অন্য যা থাকবে (যেমন <code>UG...MV</code>, <code>LP...</code>, <code>AP...</code>): "
            "সেগুলো <b>লোকাল পোস্ট অফিসের মাধ্যমে</b> আসবে (সময় লাগে ২০–৩৫+ দিন)।\n\n"
            "<b>২. অর্ডার করার সময় কীভাবে নিশ্চিত হবেন?</b>\n"
            "প্রোডাক্ট পেইজে <b>Shipping</b> অপশনে ক্লিক করুন:\n"
            "• <b>AliExpress Standard / Selection Shipping:</b> থাকলে সেটি <code>BR****MG</code> দিয়ে রেডএক্সে দ্রুত আসবে।\n"
            "• <b>Super Economy Global / Saver Shipping:</b> থাকলে সেটি ডাকযোগে লোকাল পোস্ট অফিসে আসবে।\n\n"
            "💡 <i>পরামর্শ: কয়েক টাকা বেশি হলেও সবসময় Standard / Selection Shipping যুক্ত প্রোডাক্ট কিনুন!</i>"
        )
        await query.edit_message_text(text, reply_markup=get_guide_back_keyboard(), parse_mode="HTML")
        return True

    elif topic == "stages":
        text = (
            "⏳ <b>ট্র্যাকিং এর কোন স্টেজে কত সময় লাগে?</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "<b>১. কোন স্টেজে সবচেয়ে বেশি দেরি হয়?</b>\n"
            "• চায়নার লোকাল এয়ারপোর্ট থেকে ট্রানজিটের ফ্লাইট পেতে সবচেয়ে বেশি সময় লাগে (<b>৪–৬ দিন</b>)।\n"
            "• <i>Awaiting transit</i> থেকে <i>Awaiting flight</i> হতে সাধারণত ৪–৬ দিন সময় নেয়।\n"
            "• বাংলাদেশে ফ্লাইট ল্যান্ড করার পর কাস্টমস ক্লিয়ারেন্স পেতে লাগে আরও <b>২–৪ দিন</b>।\n\n"
            "<b>২. অ্যাপে কোন স্টেজের পর আর আপডেট পাবেন না?</b>\n"
            "• <b>RedX (BR...MG):</b> <i>Package out for delivery</i> মানে চাইনিজ লজিস্টিক ও কাস্টমস ক্লিয়ার হয়ে রেডএক্সকে পার্সেল বুঝিয়ে দেওয়া হয়েছে। সন্ধ্যা/রাতে রেডএক্স থেকে এসএমএস পাবেন এবং পরের ১–২ দিনে বাসায় ডেলিভারি পাবেন।\n"
            "• <b>পোস্ট অফিস (UG/LP/AP):</b> অ্যাপে <i>Your package arrived at local airport</i> এর পর অ্যাপের আপডেট বন্ধ হয়ে যায়। এরপর থেকে আমাদের বট দিয়ে বাংলাদেশ পোস্ট ট্র্যাকিং ফলো করতে হবে।"
        )
        await query.edit_message_text(text, reply_markup=get_guide_back_keyboard(), parse_mode="HTML")
        return True

    elif topic == "postoffice":
        text = (
            "📮 <b>পোস্ট অফিসে প্রোডাক্ট আসলে করণীয় কী?</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "<b>১. 'Item Not Found / আইটেম পাওয়া যায়নি' দেখালে:</b>\n"
            "• এর মানে পার্সেল এয়ারপোর্টে আসলেও এখনো কাস্টমস ছাড়িয়ে বাংলাদেশ পোস্টের কেন্দ্রীয় ডাকঘরে রিসিভ হয়নি। সচরাচর ৩–৫ দিন পর এন্ট্রি হয়। (শুক্র-শনিবার ডাকঘর বন্ধ থাকে)।\n\n"
            "<b>২. 'Delivered' দেখাচ্ছে কিন্তু বাসায় আসেনি?</b>\n"
            "⚠️ <b>জরুরি তথ্য:</b> বাংলাদেশ পোস্টের ট্র্যাকিং-এ <i>'Delivered'</i> মানে সরাসরি বাসায় পৌঁছানো নয়! "
            "পোস্ট অফিসে পার্সেল রিসিভ করে সিস্টেমে এন্ট্রি করলেও স্ট্যাটাস 'Delivered' হয়ে যায়। ভয় পাওয়ার কারণ নেই, সেদিন বা তার পরেরদিন পোস্টম্যান ডেলিভারি দেবে।\n\n"
            "<b>৩. পোস্ট অফিস থেকে নিজে সংগ্রহ:</b>\n"
            "ফোন না পেলে বা দেরি হলে আপনার এলাকার পোস্ট অফিসে গিয়ে <b>International Mail</b> বিভাগে গিয়ে ট্র্যাকিং নাম্বার ও ফোনে অর্ডার দেখালেই পার্সেল দিয়ে দিবে।\n\n"
            "<b>৪. 'Item wrongly directed forward' সমস্যা:</b>\n"
            "এটি কোনো ভুল নয়! জেলা প্রধান ডাকঘর (Head Office) হয়ে আপনার উপজেলা/লোকাল সাব-পোস্ট অফিসে আসার স্বাভাবিক রুট।"
        )
        await query.edit_message_text(text, reply_markup=get_guide_back_keyboard(), parse_mode="HTML")
        return True

    elif topic == "customs":
        text = (
            "💰 <b>কাস্টমস ট্যাক্স ও ঝুঁকিপূর্ণ পণ্য গাইড</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "<b>১. কোন কোন প্রোডাক্টে ট্যাক্স আসতে পারে?</b>\n"
            "ব্যক্তিগত ব্যবহারের বেশিরভাগ সাধারণ আইটেমে (১-২ পিস) কোনো ট্যাক্স আসে না। তবে নিচের আইটেমগুলোতে ট্যাক্স আসার সম্ভাবনা অনেক বেশি:\n"
            "• 🔋 যেকোনো ডিভাইসে বড় ব্যাটারি থাকলে বা পাওয়ারব্যাংক\n"
            "• 📱 মোবাইল ফোন, ট্যাবলেট বা হ্যান্ডহেল্ড গেমিং কনসোল\n"
            "• 🚁 ড্রোন, আরসি কার, রিমোট কন্ট্রোল খেলনা\n"
            "• 📷 ক্যামেরা, দামি স্মার্টওয়াচ বা উচ্চমূল্যের গ্যাজেট\n"
            "• 📦 একই পণ্য অনেক বেশি পরিমাণে একসাথে অর্ডার করলে\n\n"
            "<b>২. সাধারণত যেগুলোতে ট্যাক্স আসে না:</b>\n"
            "• মোবাইল ডিসপ্লে, কেসিং, কেবল, চার্জার\n"
            "• ছোট ইলেকট্রনিক্স পার্টস (ESP32, Arduino, সেন্সর, আইসি)\n"
            "• পোশাক, ব্যাগ, সাধারণ টুলস ও ঘরোয়া জিনিসপত্র।"
        )
        await query.edit_message_text(text, reply_markup=get_guide_back_keyboard(), parse_mode="HTML")
        return True

    elif topic == "deals":
        text = (
            "🎁 <b>ওয়েলকাম ডিল, রিফান্ড ও সতর্কতা</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "<b>১. পার্সেল খোলার সময় অবশ্য করণীয়:</b>\n"
            "⚠️ পার্সেল হাতে পাওয়ার পর <b>শুরু থেকে শেষ পর্যন্ত পরিষ্কার একটি আনবক্সিং ভিডিও</b> করে রাখুন। প্রোডাক্ট নষ্ট বা ভুল আসলে এই ভিডিও ছাড়া আলিএক্সপ্রেস কোনো রিফান্ড দেয় না!\n\n"
            "<b>২. রিটার্ন নাকি রিফান্ড?</b>\n"
            "বাংলাদেশ থেকে আলিএক্সপ্রেসে পণ্য ফেরত পাঠানো অত্যন্ত ব্যয়বহুল ও প্রায় অসম্ভব। তাই কোনো সমস্যা হলে Dispute ওপেন করার সময় সবসময় <b>'Refund Only'</b> সিলেক্ট করবেন (কখনোই 'Return & Refund' নয়)।\n\n"
            "<b>৩. ওয়েলকাম ডিল টিপস:</b>\n"
            "• নতুন অ্যাকাউন্টে কার্ডের চেয়ে ডিভাইস আইডি ও নেটওয়ার্ক বেশি ম্যাটার করে।\n"
            "• দুইটা প্রোডাক্টের ট্র্যাকিং আইডি একই দেখালে বুঝবেন Choice শিপিং-এ একসাথে মার্চ করে পাঠানো হয়েছে।"
        )
        await query.edit_message_text(text, reply_markup=get_guide_back_keyboard(), parse_mode="HTML")
        return True

    elif topic == "faq":
        text = (
            "❓ <b>আলিএক্সপ্রেস শপিং FAQ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "<b>প্র: ক্যাশ-অন ডেলিভারি (COD) আছে কি?</b>\n"
            "উ: না, অর্ডার করার সময় অনলাইন পেমেন্ট করতে হবে।\n\n"
            "<b>প্র: কোন কার্ড দিয়ে পেমেন্ট করা যায়?</b>\n"
            "উ: ডুয়েল কারেন্সিযুক্ত যেকোনো ব্যাংক কার্ড (MasterCard/Visa), অথবা RedotPay/পাসপোর্ট এনডোর্সড কার্ড।\n\n"
            "<b>প্র: প্রোডাক্ট হাতে পেতে কতদিন লাগে?</b>\n"
            "উ: RedX হলে সাধারণত ১০–১৩ দিন। পোস্ট অফিস হলে ১৫–৩০ দিন (কখনও ৩৫ দিন)।\n\n"
            "<b>প্র: একই অর্ডারে আলাদা ট্র্যাকিং কোড কেন?</b>\n"
            "উ: ভিন্ন ভিন্ন সেলার বা শিপিং মেথড (একটি Standard, আরেকটি Saver Economy) হলে আলাদা পার্সেল হিসেবে আসে।"
        )
        await query.edit_message_text(text, reply_markup=get_guide_back_keyboard(), parse_mode="HTML")
        return True

    return False
