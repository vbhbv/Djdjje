import requests
import telebot
from telebot import types
from flask import Flask, request
import re 
import os 
import sys
import json # ضروري لمعالجة JSONDecodeError

# ===============================================
#              0. الإعدادات والثوابت والتهيئة
# ===============================================

# قراءة المتغيرات البيئية
BOT_TOKEN = os.getenv("BOT_TOKEN") 
WEBHOOK_URL_BASE = os.getenv("WEBHOOK_URL") 
WEBHOOK_URL_PATH = "/{}".format(BOT_TOKEN) 

# المتغيرات الخاصة بالـ API
API_ACCESS_KEY = os.getenv("API_ACCESS_KEY") # المفتاح الجديد
TIKTOK_API_ENDPOINT = os.getenv("TIKTOK_API_ENDPOINT") # رابط TikHub
INSTAGRAM_API_ENDPOINT = os.getenv("INSTAGRAM_API_ENDPOINT") # رابط TikHub

DEVELOPER_USER_ID = "1315011160"
CHANNEL_USERNAME = "@SuPeRx1"
API_TIMEOUT = 20

# التهيئة
try:
    bot = telebot.TeleBot(BOT_TOKEN)
    app = Flask(__name__) 
except Exception as e:
    print(f"❌ فشل تهيئة البوت/Flask. الخطأ: {e}")

# دالة مساعدة لإنشاء Headers
def get_auth_headers():
    """تنشئ الـ Headers اللازمة لإرسال مفتاح الـ API."""
    if not API_ACCESS_KEY:
        print("❌ تنبيه: مفتاح API غير موجود.")
        return {}
    return {
        'Authorization': f'Bearer {API_ACCESS_KEY}', 
        'User-Agent': 'TelegramBot/1.0'
    }

# ===============================================
#              1. نقاط وصول Webhook (ULTRA-STABLE)
# ===============================================

@app.route(WEBHOOK_URL_PATH, methods=['POST'])
def webhook():
    # ... (هذا الجزء يبقى كما هو لمنع 502)
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
#              2. و 3. معالجة الأوامر والدوال
# ===============================================

@bot.message_handler(commands=["start"])
def send_welcome(message):
    # ... (دالة start تبقى كما هي)
    first_name = message.from_user.first_name if message.from_user else "صديقنا"
    markup = types.InlineKeyboardMarkup(row_width=2)
    tt_btn = types.InlineKeyboardButton("تحميل تيك توك 🎶", callback_data="download_tiktok")
    ig_btn = types.InlineKeyboardButton("تحميل إنستجرام 📸", callback_data="download_instagram")
    dev_btn = types.InlineKeyboardButton("المطور 👨‍💻", url="https://t.me/yourusername") 
    markup.add(tt_btn, ig_btn, dev_btn)
    bot.send_message(
        message.chat.id,
        f"""<b>مرحباً بك {first_name}!</b> 👋
        أنا بوت التحميل الشامل. اختر المنصة التي تريد التحميل منها:
        * اختر من القائمة أدناه وأرسل <b>الرابط فوراً</b>.
        """,
        parse_mode='HTML', 
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data in ['download_tiktok', 'download_instagram'])
def handle_download_choice(call):
    # ... (دالة callback تبقى كما هي)
    platform = "تيك توك" if call.data == 'download_tiktok' else "إنستجرام"
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=f"""<b>🚀 أرسل رابط فيديو {platform} الآن!</b>""",
        parse_mode='HTML' 
    )
    if call.data == 'download_tiktok':
        bot.register_next_step_handler(call.message, process_tiktok_link)
    elif call.data == 'download_instagram':
        bot.register_next_step_handler(call.message, process_instagram_link)
        
def process_tiktok_link(message):
    user_url = message.text
    loading_msg = None
    
    if user_url.startswith('/'):
        bot.send_message(message.chat.id, "❌ تم إلغاء العملية. اضغط /start.", parse_mode='HTML')
        send_welcome(message) 
        return
        
    try:
        if not re.match(r'https?://(?:www\.)?tiktok\.com/', user_url):
            bot.send_message(message.chat.id, "<b>❌ الرابط غير صالح!</b> يرجى التأكد من رابط تيك توك صحيح.", parse_mode='HTML')
            send_welcome(message) 
            return
            
        loading_msg = bot.send_message(message.chat.id, "<strong>⏳ جارٍ التحميل من تيك توك...</strong>", parse_mode="html")

        # -------------------------------------------------------------
        # استخدام مفتاح API وروابط TikHub
        headers = get_auth_headers()
        
        try:
            # TikHub يتوقع الرابط كاملاً في الـ Query String
            response = requests.get(
                f'{TIKTOK_API_ENDPOINT}?url={user_url}', 
                headers=headers, 
                timeout=API_TIMEOUT
            )
            response.raise_for_status() 
            data = response.json()
        
        except requests.exceptions.Timeout:
            raise Exception("فشل الاتصال: API التحميل استغرق وقتاً طويلاً (Timeout).")
        except requests.exceptions.RequestException as e:
            raise Exception(f"خطأ في الاتصال بالـ API الخارجي: {e}")
        except json.JSONDecodeError:
            print(f"❌ الرد الخام من API تيك توك: {response.text}")
            raise Exception("خطأ: API التحميل أرسل بيانات غير صالحة (ليست JSON).")
        # -------------------------------------------------------------
        
        # يجب تعديل مسارات استخراج الروابط لتتوافق مع رد TikHub
        # سأفترض أن TikHub يعيد "data" فيها رابط "videoURL" أو "audioURL"
        video_url = data.get("data", {}).get("videoURL") 
        audio_url = data.get("data", {}).get("audioURL")
        
        bot.delete_message(message.chat.id, loading_msg.message_id)
        
        caption_text = f"✅ تم التحميل بواسطة: {CHANNEL_USERNAME}" 
        
        if video_url:
            bot.send_video(message.chat.id, video_url, caption=f'<b>{caption_text}</b>', parse_mode='HTML')
        
        if not video_url:
             bot.send_message(message.chat.id, "❌ لم يتم العثور على فيديو. قد يكون الرابط خاصاً أو غير صحيح.", parse_mode='HTML')
    
    except Exception as e:
        print(f"Error in TikTok: {e}")
        if loading_msg:
             try: bot.delete_message(message.chat.id, loading_msg.message_id) 
             except: pass 
        bot.send_message(message.chat.id, f"❌ حدث خطأ أثناء التحميل: <b>{e}</b>", parse_mode='HTML')
        
    bot.send_message(message.chat.id, "اضغط على الأمر /start للعودة إلى القائمة الرئيسية.", parse_mode='HTML')

# -------------------
# دالة إنستجرام (يجب تعديلها بنفس طريقة تيك توك)
# -------------------

def process_instagram_link(message):
    user_url = message.text
    loading_msg = None
    if user_url.startswith('/'):
        bot.send_message(message.chat.id, "❌ تم إلغاء العملية. اضغط /start.", parse_mode='HTML')
        send_welcome(message) 
        return
        
    try:
        if not re.match(r'https?://(?:www\.)?instagram\.com/', user_url):
            bot.send_message(message.chat.id, "<b>❌ الرابط غير صالح!</b> يرجى التأكد من رابط إنستجرام صحيح.", parse_mode='HTML')
            send_welcome(message)
            return

        loading_msg = bot.send_message(message.chat.id, f"""<strong>⏳ جارٍ التحميل من إنستجرام...</strong>""", parse_mode="html")
        
        # -------------------------------------------------------------
        # الجزء الحرج: استخدام المفتاح وروابط TikHub
        headers = get_auth_headers()
        
        try:
            response = requests.get(
                f'{INSTAGRAM_API_ENDPOINT}?url={user_url}', 
                headers=headers, 
                timeout=API_TIMEOUT
            )
            response.raise_for_status()
            data = response.json()
        
        except Exception as e:
            # معالجة فشل الاتصال/JSON
             raise Exception(f"فشل API إنستجرام: {e}")
        # -------------------------------------------------------------

        # يجب تعديل مسارات استخراج الروابط لتتوافق مع رد TikHub
        media_url = data.get('data', {}).get('media_url') 
        
        bot.delete_message(message.chat.id, loading_msg.message_id) 
        
        caption_text = f"✅ تم التحميل بواسطة: {CHANNEL_USERNAME}" 

        if media_url:
            bot.send_video(message.chat.id, media_url, caption=f"<b>{caption_text}</b>", parse_mode='HTML')
        else:
            bot.send_message(message.chat.id, "❌ لم يتم العثور على وسائط في الرابط. قد يكون الرابط خاصاً أو غير صحيح.", parse_mode='HTML')

    except Exception as e:
        print(f"Error in Instagram: {e}")
        if loading_msg:
             try: bot.delete_message(message.chat.id, loading_msg.message_id) 
             except: pass 
        bot.send_message(message.chat.id, f"❌ حدث خطأ أثناء التحميل: <b>{e}</b>", parse_mode='HTML')
        
    bot.send_message(message.chat.id, "اضغط على الأمر /start للعودة إلى القائمة الرئيسية.", parse_mode='HTML')


# ===============================================
#              4. تهيئة Webhook
# ===============================================

if __name__ == '__main__':
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL_BASE + WEBHOOK_URL_PATH)
    print('✅ البوت جاهز للتشغيل بواسطة Gunicorn...')
