import os
import json
import logging
import asyncio
import glob
import re
import urllib.parse
import yt_dlp
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)

LINKS_FILE = "temp_links.json"

def load_links() -> dict:
    if not os.path.exists(LINKS_FILE):
        return {}
    try:
        with open(LINKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"خطأ أثناء قراءة ملف الروابط: {e}")
        return {}

def save_links(links: dict):
    try:
        with open(LINKS_FILE, "w", encoding="utf-8") as f:
            json.dump(links, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"خطأ أثناء حفظ ملف الروابط: {e}")

def clean_title(title: str) -> str:
    """تنظيف العناوين التلقائية والكلايش المزعجة من المنصات"""
    if not title:
        return ""
    
    if re.search(r'TikTok video #\d+', title, re.IGNORECASE):
        return ""
    if re.search(r'Video by', title, re.IGNORECASE):
        return ""
    
    return title.strip()

async def download_media_yt_dlp(
    bot: Bot, 
    chat_id: int, 
    url: str, 
    platform_name: str, 
    status_msg_id: int, 
    download_as_mp3: bool = False
):
    download_dir = "downloads"
    os.makedirs(download_dir, exist_ok=True)
    
    out_template = os.path.join(download_dir, "%(id)s.%(ext)s")

    # التعديل الأقوى: إعدادات متقدمة جداً لمنع كشف السيرفرات والتغلب على حظر إنستغرام
    base_headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9,ar;q=0.8',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'cross-site',
        'Sec-Fetch-Dest': 'document',
    }

    # الإعدادات الأساسية الشاملة
    ydl_opts_primary = {
        'outtmpl': out_template,
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'geo_bypass': True,
        'check_formats': False,
        'extractor_args': {
            'instagram': {
                'refer_to_author': True,
            }
        },
        'http_headers': base_headers,
    }

    if download_as_mp3:
        ydl_opts_primary['format'] = 'bestaudio/best'
    else:
        ydl_opts_primary['format'] = 'best[ext=mp4]/best'

    loop = asyncio.get_running_loop()
    
    def _extract_and_download():
        # المحاولة الأولى بالخيارات المتقدمة
        try:
            with yt_dlp.YoutubeDL(ydl_opts_primary) as ydl:
                info = ydl.extract_info(url, download=True)
                video_id = info.get('id')
                raw_title = info.get('title', '')
                cleaned = clean_title(raw_title)
                
                search_pattern = os.path.join(download_dir, f"{video_id}.*")
                matching_files = glob.glob(search_pattern)
                if matching_files:
                    return matching_files[0], cleaned
                return ydl.prepare_filename(info), cleaned
        except Exception as primary_error:
            logger.warning(f"المحاولة الأولى فشلت: {primary_error}، جاري بدء المحاولة البديلة...")
            
            # المحاولة الثانية (Fall-back) بتغيير المتصفح والمستخرج للتغلب على الحظر القوي
            ydl_opts_secondary = ydl_opts_primary.copy()
            ydl_opts_secondary['http_headers']['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
            ydl_opts_secondary['format'] = 'best'
            
            with yt_dlp.YoutubeDL(ydl_opts_secondary) as ydl_sec:
                info = ydl_sec.extract_info(url, download=True)
                video_id = info.get('id')
                raw_title = info.get('title', '')
                cleaned = clean_title(raw_title)
                
                search_pattern = os.path.join(download_dir, f"{video_id}.*")
                matching_files = glob.glob(search_pattern)
                if matching_files:
                    return matching_files[0], cleaned
                return ydl_sec.prepare_filename(info), cleaned

    file_path = None
    try:
        file_path, title = await loop.run_in_executor(None, _extract_and_download)

        if not file_path or not os.path.exists(file_path):
            raise FileNotFoundError("لم يتم العثور على الملف بعد التنزيل.")

        share_text = urllib.parse.quote("جرب هذا البوت الممتاز لتنزيل الفيديوهات والصوتيات من مختلف المنصات! ⚡")
        share_url = f"https://t.me/share/url?url=https://t.me/Seagebot&text={share_text}"
        
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 مشاركة مع الأصدقاء", url=share_url)]
        ])

        if download_as_mp3:
            caption_text = f"🎵 **{title}**\n\n@Seagebot" if title else "@Seagebot"
            with open(file_path, 'rb') as media_file:
                await bot.send_audio(
                    chat_id=chat_id,
                    audio=media_file,
                    title=title or "Audio",
                    caption=caption_text,
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
        else:
            caption_text = f"🎥 **{title}**\n\n@Seagebot" if title else "@Seagebot"
            with open(file_path, 'rb') as media_file:
                await bot.send_video(
                    chat_id=chat_id,
                    video=media_file,
                    caption=caption_text,
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )

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
                text="❌ **تعذر تنزيل هذا المنشور.**\nقد يكون الحساب خاصاً (Private) أو يفرض إنستغرام حماية مؤقتة على الرابط.",
                parse_mode='Markdown'
            )
        except Exception:
            pass

    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as clean_err:
                logger.warning(f"فشل حذف الملف المؤقت {file_path}: {clean_err}")
