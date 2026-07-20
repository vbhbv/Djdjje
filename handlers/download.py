import os
import tempfile
import yt_dlp
import json
import static_ffmpeg
import asyncio
from telegram import Update
from telegram.ext import ContextTypes

# استيراد الدالات المطلوبة من ملف الإدارة admin.py
from admin import log_action, is_user_banned

# ===============================================
#   0. تهيئة البيئة والخدمات الأساسية
# ===============================================

# تفعيل مسارات FFmpeg تلقائياً
try:
    static_ffmpeg.add_paths()
except Exception as e:
    print(f"⚠️ تنبيه أثناء إعداد static_ffmpeg: {e}")

TEMP_STORAGE_FILE = 'temp_links.json' 

def load_links():
    """تحميل جميع الروابط المخزنة من ملف JSON بصورة آمنة."""
    if os.path.exists(TEMP_STORAGE_FILE):
        try:
            with open(TEMP_STORAGE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ فشل قراءة {TEMP_STORAGE_FILE}: {e}")
            return {}
    return {}

def save_links(data):
    """حفظ الروابط الحالية إلى ملف JSON."""
    try:
        with open(TEMP_STORAGE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ فشل حفظ البيانات في ملف JSON: {e}")

# ===============================================
#              1. دالة التحميل الرئيسية
# ===============================================

async def download_media_yt_dlp(bot, chat_id, url, platform_name, loading_msg_id, download_as_mp3=False):
    """
    دالة التحميل والتحويل من التيك توك، إنستغرام، ويوتيوب.
    مدمجة مع نظام تسجيل الإحصائيات وفحص الحظر من PostgreSQL.
    """
    
    # 1. التحقق الفوري من الحظر قبل البدء
    if await is_user_banned(chat_id):
        try:
            await bot.edit_message_text(
                chat_id=chat_id, 
                message_id=loading_msg_id, 
                text="🚫 **عذراً، حسابك محظور من استخدام البوت.**", 
                parse_mode='Markdown'
            )
        except Exception:
            pass
        return False

    # 2. تنظيف القرص تلقائياً عبر TemporaryDirectory
    with tempfile.TemporaryDirectory() as tmpdir:
        output_template = os.path.join(tmpdir, 'download.%(ext)s')
        
        ydl_opts = {
            'outtmpl': output_template,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'cookiefile': None,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios']
                }
            },
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            },
            'max_filesize': 500 * 1024 * 1024, # حد 500 ميغابايت
        }
        
        if download_as_mp3:
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128',
            }]
            ydl_opts['postprocessor_args'] = [
                '-threads', '2',
                '-preset', 'ultrafast'
            ]
        else:
            ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'

        action_type = "download_mp3" if download_as_mp3 else "download_video"

        try:
            # تشغيل التحميل في Executor منفصل حتى لا يتوقف البوت عن الاستجابة
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                loop = asyncio.get_event_loop()
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
                downloaded_file = ydl.prepare_filename(info)
                
                if download_as_mp3:
                    downloaded_file = os.path.splitext(downloaded_file)[0] + '.mp3'

            # مسح رسالة التحميل
            try:
                await bot.delete_message(chat_id, loading_msg_id)
            except Exception:
                pass

            # إرسال الملف للمستخدم
            CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "")
            caption_text = f"✅ تم التحميل من {platform_name}"
            if CHANNEL_USERNAME:
                caption_text += f" بواسطة: {CHANNEL_USERNAME}"
            
            if os.path.exists(downloaded_file):
                file_size_mb = os.path.getsize(downloaded_file) / (1024 * 1024)
                if file_size_mb > 50:
                    await bot.send_message(
                        chat_id, 
                        f"⚠️ <b>حجم الملف كبير جداً ({file_size_mb:.1f} MB)!</b>\nحد الرفع المسموح عبر التلجرام هو 50MB.", 
                        parse_mode='HTML'
                    )
                    return False

                with open(downloaded_file, 'rb') as f:
                    if download_as_mp3:
                        await bot.send_audio(chat_id, f, caption=f'<b>{caption_text}</b>', parse_mode='HTML')
                    else:
                        await bot.send_video(chat_id, f, caption=f'<b>{caption_text}</b>', parse_mode='HTML', supports_streaming=True)
                
                # تسجيل العملية الناجحة في جدول stats_log
                await log_action(f"{platform_name}_{action_type}_success")
                return True
            else:
                raise Exception("لم يتم العثور على الملف بعد الانتهاء من التحميل.")

        except Exception as e:
            try:
                await bot.delete_message(chat_id, loading_msg_id)
            except Exception:
                pass
            
            await log_action(f"{platform_name}_{action_type}_failed")
            raise e
