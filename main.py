import os
import sys
import re
import json
import threading
from flask import Flask
import telebot
from telebot import types

# 🚨 استيراد جميع الدوال من ملف التحميل الخارجي
from handlers.download import download_media_yt_dlp, load_links, save_links

# ===============================================
#              0. الإعدادات والثوابت والتهيئة
# ===============================================

# وضع التوكن مباشرة داخل الكود لمنع أي تعارض
BOT_TOKEN = "8913222700:AAETkljjyRrGf-NllmznlCLdprzUQv37Xww"
CHANNEL_USERNAME = "@SuPeRx1"
DEVELOPER_USER_ID = "1315011160"

# تهيئة البوت وتطبيق Flask الخفيف لإبقاء السيرفر حياً
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# نقطة وصول وهمية لفحص سلامة التطبيق (Health Check) المطلوبة من الاستضافة
@app.route('/')
def home():
    return "Bot is running perfectly via Polling with Hardcoded Token!", 200

# ===============================================
#              1. معالجة الأوامر الرئيسية (الواجهة)
# ===============================================

@bot.message_handler(commands=["start"])
def send_welcome(message):
    first_name = message.from_user.first_name if message.from_user else "صديقنا"
    markup = types.InlineKeyboardMarkup(row_width=2)
    tt_btn = types.InlineKeyboardButton("تحميل تيك توك 🎶", callback_data="download_tiktok")
    ig_btn = types.InlineKeyboardButton("تحميل إنستجرام 📸", callback_data="download_instagram")
    yt_btn = types.InlineKeyboardButton("تحميل يوتيوب ▶️", callback_data="download_youtube")
    dev_btn = types.InlineKeyboardButton("المطور 👨‍💻", url="https://t.me/yourusername") 
    markup.add(tt_btn, ig_btn, yt_btn, dev_btn)
    bot.send_message(
        message.chat.id,
        f"""<b>مرحباً بك {first_name}!</b> 👋
أنا بوت التحميل الشامل. اختر المنصة التي تريد التحميل منها:
* اختر من القائمة أدناه وأرسل <b>الرابط فوراً</b>.""",
        parse_mode='HTML', 
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('download_'))
def handle_download_choice(call):
    platform_key = call.data.split('_')[1]
    platforms = {'tiktok': 'تيك توك', 'instagram': 'إنستجرام', 'youtube': 'يوتيوب'}
    platform = platforms.get(platform_key, 'غير معروف')
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=f"<b>🚀 أرسل رابط فيديو {platform} الآن!</b>",
        parse_mode='HTML' 
    )
    call.message.platform_key = platform_key 
    bot.register_next_step_handler(call.message, process_user_link)
    
# ===============================================
#              2. الدالة الرئيسية الموحدة للمعالجة
# ===============================================

@bot.message_handler(func=lambda m: True)
def process_user_link(message):
    user_url = message.text
    loading_msg = None
    platform_key = getattr(message, 'platform_key', None) 
    
    if user_url.startswith('/'):
        bot.send_message(message.chat.id, "❌ تم إلغاء العملية. اضغط /start.", parse_mode='HTML')
        return send_welcome(message)

    if not platform_key:
        if re.match(r'https?://(?:www\.)?(?:tiktok\.com|vt\.tiktok\.com|vm\.tiktok\.com)/', user_url):
            platform_key = 'tiktok'
        elif re.match(r'https?://(?:www\.)?instagram\.com/(?:p|reel|tv|stories)/', user_url):
            platform_key = 'instagram'
        elif re.match(r'https?://(?:www\.)?(?:youtube\.com|youtu\.be)/', user_url):
            platform_key = 'youtube'
        else:
            bot.send_message(message.chat.id, "❌ **الرابط غير صالح!** يرجى إرسال رابط صحيح.", parse_mode='HTML')
            return

    platforms = {'tiktok': 'تيك توك', 'instagram': 'إنستجرام', 'youtube': 'يوتيوب'}
    platform_name = platforms[platform_key]
    
    try:
        if platform_key == 'youtube':
            message_id_key = str(message.message_id) 
            links = load_links()
            links[message_id_key] = user_url
            save_links(links) 
            
            markup = types.InlineKeyboardMarkup()
            vid_btn = types.InlineKeyboardButton("تحميل فيديو 🎥", callback_data=f"final_dl_{platform_key}_video_{message_id_key}")
            aud_btn = types.InlineKeyboardButton("تحويل إلى صوت 🎧 (MP3)", callback_data=f"final_dl_{platform_key}_audio_{message_id_key}")
            markup.add(vid_btn, aud_btn)
            
            bot.send_message(message.chat.id, f"✅ تم التعرف على رابط {platform_name}. الرجاء اختيار صيغة التحميل:", reply_markup=markup, parse_mode='HTML')
            return
            
        loading_msg = bot.send_message(message.chat.id, f"<strong>⏳ جارٍ التحميل المباشر من {platform_name} (فيديو)...</strong>", parse_mode="html")
        download_media_yt_dlp(bot, message.chat.id, user_url, platform_name, loading_msg.message_id, download_as_mp3=False)
            
    except Exception as e:
        print(f"❌ خطأ في معالجة {platform_name}: {e}")
        if loading_msg:
             try: bot.delete_message(message.chat.id, loading_msg.message_id) 
             except: pass 
        error_msg = str(e).split('\n')[0] 
        bot.send_message(message.chat.id, f"❌ حدث خطأ أثناء تحميل {platform_name}: <b>{error_msg}</b>", parse_mode='HTML')

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
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="❌ انتهت صلاحية التحميل. اضغط /start للبدء مجدداً.", parse_mode='HTML')
        return

    platforms = {'tiktok': 'تيك توك', 'instagram': 'إنستجرام', 'youtube': 'يوتيوب'}
    platform_name = platforms[platform_key]
    download_as_mp3 = (media_type == 'audio')
    
    try:
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"<b>⏳ جارٍ التحميل/التحويل من {platform_name} ({media_type.upper()})...</b>", parse_mode='HTML')
        download_media_yt_dlp(bot, call.message.chat.id, user_url, platform_name, call.message.message_id, download_as_mp3)
    except Exception as e:
        print(f"❌ خطأ حرج في التحميل النهائي {platform_name}: {e}")
        error_msg = str(e).split('\n')[0] 
        bot.send_message(call.message.chat.id, f"❌ حدث خطأ أثناء تحميل {platform_name}: <b>{error_msg}</b>", parse_mode='HTML')

# ===============================================
#              4. التشغيل الذكي (Flask + Polling)
# ===============================================

def run_bot():
    print("🚀 البوت بدأ العمل بنظام Polling في خلفية السيرفر...")
    bot.remove_webhook()
    bot.infinity_polling(skip_pending=True)

if __name__ == '__main__':
    # تشغيل البوت في خيط (Thread) مستقل بالخلفية لمنع حظر خادم الويب
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # تشغيل خادم Flask للاستماع للمنفذ المتوقع من خادم الاستضافة
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
