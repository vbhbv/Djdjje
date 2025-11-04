import requests
import telebot
from telebot import types
from flask import Flask, request
import re 
import os 
import sys
import json 
import yt_dlp # المكتبة الجديدة
import tempfile # لمعالجة الملفات المؤقتة

# ===============================================
#              0. الإعدادات والثوابت والتهيئة
# ===============================================

# قراءة المتغيرات البيئية
BOT_TOKEN = os.getenv("BOT_TOKEN") 
WEBHOOK_URL_BASE = os.getenv("WEBHOOK_URL") 
WEBHOOK_URL_PATH = "/{}".format(BOT_TOKEN) 

# تم حذف جميع متغيرات API الخارجية (TIKHUB_KEY, ENDPOINTS)

DEVELOPER_USER_ID = "1315011160"
CHANNEL_USERNAME = "@SuPeRx1"

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
#              2. معالجة الأوامر الرئيسية
# ===============================================

@bot.message_handler(commands=["start"])
def send_welcome(message):
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
        
# ===============================================
#              3. دوال التحميل (باستخدام yt-dlp)
# ===============================================

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
            
        loading_msg = bot.send_message(message.chat.id, "<strong>⏳ جارٍ التحميل المباشر من تيك توك... قد يستغرق وقتاً.</strong>", parse_mode="html")

        # إنشاء مسار مؤقت لحفظ الملف
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, 'video.mp4')
            
            # خيارات التنزيل لـ yt-dlp
            ydl_opts = {
                'outtmpl': file_path,
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]', 
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'cookiefile': None, # لتجنب مشاكل تسجيل الدخول
                'postprocessors': [{
                    'key': 'FFmpegVideoRemuxer',
                    'prefer_muxer': 'mp4',
                }],
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(user_url, download=True)
            
            bot.delete_message(message.chat.id, loading_msg.message_id)
            
            caption_text = f"✅ تم التحميل مباشرة بواسطة: {CHANNEL_USERNAME}" 
            
            # إرسال الملف المُحمَّل
            if os.path.exists(file_path):
                 with open(file_path, 'rb') as f:
                    bot.send_video(
                        message.chat.id,
                        f,
                        caption=f'<b>{caption_text}</b>', 
                        parse_mode='HTML',
                        supports_streaming=True
                    )
            else:
                 raise Exception("فشل yt-dlp في استخراج المسار أو التنزيل.")


    except Exception as e:
        print(f"=====================================================")
        print(f"❌ خطأ حرج في معالجة تيك توك (yt-dlp): {e}") 
        print(f"=====================================================")
        
        if loading_msg:
             try: bot.delete_message(message.chat.id, loading_msg.message_id) 
             except: pass 
        bot.send_message(message.chat.id, f"❌ حدث خطأ أثناء التحميل المباشر: <b>{e}</b>", parse_mode='HTML')
        
    bot.send_message(message.chat.id, "اضغط على الأمر /start للعودة إلى القائمة الرئيسية.", parse_mode='HTML')

# -------------------
# دالة إنستجرام (باستخدام yt-dlp)
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

        loading_msg = bot.send_message(message.chat.id, f"""<strong>⏳ جارٍ التحميل المباشر من إنستجرام...</strong>""", parse_mode="html")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, 'video.mp4')
            
            ydl_opts = {
                'outtmpl': file_path,
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]', 
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'cookiefile': None, # مهم لبعض المحتوى العام
                'postprocessors': [{
                    'key': 'FFmpegVideoRemuxer',
                    'prefer_muxer': 'mp4',
                }],
            }
        
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(user_url, download=True)

        bot.delete_message(message.chat.id, loading_msg.message_id) 
        
        caption_text = f"✅ تم التحميل مباشرة بواسطة: {CHANNEL_USERNAME}" 

        if os.path.exists(file_path):
             with open(file_path, 'rb') as f:
                bot.send_video(message.chat.id, f, caption=f"<b>{caption_text}</b>", parse_mode='HTML', supports_streaming=True)
        else:
             raise Exception("فشل yt-dlp في استخراج المسار أو التنزيل.")


    except Exception as e:
        print(f"=====================================================")
        print(f"❌ خطأ حرج في معالجة إنستجرام (yt-dlp): {e}") 
        print(f"=====================================================")
        
        if loading_msg:
             try: bot.delete_message(message.chat.id, loading_msg.message_id) 
             except: pass 
        bot.send_message(message.chat.id, f"❌ حدث خطأ أثناء التحميل المباشر: <b>{e}</b>", parse_mode='HTML')
        
    bot.send_message(message.chat.id, "اضغط على الأمر /start للعودة إلى القائمة الرئيسية.", parse_mode='HTML')


# ===============================================
#              4. تهيئة Webhook
# ===============================================

if __name__ == '__main__':
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL_BASE + WEBHOOK_URL_PATH)
    print('✅ البوت جاهز للتشغيل بواسطة Gunicorn...')
