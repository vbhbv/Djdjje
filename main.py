Import requests
import telebot
from telebot import types
from flask import Flask, request
import re 
import os 
import sys
import json 
from datetime import datetime
from collections import defaultdict

# 🚨 استيراد جميع الدوال من ملف التحميل الخارجي
from handlers.download import download_media_yt_dlp, load_links, save_links

# ===============================================
#              0. الإعدادات والثوابت والتهيئة
# ===============================================

# قراءة المتغيرات البيئية
BOT_TOKEN = os.getenv("BOT_TOKEN") 
WEBHOOK_URL_BASE = os.getenv("WEBHOOK_URL") 
WEBHOOK_URL_PATH = "/{}".format(BOT_TOKEN) 

# --- تحديث: الثوابت الجديدة للمطور والقناة ---
DEVELOPER_USER_ID = "6166700051" # تم تحديث ID المطور
CHANNEL_USERNAME = "@iiollr"      # القناة المطلوبة للاشتراك
STATS_FILE = "stats.json"         # ملف حفظ الإحصائيات
# ===============================================

# التهيئة
try:
    bot = telebot.TeleBot(BOT_TOKEN)
    app = Flask(__name__) 
except Exception as e:
    print(f"❌ فشل تهيئة البوت/Flask. الخطأ: {e}")

# ===============================================
#              1. دوال الإحصائيات (Stats)
# ===============================================

def load_stats():
    """تحميل الإحصائيات من ملف JSON."""
    if not os.path.exists(STATS_FILE):
        return {"total_downloads": 0, "users": {}}
    try:
        with open(STATS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ خطأ في تحميل الإحصائيات: {e}")
        return {"total_downloads": 0, "users": {}}

def save_stats(stats):
    """حفظ الإحصائيات إلى ملف JSON."""
    try:
        with open(STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(stats, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"❌ خطأ في حفظ الإحصائيات: {e}")

def update_user_stats(user_data, platform_key):
    """تحديث إحصائيات مستخدم محدد وزيادة عدد التنزيلات الإجمالي."""
    stats = load_stats()
    user_id = str(user_data.id)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # تحديث بيانات المستخدم
    user_entry = stats['users'].get(user_id, {
        "first_name": user_data.first_name,
        "username": user_data.username,
        "join_date": now_str,
        "download_count": 0,
        "platform_downloads": defaultdict(int) 
    })
    
    # تحديث عداد التنزيلات لهذا المستخدم والمنصة
    user_entry['download_count'] += 1
    user_entry['last_activity'] = now_str
    
    # لضمان التحويل الصحيح عند التحميل من الملف (defaultdict لا يعمل مع JSON مباشرة)
    platform_downloads = user_entry.get('platform_downloads', {})
    platform_downloads[platform_key] = platform_downloads.get(platform_key, 0) + 1
    user_entry['platform_downloads'] = dict(platform_downloads)

    stats['users'][user_id] = user_entry
    stats['total_downloads'] = stats.get('total_downloads', 0) + 1
    
    save_stats(stats)


# ===============================================
#              2. دالة التحقق من الاشتراك الإجباري
# ===============================================

def is_subscribed(user_id):
    """التحقق مما إذا كان المستخدم مشتركًا في القناة الإجبارية."""
    try:
        member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        # إذا كان العضو ليس "left" أو "banned"، فهو مشترك
        if member.status not in ['left', 'banned']:
            return True
        return False
    except Exception as e:
        # غالباً يحدث خطأ إذا كانت القناة خاصة أو اسم المستخدم خاطئ
        print(f"❌ خطأ في التحقق من الاشتراك: {e}")
        return False

def send_force_subscribe_message(chat_id):
    """إرسال رسالة الاشتراك الإجباري."""
    markup = types.InlineKeyboardMarkup()
    channel_btn = types.InlineKeyboardButton("اشترك في القناة 📢", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")
    check_btn = types.InlineKeyboardButton("✅ لقد اشتركت (تحقق)", callback_data="check_subscription")
    markup.row(channel_btn)
    markup.row(check_btn)
    
    bot.send_message(
        chat_id,
        f"🚨 **يجب عليك الاشتراك في القناة أولاً للمتابعة!**\n\nاضغط على الزر أدناه للاشتراك ثم اضغط 'لقد اشتركت (تحقق)'.\n\nالقناة: {CHANNEL_USERNAME}",
        parse_mode='HTML',
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data == 'check_subscription')
def check_subscription_callback(call):
    """معالجة النقر على زر 'تحقق من الاشتراك'."""
    if is_subscribed(call.from_user.id):
        bot.answer_callback_query(call.id, "✅ تم التحقق بنجاح! يمكنك الآن إرسال الرابط.")
        # تحديث الرسالة لتبدو كأنها صفحة الترحيب مجدداً
        send_welcome(call.message)
    else:
        bot.answer_callback_query(call.id, "❌ لم يتم العثور على اشتراكك بعد. يرجى الاشتراك والمحاولة مجدداً.")
        # إعادة إرسال رسالة الاشتراك لضمان ظهور الأزرار
        send_force_subscribe_message(call.message.chat.id)


# ===============================================
#              3. لوحة التحكم (Admin Panel)
# ===============================================

@bot.message_handler(commands=["admin"])
def admin_panel(message):
    """عرض لوحة التحكم والإحصائيات للمطور فقط."""
    if str(message.chat.id) != DEVELOPER_USER_ID:
        bot.send_message(message.chat.id, "❌ غير مصرح لك بالوصول إلى لوحة التحكم.", parse_mode='HTML')
        return

    stats = load_stats()
    total_users = len(stats['users'])
    total_downloads = stats['total_downloads']
    
    # حساب أعلى المستخدمين تنزيلاً
    sorted_users = sorted(
        stats['users'].items(), 
        key=lambda item: item[1]['download_count'], 
        reverse=True
    )[:5] # أعلى 5 مستخدمين

    # بناء رسالة التقرير
    report = f"📊 **لوحة تحكم وإحصائيات البوت**\n\n"
    report += f"👤 **إجمالي المستخدمين:** {total_users}\n"
    report += f"📥 **إجمالي التنزيلات:** {total_downloads}\n"
    report += f"🔗 **القناة الإجبارية:** {CHANNEL_USERNAME}\n"
    
    report += f"\n🏆 **أعلى 5 مستخدمين تنزيلاً:**\n"
    if sorted_users:
        for user_id, user_data in sorted_users:
            username = f"@{user_data.get('username')}" if user_data.get('username') else user_data.get('first_name', 'مستخدم مجهول')
            report += f"  - {username} (ID: <code>{user_id}</code>): {user_data['download_count']} تنزيل.\n"
    else:
        report += "  (لا توجد إحصائيات مستخدمين بعد.)\n"
        
    report += f"\n⏱ **آخر تحديث:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    bot.send_message(message.chat.id, report, parse_mode='HTML')

# ===============================================
#              4. نقاط وصول Webhook (متبقية كما هي)
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
#              5. معالجة الأوامر الرئيسية (الواجهة)
# ===============================================

@bot.message_handler(commands=["start"])
def send_welcome(message):
    # لا داعي لإعادة فحص الاشتراك هنا، سيتم فحصه عند إرسال الرابط الفعلي
    first_name = message.from_user.first_name if message.from_user else "صديقنا"
    
    # --- تصميم أزرار مبتكر للقائمة الرئيسية ---
    markup = types.InlineKeyboardMarkup(row_width=3)
    
    # الصف الأول: المنصات المتاحة
    tt_btn = types.InlineKeyboardButton("🎶 TikTok", url="https://tiktok.com")
    ig_btn = types.InlineKeyboardButton("📸 Instagram", url="https://instagram.com")
    yt_btn = types.InlineKeyboardButton("▶️ YouTube", url="https://youtube.com")
    markup.row(tt_btn, ig_btn, yt_btn) # وضعهم في صف واحد (تصميم "علامات التبويب")

    # الصف الثاني: زر المعلومات والمطور
    settings_btn = types.InlineKeyboardButton("💡 تعليمات الاستخدام", callback_data="show_instructions")
    dev_btn = types.InlineKeyboardButton("👨‍💻 المطور", url="https://t.me/yourusername") 
    markup.row(settings_btn, dev_btn)

    bot.send_message(
        message.chat.id,
        f"""<b>مرحباً بك {first_name}!</b> 👋
        أنا **{bot.get_me().first_name}**، بوت التحميل الشامل.
        
        🚀 **ابدأ الآن:** أرسل **رابط المحتوى** الذي تريد تحميله (من TikTok، Instagram، أو YouTube) **مباشرة** في هذه الدردشة.
        
        *💡 سيقوم البوت بالتعرف على المنصة وتوفير خيارات تحميل مبتكرة.*
        """,
        parse_mode='HTML', 
        reply_markup=markup
    )
# ... بقية دوال الواجهة (show_instructions, go_to_start_menu) متبقية كما هي

@bot.callback_query_handler(func=lambda call: call.data == 'show_instructions')
def show_instructions(call):
    bot.answer_callback_query(call.id, "تعليمات الاستخدام")
    markup = types.InlineKeyboardMarkup()
    back_btn = types.InlineKeyboardButton("➡️ العودة للقائمة الرئيسية", callback_data="go_to_start_menu")
    markup.add(back_btn)
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=f"""<b>💡 دليل الاستخدام السريع:</b>
        1. قم بنسخ رابط الفيديو/المحتوى مباشرة.
        2. أرسل الرابط في هذه المحادثة.
        3. سيتم التعرف على المنصة تلقائياً.
        4. إذا كان يوتيوب، ستظهر لك مصفوفة بأزرار الجودة والصيغة المبتكرة.
        """,
        parse_mode='HTML', 
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data == 'go_to_start_menu')
def go_to_start_menu(call):
    bot.answer_callback_query(call.id)
    first_name = call.from_user.first_name if call.from_user else "صديقنا"
    
    markup = types.InlineKeyboardMarkup(row_width=3)
    tt_btn = types.InlineKeyboardButton("🎶 TikTok", url="https://tiktok.com")
    ig_btn = types.InlineKeyboardButton("📸 Instagram", url="https://instagram.com")
    yt_btn = types.InlineKeyboardButton("▶️ YouTube", url="https://youtube.com")
    markup.row(tt_btn, ig_btn, yt_btn) 

    settings_btn = types.InlineKeyboardButton("💡 تعليمات الاستخدام", callback_data="show_instructions")
    dev_btn = types.InlineKeyboardButton("👨‍💻 المطور", url="https://t.me/yourusername") 
    markup.row(settings_btn, dev_btn)

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=f"""<b>مرحباً بك {first_name}!</b> 👋
        أنا **{bot.get_me().first_name}**، بوت التحميل الشامل.
        
        🚀 **ابدأ الآن:** أرسل **رابط المحتوى** الذي تريد تحميله (من TikTok، Instagram، أو YouTube) **مباشرة** في هذه الدردشة.
        
        *💡 سيقوم البوت بالتعرف على المنصة وتوفير خيارات تحميل مبتكرة.*
        """,
        parse_mode='HTML', 
        reply_markup=markup
    )
    
# ===============================================
#              6. الدالة الرئيسية الموحدة للمعالجة
# ===============================================

@bot.message_handler(func=lambda m: True)
def process_user_link(message):
    user_url = message.text
    loading_msg = None
    
    # 0. التحقق من الاشتراك الإجباري
    if not is_subscribed(message.chat.id):
        return send_force_subscribe_message(message.chat.id)
    
    # 1. التحقق من إلغاء العملية
    if user_url.startswith('/'):
        bot.send_message(message.chat.id, "❌ تم إلغاء العملية. اضغط /start.", parse_mode='HTML')
        return 

    # 2. تحديد المنصة بناءً على الرابط
    platform_key = None
    if re.match(r'https?://(?:www\.)?(?:tiktok\.com|vt\.tiktok\.com|vm\.tiktok\.com)/', user_url):
        platform_key = 'tiktok'
    elif re.match(r'https?://(?:www\.)?instagram\.com/(?:p|reel|tv|stories)/', user_url):
        platform_key = 'instagram'
    elif re.match(r'https?://(?:www\.)?(?:youtube\.com|youtu\.be)/', user_url):
        platform_key = 'youtube'
    else:
        bot.send_message(message.chat.id, "❌ **الرابط غير صالح!** يرجى إرسال رابط صحيح.\nاضغط /start للبدء مجدداً.", parse_mode='HTML')
        return
    
    platforms = {'tiktok': 'تيك توك', 'instagram': 'إنستجرام', 'youtube': 'يوتيوب'}
    platform_name = platforms[platform_key]
    
    try:
        # 3. إرسال خيار التحويل لليوتيوب فقط باستخدام "مصفوفة التنسيقات الذكية"
        if platform_key == 'youtube':
            
            # تحديث الإحصائيات قبل إرسال خيارات التحميل
            update_user_stats(message.from_user, platform_key)
            
            message_id_key = str(message.message_id) 
            
            links = load_links()
            links[message_id_key] = user_url
            save_links(links) 
            
            # --- مصفوفة التنسيقات الذكية (Smart Format Matrix) ---
            markup = types.InlineKeyboardMarkup(row_width=2)
            
            vid_hq_btn = types.InlineKeyboardButton("💎 جودة فائقة (1080p)", callback_data=f"final_dl_{platform_key}_video_hq_{message_id_key}")
            aud_mp3_btn = types.InlineKeyboardButton("🎶 صوت نقي (MP3)", callback_data=f"final_dl_{platform_key}_audio_mp3_{message_id_key}")
            markup.row(vid_hq_btn, aud_mp3_btn)
            
            vid_std_btn = types.InlineKeyboardButton("📱 قياسي (720p/480p)", callback_data=f"final_dl_{platform_key}_video_std_{message_id_key}")
            vid_low_btn = types.InlineKeyboardButton("🌐 بيانات أقل (360p)", callback_data=f"final_dl_{platform_key}_video_low_{message_id_key}")
            markup.row(vid_std_btn, vid_low_btn)
            
            cancel_btn = types.InlineKeyboardButton("❌ إلغاء العملية", callback_data=f"cancel_download_{message_id_key}")
            markup.add(cancel_btn)
            
            bot.send_message(message.chat.id, f"✅ تم التعرف على رابط {platform_name}. **اختر الإعداد المناسب للتنزيل:**", reply_markup=markup, parse_mode='HTML')
            return
            
        # 4. بدء عملية التحميل المباشر لـ تيك توك وإنستجرام (فيديو فقط)
        
        # تحديث الإحصائيات قبل بدء التحميل المباشر
        update_user_stats(message.from_user, platform_key)
        
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
        pass

# ===============================================
#              7. معالجة التحميل النهائي (MP3/فيديو)
# ===============================================

@bot.callback_query_handler(func=lambda call: call.data.startswith('final_dl_'))
def handle_final_download(call):
    # final_dl_platform_type_format_message_id_key
    parts = call.data.split('_')
    platform_key = parts[2]
    media_type = parts[3] 
    media_format = parts[4] 
    message_id_key = parts[5] 
    
    # 0. التحقق من الاشتراك الإجباري قبل إتمام التحميل
    if not is_subscribed(call.from_user.id):
        bot.answer_callback_query(call.id, "🚨 يرجى الاشتراك في القناة أولاً للمتابعة.", show_alert=True)
        return send_force_subscribe_message(call.message.chat.id)
    
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
            text=f"<b>⏳ جارٍ التحميل/التحويل من {platform_name} ({media_format.upper()})...</b>",
            parse_mode='HTML'
        )
        
        # 2. استدعاء دالة التنزيل المتخصصة
        download_media_yt_dlp(
            bot, 
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
        pass

# ===============================================
#              8. معالجة الإلغاء
# ===============================================

@bot.callback_query_handler(func=lambda call: call.data.startswith('cancel_download_'))
def handle_cancel_download(call):
    # cancel_download_message_id_key
    message_id_key = call.data.split('_')[2]
    
    # 1. حذف الرابط المؤقت من الذاكرة
    links = load_links()
    if message_id_key in links:
        del links[message_id_key]
        save_links(links)
    
    # 2. تحديث الرسالة
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=f"✅ **تم إلغاء عملية التحميل.**\nاضغط على الأمر /start للبدء مجدداً.",
        parse_mode='HTML'
    )
    bot.answer_callback_query(call.id, "تم إلغاء العملية بنجاح.")

# ===============================================
#              9. تهيئة Webhook
# ===============================================

if __name__ == '__main__':
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL_BASE + WEBHOOK_URL_PATH)
    print('✅ البوت جاهز للتشغيل بواسطة Gunicorn...')
