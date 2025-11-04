import requests
import telebot
from telebot import types
from flask import Flask, request
import re 
import os 
import sys

# ===============================================
#              0. الإعدادات والثوابت والتهيئة
# ===============================================

# قراءة المتغيرات البيئية
BOT_TOKEN = os.getenv("BOT_TOKEN") 
WEBHOOK_URL_BASE = os.getenv("WEBHOOK_URL") 
WEBHOOK_URL_PATH = "/{}".format(BOT_TOKEN) 

DEVELOPER_USER_ID = "1315011160"
CHANNEL_USERNAME = "@SuPeRx1"

TIKTOK_API = 'https://dev-broksuper.pantheonsite.io/api/e/mp3.php?url='
INSTAGRAM_API = 'https://dev-broksuper.pantheonsite.io/api/ink.php?url='
API_TIMEOUT = 20

# طباعة المتغيرات للتحقق النهائي
print(f"✅ تم قراءة التوكن: {BOT_TOKEN}")
print(f"✅ تم قراءة Webhook URL: {WEBHOOK_URL_BASE + WEBHOOK_URL_PATH}")

if not BOT_TOKEN or not WEBHOOK_URL_BASE:
    print("❌ خطأ: يجب تعيين متغيرات BOT_TOKEN و WEBHOOK_URL بشكل كامل!")
    # يمكن أن يكون الفشل هنا هو سبب عدم ظهور رسالة "جاهز للتشغيل"

# التهيئة
try:
    bot = telebot.TeleBot(BOT_TOKEN)
    app = Flask(__name__) 
except Exception as e:
    print(f"❌ فشل تهيئة البوت/Flask. الخطأ: {e}")

# ===============================================
#              1. نقاط وصول Webhook (ULTRA-STABLE)
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
#              2. معالجة الأوامر الرئيسية (مع الأزرار)
# ===============================================

@bot.message_handler(commands=["start"])
def send_welcome(message):
    
    first_name = message.from_user.first_name if message.from_user else "صديقنا"
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    tt_btn = types.InlineKeyboardButton("تحميل تيك توك 🎶", callback_data="download_tiktok")
    ig_btn = types.InlineKeyboardButton("تحميل إنستجرام 📸", callback_data="download_instagram")
    # تم تغيير رابط المطور لتفادي أي مشاكل في التهيئة
    dev_btn = types.InlineKeyboardButton("المطور 👨‍💻", url="https://t.me/yourusername") 
    
    markup.add(tt_btn, ig_btn, dev_btn)
    
    bot.send_message(
        message.chat.id,
        f"""
        <b>مرحباً بك {first_name}!</b> 👋
        
        أنا بوت التحميل الشامل. اختر المنصة التي تريد التحميل منها:
        * اختر من القائمة أدناه وأرسل <b>الرابط فوراً</b>.
        """,
        parse_mode='HTML', 
        reply_markup=markup
    )

# ===============================================
#              3. معالجة الـ Callback و الدوال
# ===============================================
# هذه الدوال لم يتم تعديلها لأنها تعمل فقط بعد نجاح الرد الأولي.

@bot.callback_query_handler(func=lambda call: call.data in ['download_tiktok', 'download_instagram'])
def handle_download_choice(call):
    platform = "تيك توك" if call.data == 'download_tiktok' else "إنستجرام"
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=f"""
        <b>🚀 أرسل رابط فيديو {platform} الآن!</b>
        """,
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
        bot.send_message(message.chat.id, "❌ تم إلغاء عملية التحميل. اضغط /start للعودة.", parse_mode='HTML')
        send_welcome(message) 
        return
        
    try:
        if not re.match(r'https?://(?:www\.)?tiktok\.com/', user_url):
            bot.send_message(message.chat.id, "<b>❌ الرابط غير صالح!</b> يرجى التأكد من إرسال رابط تيك توك صحيح.", parse_mode='HTML')
            send_welcome(message) 
            return
            
        loading_msg = bot.send_message(message.chat.id, "<strong>⏳ جارٍ التحميل من تيك توك... يرجى الانتظار.</strong>", parse_mode="html")
        
        response = requests.get(f'{TIKTOK_API}{user_url}', timeout=API_TIMEOUT).json()
        video_url = response.get("video", {}).get("videoURL")
        audio_url = response.get("audioURL")
        
        bot.delete_message(message.chat.id, loading_msg.message_id)
        
        caption_text = f"✅ تم التحميل بواسطة: {CHANNEL_USERNAME}" 
        
        if video_url:
            bot.send_video(message.chat.id, video_url, caption=f'<b>{caption_text}</b>', parse_mode='HTML')
        
        if audio_url:
            bot.send_voice(message.chat.id, audio_url, caption=f'<b>🎧 {caption_text}</b>', parse_mode='HTML')
            
        if not video_url and not audio_url:
             bot.send_message(message.chat.id, "❌ لم يتم العثور على محتوى للتحميل. تأكد من أن الرابط عام.", parse_mode='HTML')
    
    except Exception as e:
        print(f"Error in TikTok: {e}")
        if loading_msg:
             try: bot.delete_message(message.chat.id, loading_msg.message_id) 
             except: pass 
        bot.send_message(message.chat.id, "❌ حدث خطأ أثناء التحميل. تأكد من الرابط أو حاول لاحقاً.", parse_mode='HTML')
        
    bot.send_message(message.chat.id, "اضغط على الأمر /start للعودة إلى القائمة الرئيسية.", parse_mode='HTML')


def process_instagram_link(message):
    user_url = message.text
    loading_msg = None
    if user_url.startswith('/'):
        bot.send_message(message.chat.id, "❌ تم إلغاء عملية التحميل. اضغط /start للعودة.", parse_mode='HTML')
        send_welcome(message) 
        return
        
    try:
        if not re.match(r'https?://(?:www\.)?instagram\.com/', user_url):
            bot.send_message(message.chat.id, "<b>❌ الرابط غير صالح!</b> يرجى التأكد من إرسال رابط إنستجرام صحيح.", parse_mode='HTML')
            send_welcome(message)
            return

        loading_msg = bot.send_message(message.chat.id, f"""<strong>⏳ جارٍ التحميل من إنستجرام... يرجى الانتظار.</strong>""", parse_mode="html")
        
        response = requests.get(f"{INSTAGRAM_API}{user_url}", timeout=API_TIMEOUT).json()
        media_url = response.get('media')
        
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
        bot.send_message(message.chat.id, "❌ حدث خطأ أثناء التحميل. تأكد من الرابط أو حاول لاحقاً.", parse_mode='HTML')
        
    bot.send_message(message.chat.id, "اضغط على الأمر /start للعودة إلى القائمة الرئيسية.", parse_mode='HTML')


# ===============================================
#              4. تهيئة Webhook (لـ Gunicorn)
# ===============================================

if __name__ == '__main__':
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL_BASE + WEBHOOK_URL_PATH)
    print('✅ البوت جاهز للتشغيل بواسطة Gunicorn...')
