import requests
import telebot
from telebot import types
from flask import Flask, request
import re 
import os 
import sys
import json 

# 🚨 استيراد جميع الدوال من ملف التحميل الخارجي
from handlers.download import download_media_yt_dlp, load_links, save_links

# ===============================================
#              0. الإعدادات والثوابت والتهيئة
# ===============================================

# قراءة المتغيرات البيئية
BOT_TOKEN = os.getenv("BOT_TOKEN") 
WEBHOOK_URL_BASE = os.getenv("WEBHOOK_URL") 
WEBHOOK_URL_PATH = "/{}".format(BOT_TOKEN) 

DEVELOPER_USER_ID = "1315011160"
CHANNEL_USERNAME = "@SuPeRx1" # يُفضل وضعه كمتغير بيئي أيضاً

# التهيئة
try:
    bot = telebot.TeleBot(BOT_TOKEN)
    app = Flask(__name__) 
except Exception as e:
    print(f"❌ فشل تهيئة البوت/Flask. الخطأ: {e}")

# ===============================================
#              1. نقاط وصول Webhook
# ===============================================

@app.route(WEBHOOK_URL_PATH, methods=['POST'])
def webhook():
    """نقطة النهاية التي يستقبل منها البوت تحديثات تيليجرام."""
    if request.headers.get('content-type') == 'application/json':
        try:
            json_string = request.get_data().decode('utf-8')
            update = telebot.types.Update.de_json(json_string)
            bot.process_new_updates([update])
        except Exception as e:
            print(f"❌ خطأ حرج في معالجة Webhook: {e}")
        return '', 200 
    else:
        return 'Error', 403

# ===============================================
#              2. معالجة الأوامر الرئيسية (الواجهة)
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
        * اختر من القائمة أدناه وأرسل <b>الرابط فوراً</b>.
        """,
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
        text=f"""<b>🚀 أرسل رابط فيديو {platform} الآن!</b>""",
        parse_mode='HTML' 
    )
    call.message.platform_key = platform_key 
    bot.register_next_step_handler(call.message, process_user_link)
    
# ===============================================
#              3. الدالة الرئيسية الموحدة للمعالجة
# ===============================================

@bot.message_handler(func=lambda m: True)
def process_user_link(message):
    user_url = message.text
    loading_msg = None
    platform_key = getattr(message, 'platform_key', None) 
    
    # 1. التحقق من إلغاء العملية
    if user_url.startswith('/'):
        bot.send_message(message.chat.id, "❌ تم إلغاء العملية. اضغط /start.", parse_mode='HTML')
        return send_welcome(message)

    # 2. تحديد المنصة بناءً على الرابط
    if not platform_key:
        if re.match(r'https?://(?:www\.)?(?:tiktok\.com|vt\.tiktok\.com|vm\.tiktok\.com)/', user_url):
            platform_key = 'tiktok'
        elif re.match(r'https?://(?:www\.)?instagram\.com/(?:p|reel|tv|stories)/', user_url):
            platform_key = 'instagram'
        elif re.match(r'https?://(?:www\.)?(?:youtube\.com|youtu\.be)/', user_url):
            platform_key = 'youtube'
        else:
            bot.send_message(message.chat.id, "❌ **الرابط غير صالح!** يرجى إرسال رابط صحيح.", parse_mode='HTML')
            return send_welcome(message)
    
    platforms = {'tiktok': 'تيك توك', 'instagram': 'إنستجرام', 'youtube': 'يوتيوب'}
    platform_name = platforms[platform_key]
    
    try:
        # 3. إرسال خيار التحويل لليوتيوب فقط 
        if platform_key == 'youtube':
            
            message_id_key = str(message.message_id) 
            
            links = load_links()
            links[message_id_key] = user_url
            save_links(links) 
            
            markup = types.InlineKeyboardMarkup()
            # تمرير المفتاح القصير بدلاً من الرابط الطويل
            vid_btn = types.InlineKeyboardButton("تحميل فيديو 🎥", callback_data=f"final_dl_{platform_key}_video_{message_id_key}")
            aud_btn = types.InlineKeyboardButton("تحويل إلى صوت 🎧 (MP3)", callback_data=f"final_dl_{platform_key}_audio_{message_id_key}")
            markup.add(vid_btn, aud_btn)
            
            bot.send_message(message.chat.id, f"✅ تم التعرف على رابط {platform_name}. الرجاء اختيار صيغة التحميل:", reply_markup=markup, parse_mode='HTML')
            return
            
        # 4. بدء عملية التحميل المباشر لـ تيك توك وإنستجرام (فيديو فقط)
        loading_msg = bot.send_message(message.chat.id, f"<strong>⏳ جارٍ التحميل المباشر من {platform_name} (فيديو)...</strong>", parse_mode="html")
        
        # 🚨 استدعاء الدالة من الملف الخارجي (handlers/download.py)
        download_media_yt_dlp(bot, message.chat.id, user_url, platform_name, loading_msg.message_id, download_as_mp3=False)
            
    except Exception as e:
        # 5. معالجة الأخطاء
        print(f"=====================================================")
        print(f"❌ خطأ حرج في معالجة {platform_name or 'التحميل'}: {e}") 
        print(f"=====================================================")
        
        if loading_msg:
             try: bot.delete_message(message.chat.id, loading_msg.message_id) 
             except: pass 
        
        error_msg = str(e).split('\n')[0] 
        bot.send_message(message.chat.id, f"❌ حدث خطأ أثناء تحميل {platform_name or 'الملف'}: <b>{error_msg}</b>", parse_mode='HTML')
        
    finally:
        # 6. إنهاء العملية
        bot.send_message(message.chat.id, "اضغط على الأمر /start للعودة إلى القائمة الرئيسية.", parse_mode='HTML')

# ===============================================
#              4. معالجة التحميل النهائي (MP3/فيديو)
# ===============================================

@bot.callback_query_handler(func=lambda call: call.data.startswith('final_dl_'))
def handle_final_download(call):
    # final_dl_platform_type_message_id_key
    parts = call.data.split('_')
    platform_key = parts[2]
    media_type = parts[3] 
    message_id_key = parts[4] 
    
    # 🚨 استرداد الرابط من ملف JSON وحذفه منه
    links = load_links()
    user_url = links.pop(message_id_key, None) 
    save_links(links) 
    
    if not user_url:
        bot.answer_callback_query(call.id, "❌ انتهت صلاحية هذا الرابط أو تم تحميله مسبقاً.")
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"❌ انتهت صلاحية التحميل. اضغط /start للبدء مجدداً.",
            parse_mode='HTML'
        )
        return

    platforms = {'tiktok': 'تيك توك', 'instagram': 'إنستجرام', 'youtube': 'يوتيوب'}
    platform_name = platforms[platform_key]
    download_as_mp3 = (media_type == 'audio')
    
    try:
        # 1. تحديث رسالة التحميل
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"<b>⏳ جارٍ التحميل/التحويل من {platform_name} ({media_type.upper()})...</b>",
            parse_mode='HTML'
        )
        
        # 2. استدعاء دالة التنزيل المتخصصة
        download_media_yt_dlp(
            bot, # 🚨 تمرير البوت للدالة الخارجية
            call.message.chat.id,
            user_url,
            platform_name,
            call.message.message_id,
            download_as_mp3
        )
        
    except Exception as e:
        # 3. معالجة الأخطاء
        print(f"=====================================================")
        print(f"❌ خطأ حرج في التحميل النهائي {platform_name}: {e}") 
        print(f"=====================================================")
        
        error_msg = str(e).split('\n')[0] 
        bot.send_message(call.message.chat.id, f"❌ حدث خطأ أثناء تحميل {platform_name}: <b>{error_msg}</b>", parse_mode='HTML')
        
    finally:
        bot.send_message(call.message.chat.id, "اضغط على الأمر /start للعودة إلى القائمة الرئيسية.", parse_mode='HTML')

# ===============================================
#              5. تهيئة Webhook
# ===============================================

if __name__ == '__main__':
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL_BASE + WEBHOOK_URL_PATH)
    print('✅ البوت جاهز للتشغيل بواسطة Gunicorn...')
