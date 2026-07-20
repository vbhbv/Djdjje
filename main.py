import os
import sys
import re
import logging
import socket
import threading
import asyncio
from flask import Flask

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, constants
from telegram.ext import (
    ApplicationBuilder, 
    ContextTypes, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler, 
    filters
)

# استيراد وحدة التنزيل
from handlers.download import download_media_yt_dlp, load_links, save_links

# استيراد دالات لوحة التحكم وقاعدة البيانات من admin.py
from admin import (
    init_db, 
    register_user, 
    is_user_banned, 
    check_force_subscribe, 
    admin_panel_command, 
    handle_admin_callbacks, 
    handle_admin_inputs
)

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===============================================
#              0. الإعدادات والتهيئة
# ===============================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    logger.critical("❌ متغير البيئة BOT_TOKEN غير مضبوط!")

app = Flask(__name__)
lock_socket = None
bot_started = False

@app.route('/')
def home():
    return "Bot Status: Online | PostgreSQL & Admin Panel Active", 200

# ===============================================
#              1. الوساطة والتحقق (Middleware)
# ===============================================

async def pre_process_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    دالة مركزية تُنفذ عند كل تفاعل:
    - تسجيل/تحديث المستخدم في PostgreSQL.
    - التحقق من الحظر.
    - التحقق من الاشتراك الإجباري.
    """
    if not update.effective_user:
        return True

    user = update.effective_user
    username = user.username or f"User_{user.id}"

    # 1. تسجيل المستخدم في القاعدة
    await register_user(user.id, username)

    # 2. فحص الحظر
    if await is_user_banned(user.id):
        if update.message:
            await update.message.reply_text("🚫 **عذراً، حسابك محظور نهائياً من استخدام البوت.**", parse_mode='Markdown')
        return False

    # 3. فحص الاشتراك الإجباري
    is_subscribed = await check_force_subscribe(update, context)
    if not is_subscribed:
        return False

    return True

# ===============================================
#              2. الأوامر والمعالجات
# ===============================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /start للترحيب"""
    if not await pre_process_update(update, context):
        return

    first_name = update.effective_user.first_name
    await update.message.reply_text(
        f"<b>مرحباً بك {first_name}!</b> 👋\n\n"
        f"أنا بوت التحميل السريع من (تيك توك، إنستغرام، يوتيوب).\n"
        f"أرسل رابط الميديا مباشرة وسأعطيك خيارات التحميل صوت أو فيديو! 🚀",
        parse_mode=constants.ParseMode.HTML
    )

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة جميع الرسائل النصية والروابط"""
    if not await pre_process_update(update, context):
        return

    # معالجة المدخلات النصية الخاصة بالإدارة أولاً (إذاعة، حظر، إلخ)
    is_admin_input = await handle_admin_inputs(update, context)
    if is_admin_input:
        return

    text = update.message.text.strip() if update.message.text else ""
    if text.startswith('/'):
        return

    platform_key, platform_name = None, None
    
    # فحص الرابط عبر Regex
    if re.search(r'(?:tiktok\.com|vt\.tiktok\.com|vm\.tiktok\.com)', text, re.IGNORECASE):
        platform_key, platform_name = 'tiktok', 'تيك توك'
    elif re.search(r'instagram\.com/(?:p|reel|tv|stories)', text, re.IGNORECASE):
        platform_key, platform_name = 'instagram', 'إنستجرام'
    elif re.search(r'(?:youtube\.com|youtu\.be)', text, re.IGNORECASE):
        platform_key, platform_name = 'youtube', 'يوتيوب'
    
    if platform_key:
        msg_id_key = str(update.message.message_id) 
        links = load_links()
        links[msg_id_key] = text
        save_links(links) 
        
        keyboard = [
            [InlineKeyboardButton("تحميل فيديو 🎥", callback_data=f"final_dl_{platform_key}_video_{msg_id_key}")],
            [InlineKeyboardButton("تحويل إلى صوت 🎧 (MP3)", callback_data=f"final_dl_{platform_key}_audio_{msg_id_key}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"⚙️ <b>تم رصد رابط {platform_name}.</b>\nاختر الصيغة المطلوبة للتحميل:", 
            reply_markup=reply_markup, 
            parse_mode=constants.ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            "❌ <b>عذراً، هذا الرابط غير مدعوم!</b>\nأرسل رابطاً صحيحاً من TikTok أو Instagram أو YouTube.", 
            parse_mode=constants.ParseMode.HTML
        )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الأزرار التفاعلية (Inline Buttons)"""
    query = update.callback_query
    data = query.data

    # 1. أزرار لوحة تحكم الإدارة والتحقق من الاشتراك
    if data.startswith(('admin_', 'check_subscription')):
        await handle_admin_callbacks(update, context)
        return

    # 2. أزرار التنزيل للمستخدمين
    if not await pre_process_update(update, context):
        await query.answer()
        return

    if data.startswith('final_dl_'):
        await query.answer()
        parts = data.split('_')
        platform_key, media_type, msg_id_key = parts[2], parts[3], parts[4]
        
        links = load_links()
        user_url = links.pop(msg_id_key, None) 
        save_links(links) 
        
        if not user_url:
            await query.edit_message_text("❌ **انتهت صلاحية هذا الرابط. أرسله مجدداً.**", parse_mode='Markdown')
            return

        platforms = {'tiktok': 'تيك توك', 'instagram': 'إنستجرام', 'youtube': 'يوتيوب'}
        platform_name = platforms.get(platform_key, 'المنصة')
        download_as_mp3 = (media_type == 'audio')
        type_str = "صوت MP3 🎧" if download_as_mp3 else "فيديو 🎥"
        
        loading_msg = await query.edit_message_text(
            text=f"⚡ <b>جارٍ التحميل والمعالجة من {platform_name} ({type_str})...</b>\n⏳ يرجى الانتظار...", 
            parse_mode=constants.ParseMode.HTML
        )
        
        try:
            await download_media_yt_dlp(
                context.bot, 
                query.message.chat.id, 
                user_url, 
                platform_name, 
                loading_msg.message_id, 
                download_as_mp3
            )
        except Exception as e:
            logger.error(f"خطأ أثناء التحميل: {e}")
            err_short = str(e).split('\n')[0]
            await context.bot.send_message(
                query.message.chat.id, 
                f"❌ حدث خطأ أثناء التحميل: <b>{err_short}</b>", 
                parse_mode=constants.ParseMode.HTML
            )

# ===============================================
#   3. تشغيل البوت وإدارة السوكت (Single Instance)
# ===============================================

def run_single_application():
    """تهيئة الجداول وتشغيل الـ Polling مع الحماية من التكرار 409 وتجاوز أخطاء الـ Threading"""
    global lock_socket
    
    # حماية من فتح أكثر من Worker عبر Socket Lock
    try:
        lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        lock_socket.bind(('127.0.0.1', 47201))
    except socket.error:
        logger.info("ℹ️ يوجد Worker شغال حالياً، تم إيقاف المجرى الحالي لتفادي تعارض 409 Conflict.")
        return

    # إنشاء Async Loop جديد للثرد
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # إنشاء الجداول في PostgreSQL
    loop.run_until_complete(init_db())

    if not BOT_TOKEN:
        logger.critical("❌ لا يمكن تشغيل البوت بدون BOT_TOKEN")
        return

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # تسجيل الأوامر والمعالجات
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("admin", admin_panel_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    application.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("✅ تم قفل السوكت بنجاح. بدء استقبال التحديثات...")
    
    # تعطيل stop_signals لمنع استدعاء set_wakeup_fd خارج Main Thread
    application.run_polling(
        drop_pending_updates=True, 
        stop_signals=None, 
        close_loop=False
    )

def start_bot_in_background():
    """بدء تشغيل البوت في ثرد منفصل لمنع حظر Gunicorn"""
    global bot_started
    if not bot_started:
        bot_started = True
        bot_thread = threading.Thread(target=run_single_application, daemon=True)
        bot_thread.start()

# تشغيل البوت تلقائياً عند استدعاء الملف عبر Gunicorn
start_bot_in_background()

if __name__ == '__main__':
    # للتشغيل المحلي المباشر
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, use_reloader=False)
