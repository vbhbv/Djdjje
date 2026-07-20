import os
import sys
import re
import json
import threading
import time
import socket
from flask import Flask
import telebot
from telebot import types

# 🚨 استيراد جميع الدوال من ملف التحميل الخارجي
from handlers.download import download_media_yt_dlp, load_links, save_links

# ===============================================
#              0. الإعدادات والثوابت والتهيئة
# ===============================================

BOT_TOKEN = "8913222700:AAETkljjyRrGf-NllmznlCLdprzUQv37Xww"
CHANNEL_USERNAME = "@SuPeRx1"
DEVELOPER_USER_ID = "1315011160"

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

lock_socket = None

@app.route('/')
def home():
    return "Bot status: Active & Running Single Instance Auto-Detect Mode.", 200

# ===============================================
#              1. معالجة الأوامر الرئيسية (الواجهة)
# ===============================================

@bot.message_handler(commands=["start"])
def send_welcome(message):
    first_name = message.from_user.first_name if message.from_user else "صديقنا"
    
    bot.send_message(
        message.chat.id,
        f"""<b>مرحباً بك {first_name}!</b> 👋
أنا بوت التحميل الشامل والسريع.

🚀 <b>طريقة الاستخدام:</b>
أرسل رابط الفيديو مباشرة في الشات (تيك توك، إنستجرام، أو يوتيوب).
سأقوم بالتعرف على المنصة ثم تخييرك بين تحميله كـ <b>فيديو 🎥</b> أو تحويله إلى <b>صوت MP3 🎧</b>!""",
        parse_mode='HTML'
    )

# ===============================================
#        2. الدالة الذكية: التعرف التلقائي على الروابط
# ===============================================

@bot.message_handler(func=lambda m: True)
def auto_detect_and_process_link(message):
    user_url = message.text.strip() if message.text else ""
    
    if user_url.startswith('/'):
        return

    # 🔍 اقتناص نوع المنصة تلقائياً عبر تعابير ريجكس (Regex)
    if re.search(r'(?:tiktok\.com|vt\.tiktok\.com|vm\.tiktok\.com)', user_url, re.IGNORECASE):
        platform_key = 'tiktok'
        platform_name = 'تيك توك'
    elif re.search(r'instagram\.com/(?:p|reel|tv|stories)', user_url, re.IGNORECASE):
        platform_key = 'instagram'
        platform_name = 'إنستجرام'
    elif re.search(r'(?:youtube\.com|youtu\.be)', user_url, re.IGNORECASE):
        platform_key = 'youtube'
        platform_name = 'يوتيوب'
    else:
        bot.send_message(
            message.chat.id, 
            "❌ <b>عذراً، هذا الرابط أو النص غير مدعوم!</b>\nيرجى إرسال رابط فيديو صحيح من منصات: TikTok أو Instagram أو YouTube.", 
            parse_mode='HTML'
        )
        return

    try:
        # 🎯 عرض خيارات الصيغة (فيديو / صوت) لجميع المنصات المدعومة
        message_id_key = str(message.message_id) 
        links = load_links()
        links[message_id_key] = user_url
        save_links(links) 
        
        markup = types.InlineKeyboardMarkup()
        vid_btn = types.InlineKeyboardButton("تحميل فيديو 🎥", callback_data=f"final_dl_{platform_key}_video_{message_id_key}")
        aud_btn = types.InlineKeyboardButton("تحويل إلى صوت 🎧 (MP3)", callback_data=f"final_dl_{platform_key}_audio_{message_id_key}")
        markup.add(vid_btn, aud_btn)
        
        bot.send_message(
            message.chat.id, 
            f"⚙️ <b>تم رصد رابط {platform_name}.</b>\nاختر الصيغة التي تفضلها لبدء التحميل:", 
            reply_markup=markup, 
            parse_mode='HTML'
        )
            
    except Exception as e:
        print(f"❌ خطأ في المعالجة التلقائية لـ {platform_name}: {e}")
        error_msg = str(e).split('\n')[0] 
        bot.send_message(message.chat.id, f"❌ حدث خطأ أثناء معالجة رابط {platform_name}: <b>{error_msg}</b>", parse_mode='HTML')

# ===============================================
#              3. معالجة التحميل النهائي (MP3/فيديو)
# ===============================================

@bot.callback_query_handler(func=lambda call: call.data.startswith('final_dl_'))
def handle_final_download(call):
    parts = call.data.split('_')
    platform_key = parts[2]
    media_type = parts[3] 
    message_id_key = parts[4] 
    
    links = load_links()
    user_url = links.pop(message_id_key, None) 
    save_links(links) 
    
    if not user_url:
        bot.answer_callback_query(call.id, "❌ انتهت صلاحية هذا الرابط.")
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="❌ انتهت صلاحية الرابط. أرسله مرة أخرى مباشرة.", parse_mode='HTML')
        return

    platforms = {'tiktok': 'تيك توك', 'instagram': 'إنستجرام', 'youtube': 'يوتيوب'}
    platform_name = platforms.get(platform_key, 'المنصة')
    download_as_mp3 = (media_type == 'audio')
    
    type_str = "صوت MP3 🎧" if download_as_mp3 else "فيديو 🎥"
    
    try:
        bot.edit_message_text(
            chat_id=call.message.chat.id, 
            message_id=call.message.message_id, 
            text=f"⚡ <b>جارٍ التحميل والمعالجة السريعة من {platform_name} ({type_str})...</b>\n⏳ ثوانٍ معدودة وتكون جاهزة...", 
            parse_mode='HTML'
        )
        download_media_yt_dlp(bot, call.message.chat.id, user_url, platform_name, call.message.message_id, download_as_mp3=download_as_mp3)
    except Exception as e:
        print(f"❌ خطأ حرج في التحميل النهائي {platform_name}: {e}")
        error_msg = str(e).split('\n')[0] 
        bot.send_message(call.message.chat.id, f"❌ حدث خطأ أثناء تحميل {platform_name}: <b>{error_msg}</b>", parse_mode='HTML')

# ===============================================
#   4. آلية التشغيل الذكية (الحماية من 409 Conflict)
# ===============================================

def start_polling():
    print("🧹 إلغاء جميع الاتصالات السابقة وحذف الـ Webhook...")
    try:
        bot.close()
        time.sleep(1)
        bot.remove_webhook(drop_pending_updates=True)
        time.sleep(2)
    except Exception as e:
        print(f"⚠️ تنبيه أثناء التهيئة: {e}")

    print("🚀 انطلاق البوت بنجاح عبر نظام الـ Auto-Detect Polling النقي...")
    bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=10)

def run_single_bot_instance():
    global lock_socket
    try:
        lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        lock_socket.bind(('127.0.0.1', 47200))
        
        bot_thread = threading.Thread(target=start_polling)
        bot_thread.daemon = True
        bot_thread.start()
        print("✅ تم تأكيد تشغيل عملية Polling واحدة فقط للبوت بنجاح.")
    except socket.error:
        print("ℹ️ Worker إضافي تم تجنبه تلقائياً لمنع تعارض (409 Conflict).")

run_single_bot_instance()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
