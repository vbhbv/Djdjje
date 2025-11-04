import os 
import telebot
from flask import Flask, request

# ===============================================
#              0. الإعدادات والثوابت والتهيئة
# ===============================================

# قراءة المتغيرات البيئية
BOT_TOKEN = os.getenv("BOT_TOKEN") 
WEBHOOK_URL_BASE = os.getenv("WEBHOOK_URL") 
WEBHOOK_URL_PATH = "/{}".format(BOT_TOKEN)

# طباعة المتغيرات للتحقق النهائي 
print(f"✅ تم قراءة التوكن: {BOT_TOKEN}")
print(f"✅ تم قراءة Webhook URL: {WEBHOOK_URL_BASE + WEBHOOK_URL_PATH}")


# التهيئة
try:
    bot = telebot.TeleBot(BOT_TOKEN)
    app = Flask(__name__) 
except Exception as e:
    print(f"❌ فشل تهيئة البوت/Flask. الخطأ: {e}")

# ===============================================
#              1. نقاط وصول Webhook (الثابتة)
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
            # طباعة الخطأ في سجلات Railway لمعرفته
            print(f"❌ خطأ حرج في معالجة Webhook: {e}")
            
        # نعود دائماً بـ 200 OK
        return '', 200 
    else:
        return 'Error', 403

# ===============================================
#              2. معالجة الأوامر الرئيسية (الأبسط)
# ===============================================

@bot.message_handler(commands=["start"])
def send_welcome(message):
    """يرسل رسالة ترحيب نصية بسيطة جداً."""
    
    # رسالة نصية بسيطة جداً بدون تنسيق HTML أو أزرار
    bot.send_message(
        message.chat.id,
        "🎉 تم استلام أمر /start بنجاح! هذا هو الرد الأبسط.",
        parse_mode=None # لضمان عدم وجود أخطاء تنسيق
    )

# ===============================================
#              3. تهيئة Webhook
# ===============================================

if __name__ == '__main__':
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL_BASE + WEBHOOK_URL_PATH)
    print('✅ البوت جاهز للتشغيل بواسطة Gunicorn...')

