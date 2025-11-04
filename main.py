import requests
import telebot
from telebot import types
from flask import Flask, request
import re 
import os 
import sys
import json 
import yt_dlp
import tempfile 
from requests.exceptions import Timeout, RequestException 
from telebot.apihelper import ApiException 

# ===============================================
#              0. الإعدادات والثوابت والتهيئة
# ===============================================

# قراءة المتغيرات البيئية
BOT_TOKEN = os.getenv("BOT_TOKEN") 
WEBHOOK_URL_BASE = os.getenv("WEBHOOK_URL") 
WEBHOOK_URL_PATH = "/{}".format(BOT_TOKEN) 

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
    # نستخدم نفس الدالة لمعالجة جميع الروابط
    bot.register_next_step_handler(call.message, process_user_link)
    
# ===============================================
#              3. دالة متخصصة: التنزيل والإرسال
# ===============================================

def download_media_yt_dlp(chat_id, url, platform_name, loading_msg_id):
    """دالة متخصصة للتحميل المباشر باستخدام yt-dlp وإرسال الملف."""
    
    # 🧹 استخدام tempfile.TemporaryDirectory يضمن حذف الملفات تلقائياً
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = os.path.join(tmpdir, 'download.mp4')
        
        ydl_opts = {
            'outtmpl': file_path,
            # صيغة الدمج التي تتطلب ffmpeg 
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]', 
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'cookiefile': None,
            # 🛑 تم حذف 'allow_codec_merging' أيضاً للعودة إلى الأساس الأكثر ثباتاً 
        }

        # بدء التنزيل
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True) 
        
        # حذف رسالة "جاري التحميل"
        bot.delete_message(chat_id, loading_msg_id)
        
        # الإرسال إلى تيليجرام
        caption_text = f"✅ تم التحميل من {platform_name} بواسطة: {CHANNEL_USERNAME}" 
        
        if os.path.exists(file_path):
             with open(file_path, 'rb') as f:
                bot.send_video(
                    chat_id,
                    f,
                    caption=f'<b>{caption_text}</b>', 
                    parse_mode='HTML',
                    supports_streaming=True
                )
             return True
        else:
             raise Exception("فشل yt-dlp في حفظ أو إيجاد الملف بعد التنزيل.")
    
# ===============================================
#              4. الدالة الرئيسية الموحدة للمعالجة
# ===============================================

@bot.message_handler(func=lambda m: True)
def process_user_link(message):
    user_url = message.text
    loading_msg = None
    
    # التحقق من إلغاء العملية
    if user_url.startswith('/'):
        bot.send_message(message.chat.id, "❌ تم إلغاء العملية. اضغط /start.", parse_mode='HTML')
        return send_welcome(message)
        
    try:
        # 🚨 Regex المُحسَّن: التحقق من المنصة
        tiktok_regex = r'https?://(?:www\.)?(?:tiktok\.com|vt\.tiktok\.com|vm\.tiktok\.com)/'
        instagram_regex = r'https?://(?:www\.)?instagram\.com/(?:p|reel|tv|stories)/'
        
        platform_name = None
        
        if re.match(tiktok_regex, user_url):
            platform_name = "تيك توك"
        elif re.match(instagram_regex, user_url):
            platform_name = "إنستجرام"
        else:
            bot.send_message(message.chat.id, "❌ **الرابط غير صالح!** يرجى إرسال رابط تيك توك أو إنستجرام صحيح ومتاح للعامة.", parse_mode='HTML')
            return send_welcome(message)
            
        # إرسال رسالة جاري التحميل
        loading_msg = bot.send_message(message.chat.id, f"<strong>⏳ جارٍ التحميل المباشر من {platform_name}...</strong>", parse_mode="html")
        
        # استدعاء الدالة المتخصصة
        download_media_yt_dlp(
            message.chat.id,
            user_url,
            platform_name,
            loading_msg.message_id
        )
            
    except Exception as e:
        # طباعة الخطأ بوضوح شديد في سجلات Railway
        print(f"=====================================================")
        print(f"❌ خطأ حرج في معالجة {platform_name or 'التحميل'}: {e}") 
        print(f"=====================================================")
        
        if loading_msg:
             try: bot.delete_message(message.chat.id, loading_msg.message_id) 
             except: pass 
        
        # عرض أول سطر من الخطأ فقط للمستخدم ليكون مفهومًا
        error_msg = str(e).split('\n')[0] 
        bot.send_message(message.chat.id, f"❌ حدث خطأ أثناء تحميل {platform_name or 'الملف'}: <b>{error_msg}</b>", parse_mode='HTML')
        
    finally:
        # التأكد من العودة للقائمة الرئيسية
        bot.send_message(message.chat.id, "اضغط على الأمر /start للعودة إلى القائمة الرئيسية.", parse_mode='HTML')


# ===============================================
#              5. تهيئة Webhook
# ===============================================

if __name__ == '__main__':
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL_BASE + WEBHOOK_URL_PATH)
    print('✅ البوت جاهز للتشغيل بواسطة Gunicorn...')
