import os
import json
import logging
import asyncio
import glob
import urllib.parse
import yt_dlp
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)

# مسار ملف JSON لتخزين الروابط مؤقتاً
LINKS_FILE = "temp_links.json"

# ===============================================
#          1. إدارة الروابط المؤقتة (JSON)
# ===============================================

def load_links() -> dict:
    """تحميل الروابط المحفوظة مؤقتاً من ملف JSON"""
    if not os.path.exists(LINKS_FILE):
        return {}
    try:
        with open(LINKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"خطأ أثناء قراءة ملف الروابط: {e}")
        return {}

def save_links(links: dict):
    """حفظ الروابط في ملف JSON"""
    try:
        with open(LINKS_FILE, "w", encoding="utf-8") as f:
            json.dump(links, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"خطأ أثناء حفظ ملف الروابط: {e}")

# ===============================================
#          2. دالة التحميل والمعالجة الرئيسية
# ===============================================

async def download_media_yt_dlp(
    bot: Bot, 
    chat_id: int, 
    url: str, 
    platform_name: str, 
    status_msg_id: int, 
    download_as_mp3: bool = False
):
    """
    تحميل الوسائط باستخدام yt-dlp وإرسالها مباشرة مع زر المشاركة ويوزر البوت
    """
    download_dir = "downloads"
    os.makedirs(download_dir, exist_ok=True)
    
    # قالب حفظ الملف باسم المعرف فريد لمنع التداخل
    out_template = os.path.join(download_dir, "%(id)s.%(ext)s")

    # إعدادات التنزيل المباشر
    if download_as_mp3:
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': out_template,
            'quiet': True,
            'no_warnings': True,
        }
    else:
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': out_template,
            'quiet': True,
            'no_warnings': True,
        }

    loop = asyncio.get_running_loop()
    
    def _extract_and_download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_id = info.get('id')
            title = info.get('title', 'Media')
            
            # البحث عن الملف الذي تم تنزيله باستخدام ID المقترن به
            search_pattern = os.path.join(download_dir, f"{video_id}.*")
            matching_files = glob.glob(search_pattern)
            
            if matching_files:
                return matching_files[0], title
            
            # خيار احتياطي في حال عدم تطابق الامتداد
            filename = ydl.prepare_filename(info)
            return filename, title

    file_path = None
    try:
        # تشغيل التنزيل داخل Executor
        file_path, title = await loop.run_in_executor(None, _extract_and_download)

        if not file_path or not os.path.exists(file_path):
            raise FileNotFoundError("لم يتم العثور على الملف بعد التنزيل.")

        # تجهيز زر مشاركة البوت مع الأصدقاء
        share_text = urllib.parse.quote("جرب هذا البوت الممتاز لتنزيل الفيديوهات والصوتيات من مختلف المنصات! ⚡")
        share_url = f"https://t.me/share/url?url=https://t.me/Seagebot&text={share_text}"
        
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("مشاركة مع الأصدقاء", url=share_url)]
        ])

        # إرسال الملف بناءً على الخيار المحدد مع يوزر البوت وزر المشاركة
        with open(file_path, 'rb') as media_file:
            if download_as_mp3:
                caption_text = f"🎵 **{title}**\n\n@Seagebot"
                await bot.send_audio(
                    chat_id=chat_id,
                    audio=media_file,
                    title=title,
                    caption=caption_text,
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
            else:
                caption_text = f"🎥 **{title}**\n\n@Seagebot"
                await bot.send_video(
                    chat_id=chat_id,
                    video=media_file,
                    caption=caption_text,
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )

        # حذف رسالة "جارٍ التحميل..." عند الانتهاء
        try:
            await bot.delete_message(chat_id=chat_id, message_id=status_msg_id)
        except Exception:
            pass

    except Exception as e:
        logger.error(f"خطأ أثناء معالجة الرابط {url}: {e}")
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg_id,
                text=f"❌ **حدث خطأ أثناء التحميل:**\n`{str(e).splitlines()[0]}`",
                parse_mode='Markdown'
            )
        except Exception:
            pass

    finally:
        # إزالة الملفات المؤقتة من المجلد فور إرسالها
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as clean_err:
                logger.warning(f"فشل حذف الملف المؤقت {file_path}: {clean_err}")
