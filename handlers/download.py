import os
import tempfile
import yt_dlp
import json

# ===============================================
#              0. دوال التخزين الدائم (Persistent Storage)
# ===============================================

# 🚨 ملف JSON للتخزين الدائم لروابط يوتيوب (لمنع انتهاء الصلاحية)
TEMP_STORAGE_FILE = 'temp_links.json' 

def load_links():
    """تحميل جميع الروابط المخزنة من ملف JSON."""
    if os.path.exists(TEMP_STORAGE_FILE):
        try:
            with open(TEMP_STORAGE_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}
    return {}

def save_links(data):
    """حفظ الروابط الحالية إلى ملف JSON."""
    try:
        with open(TEMP_STORAGE_FILE, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print(f"❌ فشل حفظ البيانات في ملف JSON: {e}")

# ===============================================
#              1. دالة التحميل الرئيسية
# ===============================================

def download_media_yt_dlp(bot, chat_id, url, platform_name, loading_msg_id, download_as_mp3=False):
    """
    دالة متخصصة للتحميل المباشر باستخدام yt-dlp وإرسال الملف.
    تستخدم مسار مؤقت لضمان حذف الملفات بعد الإرسال.
    """
    
    # 🧹 الضمانة التقنية للحذف التلقائي
    with tempfile.TemporaryDirectory() as tmpdir:
        output_ext = 'mp3' if download_as_mp3 else 'mp4'
        file_path = os.path.join(tmpdir, f'download.{output_ext}')
        
        ydl_opts = {
            'outtmpl': file_path,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'cookiefile': None,
            'format': 'bestaudio/best' if download_as_mp3 else 'best[ext=mp4]/best',
        }
        
        # إضافة خيارات التحويل لـ MP3
        if download_as_mp3:
             ydl_opts['postprocessors'] = [{
                 'key': 'FFmpegExtractAudio',
                 'preferredcodec': 'mp3',
                 'preferredquality': '192',
             }]

        # بدء التنزيل/التحويل
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True) 
        
        # حذف رسالة "جاري التحميل"
        bot.delete_message(chat_id, loading_msg_id)
        
        # الإرسال إلى تيليجرام
        CHANNEL_USERNAME = "@SuPeRx1" 
        caption_text = f"✅ تم التحميل من {platform_name} بواسطة: {CHANNEL_USERNAME}" 
        
        if os.path.exists(file_path):
             with open(file_path, 'rb') as f:
                if download_as_mp3:
                    bot.send_audio(chat_id, f, caption=f'<b>{caption_text}</b>', parse_mode='HTML')
                else:
                    bot.send_video(chat_id, f, caption=f'<b>{caption_text}</b>', parse_mode='HTML', supports_streaming=True)
             return True
        else:
             raise Exception(f"فشل yt-dlp في حفظ أو إيجاد الملف بعد التنزيل كـ {output_ext}.")
