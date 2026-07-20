import os
import tempfile
import yt_dlp
import json
import static_ffmpeg

# ===============================================
#   0. تهيئة البيئة والخدمات الأساسية
# ===============================================

# 🚀 تفعيل مسارات FFmpeg تلقائياً عند بدء التشغيل
try:
    static_ffmpeg.add_paths()
except Exception as e:
    print(f"⚠️ تنبيه أثناء إعداد static_ffmpeg: {e}")

# 🚨 ملف JSON للتخزين الدائم لروابط يوتيوب
TEMP_STORAGE_FILE = 'temp_links.json' 

def load_links():
    """تحميل جميع الروابط المخزنة من ملف JSON بصورة آمنة."""
    if os.path.exists(TEMP_STORAGE_FILE):
        try:
            with open(TEMP_STORAGE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError, Exception) as e:
            print(f"⚠️ فشل قراءة {TEMP_STORAGE_FILE}: {e}")
            return {}
    return {}

def save_links(data):
    """حفظ الروابط الحالية إلى ملف JSON مع ضمان الترميز الموحد."""
    try:
        with open(TEMP_STORAGE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ فشل حفظ البيانات في ملف JSON: {e}")

# ===============================================
#              1. دالة التحميل الرئيسية
# ===============================================

def download_media_yt_dlp(bot, chat_id, url, platform_name, loading_msg_id, download_as_mp3=False):
    """
    دالة متخصصة للتحميل المباشر باستخدام yt-dlp وإرسال الملف.
    تستخدم مساراً مؤقتاً لضمان حذف الملفات فوراً بعد الإرسال لحماية موارد السيرفر.
    """
    
    # 🧹 استخدام TemporaryDirectory لتنظيف القرص فور انتهاء العملية
    with tempfile.TemporaryDirectory() as tmpdir:
        output_template = os.path.join(tmpdir, 'download.%(ext)s')
        
        ydl_opts = {
            'outtmpl': output_template,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'cookiefile': None,
            # 💡 تجاوز قيود يوتيوب عبر عميل الهاتف
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios']
                }
            },
            # 💡 ترويسة متصفح طبيعية لتفادي الحظر
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            },
            # 💡 حماية السيرفر من استنزاف الحجم (الحد الأقصى 500 ميجابايت)
            'max_filesize': 500 * 1024 * 1024,
        }
        
        if download_as_mp3:
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        else:
            # تفضيل صيغ mp4 المتوافقة مباشرة مع المشغلات
            ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'

        try:
            # 1. بدء التنزيل/التحويل عبر yt-dlp
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                # استخراج المسار الفعلي للملف المحمل
                downloaded_file = ydl.prepare_filename(info)
                if download_as_mp3:
                    # تعديل امتداد المسار عند التحويل لـ MP3
                    downloaded_file = os.path.splitext(downloaded_file)[0] + '.mp3'

            # 2. حذف رسالة "جاري التحميل" لتنظيف الشات
            try:
                bot.delete_message(chat_id, loading_msg_id)
            except Exception:
                pass

            # 3. التأكد من وجود الملف وإرساله لتيليجرام
            CHANNEL_USERNAME = "@SuPeRx1" 
            caption_text = f"✅ تم التحميل من {platform_name} بواسطة: {CHANNEL_USERNAME}" 
            
            if os.path.exists(downloaded_file):
                # فحص حجم الملف لضمان عدم تجاوز حدود تيليجرام (50MB)
                file_size_mb = os.path.getsize(downloaded_file) / (1024 * 1024)
                if file_size_mb > 50:
                    bot.send_message(
                        chat_id, 
                        f"⚠️ <b>حجم الملف كبير جداً ({file_size_mb:.1f} MB)!</b>\nحد الرفع المسموح للبوتات هو 50MB.", 
                        parse_mode='HTML'
                    )
                    return False

                with open(downloaded_file, 'rb') as f:
                    if download_as_mp3:
                        bot.send_audio(
                            chat_id, 
                            f, 
                            caption=f'<b>{caption_text}</b>', 
                            parse_mode='HTML'
                        )
                    else:
                        bot.send_video(
                            chat_id, 
                            f, 
                            caption=f'<b>{caption_text}</b>', 
                            parse_mode='HTML', 
                            supports_streaming=True
                        )
                return True
            else:
                raise Exception(f"لم يتم العثور على الملف بعد انتهاء عملية yt-dlp.")

        except Exception as e:
            # مسح رسالة التحميل في حال حدث الخطأ داخل التكتل
            try:
                bot.delete_message(chat_id, loading_msg_id)
            except Exception:
                pass
            raise e
