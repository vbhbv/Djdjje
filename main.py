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

# استيراد الوحدات الفرعية (تأكد من خلوها من أخطاء الـ Import)
from handlers.download import download_media_yt_dlp, load_links, save_links
from admin import (
    init_db, 
    register_user, 
    is_user_banned, 
    check_force_subscribe, 
    admin_panel_command, 
    handle_admin_callbacks, 
    handle_admin_inputs
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===============================================
#     تعريف كائن Flask ليعثر عليه Gunicorn
# ===============================================
app = Flask(__name__)
lock_socket = None
bot_started = False

BOT_TOKEN = os.environ.get("BOT_TOKEN")

@app.route('/')
def home():
    return "Bot status: Online", 200

# ===============================================
#              معالجات الأوامر والرسائل
# ===============================================

async def pre_process_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_user:
        return True

    user = update.effective_user
    username = user.username or f"User_{user.id}"

    await register_user(user.id, username)

    if await is_user_banned(user.id):
        if update.message:
            await update.message.reply_text("🚫 حسابك محظور من استخدام البوت.")
        return False

    is_subscribed = await check_force_subscribe(update, context)
    if not is_subscribed:
        return False

    return True

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await pre_process_update(update, context):
        return

    first_name = update.effective_user.first_name
    await update.message.reply_text(
        f"مرحباً بك {first_name}! 👋\nأرسل رابط الميديا للتحميل المباشر.",
        parse_mode=constants.ParseMode.HTML
    )

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await pre_process_update(update, context):
        return

    if await handle_admin_inputs(update, context):
        return

    text = update.message.text.strip() if update.message.text else ""
    if text.startswith('/'):
        return

    platform_key, platform_name = None, None
    
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
            f"⚙️ تم رصد رابط {platform_name}. اختر الصيغة:", 
            reply_markup=reply_markup, 
            parse_mode=constants.ParseMode.HTML
        )
    else:
        await update.message.reply_text("❌ رابط غير مدعوم.")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data.startswith(('admin_', 'check_subscription')):
        await handle_admin_callbacks(update, context)
        return

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
            await query.edit_message_text("❌ انتهت صلاحية الرابط.")
            return

        platforms = {'tiktok': 'تيك توك', 'instagram': 'إنستجرام', 'youtube': 'يوتيوب'}
        platform_name = platforms.get(platform_key, 'المنصة')
        download_as_mp3 = (media_type == 'audio')
        
        loading_msg = await query.edit_message_text(
            text=f"⚡ جارٍ التحميل من {platform_name}...", 
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
            await context.bot.send_message(
                query.message.chat.id, 
                f"❌ حدث خطأ أثناء التحميل: {str(e).split('\n')[0]}"
            )

# ===============================================
#          تشغيل البوت في الخلفية (Background)
# ===============================================

def run_single_application():
    global lock_socket
    
    # تفادي تكرار تشغيل البوت عند توزع الـ Workers
    try:
        lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        lock_socket.bind(('127.0.0.1', 47201))
    except socket.error:
        logger.info("ℹ️ Worker آخر يعمل بالفعل.")
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())

    if not BOT_TOKEN:
        logger.critical("❌ BOT_TOKEN غير موجود")
        return

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("admin", admin_panel_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    application.add_handler(CallbackQueryHandler(callback_handler))

    application.run_polling(
        drop_pending_updates=True, 
        stop_signals=None, 
        close_loop=False
    )

def start_bot_in_background():
    global bot_started
    if not bot_started:
        bot_started = True
        bot_thread = threading.Thread(target=run_single_application, daemon=True)
        bot_thread.start()

# بدء التثبيت عند استدعاء Gunicorn للملف
start_bot_in_background()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, use_reloader=False)
