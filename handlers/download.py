import os
import json
import logging
import asyncio
import glob
import re
import shutil
import subprocess
import uuid
import time
import urllib.parse
import yt_dlp
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.error import TelegramError

logger = logging.getLogger(__name__)

LINKS_FILE = "temp_links.json"
BOT_USERNAME = os.getenv("BOT_USERNAME", "Seagebot")
MAX_TELEGRAM_FILE_SIZE = 50 * 1024 * 1024  # حد Bot API القياسي

# مسارات كوكيز اختيارية لكل منصة (تُرفع كملفات على Railway إن رغبت)
YOUTUBE_COOKIES_FILE = os.getenv("YOUTUBE_COOKIES_FILE", "")
INSTAGRAM_COOKIES_FILE = os.getenv("INSTAGRAM_COOKIES_FILE", "")
TIKTOK_COOKIES_FILE = os.getenv("TIKTOK_COOKIES_FILE", "")

# قفل لمنع تحميل نفس الرابط بشكل متزامن من عدة مستخدمين
_active_downloads: dict[str, asyncio.Lock] = {}
_active_downloads_guard = asyncio.Lock()


# ===============================================
#     0. التحقق من توفر ffmpeg عند تحميل الوحدة
# ===============================================

def _detect_ffmpeg() -> str | None:
    """
    يبحث عن ffmpeg في PATH أو في FFMPEG_LOCATION من البيئة.
    يُسجَّل تحذير واضح مرة واحدة عند الإقلاع بدل فشل صامت متكرر لاحقًا.
    """
    env_path = os.getenv("FFMPEG_LOCATION", "")
    if env_path and os.path.exists(env_path):
        return env_path

    found = shutil.which("ffmpeg")
    if found:
        return found

    logger.warning(
        "⚠️ ffmpeg غير موجود على هذا السيرفر. تحويل MP3 ودمج بعض جودات الفيديو "
        "لن يعمل. أضف `RUN apt-get update && apt-get install -y ffmpeg` "
        "إلى Dockerfile وأعد النشر."
    )
    return None


FFMPEG_PATH = _detect_ffmpeg()
FFMPEG_AVAILABLE = FFMPEG_PATH is not None


# ===============================================
#          1. إدارة الروابط المؤقتة (JSON)
# ===============================================

def load_links() -> dict:
    if not os.path.exists(LINKS_FILE):
        return {}
    try:
        with open(LINKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.exception("خطأ أثناء قراءة ملف الروابط")
        return {}


def save_links(links: dict):
    try:
        with open(LINKS_FILE, "w", encoding="utf-8") as f:
            json.dump(links, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.exception("خطأ أثناء حفظ ملف الروابط")


# ===============================================
#          2. أدوات مساعدة
# ===============================================

def clean_title(title: str) -> str:
    """تنظيف العناوين التلقائية والكلايش المزعجة من المنصات"""
    if not title:
        return ""
    if re.search(r'TikTok video #\d+', title, re.IGNORECASE):
        return ""
    if re.search(r'Video by', title, re.IGNORECASE):
        return ""
    return title.strip()


def _escape_markdown(text: str) -> str:
    if not text:
        return ""
    special_chars = r"_*[]()~`>#+-=|{}.!"
    for ch in special_chars:
        text = text.replace(ch, f"\\{ch}")
    return text


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def _detect_platform(url: str) -> str:
    url_l = url.lower()
    if "tiktok" in url_l:
        return "tiktok"
    if "instagram" in url_l:
        return "instagram"
    if "youtube" in url_l or "youtu.be" in url_l:
        return "youtube"
    return "generic"


async def _get_lock_for_url(url: str) -> asyncio.Lock:
    async with _active_downloads_guard:
        if url not in _active_downloads:
            _active_downloads[url] = asyncio.Lock()
        return _active_downloads[url]


# ===============================================
#     3. مجموعات إعدادات yt-dlp للتفادي والتسريع
# ===============================================

_MOBILE_UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) '
              'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1')
_DESKTOP_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
               '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
_ANDROID_UA = ('Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 '
               '(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36')


def _base_headers(user_agent: str) -> dict:
    return {
        'User-Agent': user_agent,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9,ar;q=0.8',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'cross-site',
        'Sec-Fetch-Dest': 'document',
    }


def _speed_opts() -> dict:
    """إعدادات مشتركة لتسريع التحميل عبر التوازي الحقيقي للأجزاء"""
    opts = {
        'concurrent_fragment_downloads': 8,
        'http_chunk_size': 10 * 1024 * 1024,
        'socket_timeout': 20,
        'retries': 5,
        'fragment_retries': 5,
        'retry_sleep_functions': {'http': lambda n: min(4, 0.5 * (2 ** n))},
        'max_filesize': 500 * 1024 * 1024,
        'nocheckcertificate': True,
        'geo_bypass': True,
        'check_formats': False,
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'noprogress': True,
    }
    if FFMPEG_PATH:
        opts['ffmpeg_location'] = FFMPEG_PATH
    return opts


def _cookies_for(platform: str) -> str | None:
    mapping = {
        'youtube': YOUTUBE_COOKIES_FILE,
        'instagram': INSTAGRAM_COOKIES_FILE,
        'tiktok': TIKTOK_COOKIES_FILE,
    }
    path = mapping.get(platform, "")
    return path if path and os.path.exists(path) else None


def _build_strategy_chain(out_template: str, download_as_mp3: bool, platform: str) -> list[dict]:
    """
    عدة استراتيجيات متدرجة (User-Agent + extractor client مختلفين) تُجرَّب
    بالتتابع. الترتيب يُخصَّص حسب المنصة بناءً على ملاحظات فعلية من اللوج:
    - إنستغرام: الاستراتيجية الافتراضية الأولى تفشل بثبات بدون كوكيز،
      لذا تُدفع لاحقًا لتوفير وقت.
    - تيك توك: الفشل الحالي غالبًا خلل مستخرج داخلي في yt-dlp (status code 0)
      وليس حظر IP، لذا الأولوية لاستخدام كوكيز إن توفرت + إصدار محدّث.
    """
    audio_fmt = 'bestaudio/best'
    video_fmt = 'best[ext=mp4]/best'
    fmt = audio_fmt if download_as_mp3 else video_fmt

    def strategy_mobile_ios():
        opts = {
            **_speed_opts(),
            'outtmpl': out_template,
            'format': fmt,
            'http_headers': _base_headers(_MOBILE_UA),
            'extractor_args': {'instagram': {'refer_to_author': True}},
        }
        cookies = _cookies_for(platform)
        if cookies:
            opts['cookiefile'] = cookies
        return opts

    def strategy_desktop_android_client():
        opts = {
            **_speed_opts(),
            'outtmpl': out_template,
            'format': 'best' if not download_as_mp3 else audio_fmt,
            'http_headers': _base_headers(_DESKTOP_UA),
            'extractor_args': {'youtube': {'player_client': ['android', 'tv']}},
        }
        cookies = _cookies_for(platform)
        if cookies:
            opts['cookiefile'] = cookies
        return opts

    def strategy_android_native():
        opts = {
            **_speed_opts(),
            'outtmpl': out_template,
            'format': fmt,
            'http_headers': _base_headers(_ANDROID_UA),
            'extractor_args': {'tiktok': {'app_version': ['34.1.2'], 'manifest_app_version': ['2023506030']}},
        }
        cookies = _cookies_for(platform)
        if cookies:
            opts['cookiefile'] = cookies
        return opts

    # ترتيب افتراضي
    strategies = [strategy_mobile_ios(), strategy_desktop_android_client(), strategy_android_native()]

    # إنستغرام: الاستراتيجية الأولى (mobile_ios) معروفة بالفشل الثابت هنا
    # بدون كوكيز → إن لم تتوفر كوكيز، ابدأ بالثانية مباشرة لتوفير الوقت.
    if platform == "instagram" and not _cookies_for("instagram"):
        strategies = [strategy_desktop_android_client(), strategy_mobile_ios(), strategy_android_native()]

    # تيك توك: قدّم النسخة المزوّدة بإعدادات تيك توك الخاصة أولاً
    if platform == "tiktok":
        strategies = [strategy_android_native(), strategy_mobile_ios(), strategy_desktop_android_client()]

    if download_as_mp3 and FFMPEG_AVAILABLE:
        for opts in strategies:
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
    elif download_as_mp3 and not FFMPEG_AVAILABLE:
        # لا نضيف postprocessor لأن ffmpeg غير متوفر — سنُرسل الصوت الخام
        # ونُعلم المستخدم لاحقًا بدل فشل العملية بالكامل بخطأ Postprocessing
        pass

    return strategies


# ===============================================
#          4. دالة التحميل والمعالجة الرئيسية
# ===============================================

async def download_media_yt_dlp(
    bot: Bot,
    chat_id: int,
    url: str,
    platform_name: str,
    status_msg_id: int,
    download_as_mp3: bool = False
):
    lock = await _get_lock_for_url(url)
    async with lock:
        await _run_download(bot, chat_id, url, platform_name, status_msg_id, download_as_mp3)
    async with _active_downloads_guard:
        _active_downloads.pop(url, None)


async def _run_download(
    bot: Bot,
    chat_id: int,
    url: str,
    platform_name: str,
    status_msg_id: int,
    download_as_mp3: bool,
):
    task_id = uuid.uuid4().hex[:10]
    download_dir = os.path.join("downloads", task_id)
    os.makedirs(download_dir, exist_ok=True)
    out_template = os.path.join(download_dir, "%(id)s.%(ext)s")

    platform = _detect_platform(url)
    mp3_requested_but_no_ffmpeg = download_as_mp3 and not FFMPEG_AVAILABLE

    strategies = _build_strategy_chain(out_template, download_as_mp3, platform)
    excluded_ext = {'.jpg', '.jpeg', '.png', '.webp', '.part', '.ytdl'}

    loop = asyncio.get_running_loop()

    def _extract_and_download():
        last_error = None
        for idx, opts in enumerate(strategies, start=1):
            try:
                start = time.monotonic()
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    video_id = info.get('id')
                    raw_title = info.get('title', '')
                    cleaned = clean_title(raw_title)

                    matching_files = [
                        f for f in glob.glob(os.path.join(download_dir, f"{video_id}.*"))
                        if os.path.splitext(f)[1].lower() not in excluded_ext
                        and not f.endswith('.info.json')
                    ]
                    file_path = matching_files[0] if matching_files else ydl.prepare_filename(info)
                    logger.info(f"نجحت الاستراتيجية {idx} خلال {time.monotonic() - start:.1f}ث")
                    return file_path, cleaned
            except Exception as e:
                last_error = e
                logger.warning(f"الاستراتيجية {idx}/{len(strategies)} فشلت لـ {url}: {e}")
                continue
        raise last_error or RuntimeError("فشلت جميع محاولات التحميل")

    file_path = None
    try:
        file_path, title = await loop.run_in_executor(None, _extract_and_download)

        if not file_path or not os.path.exists(file_path):
            raise FileNotFoundError("لم يتم العثور على الملف بعد التنزيل.")

        file_size = os.path.getsize(file_path)
        if file_size > MAX_TELEGRAM_FILE_SIZE:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg_id,
                text=(
                    f"⚠️ حجم الملف ({_human_size(file_size)}) أكبر من الحد المسموح "
                    f"للرفع عبر البوت ({_human_size(MAX_TELEGRAM_FILE_SIZE)})."
                ),
            )
            return

        safe_title = _escape_markdown(title)
        share_text = urllib.parse.quote("جرب هذا البوت الممتاز لتنزيل الفيديوهات والصوتيات من مختلف المنصات! ⚡")
        share_url = f"https://t.me/share/url?url=https://t.me/{BOT_USERNAME}&text={share_text}"

        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 مشاركة مع الأصدقاء", url=share_url)]
        ])

        with open(file_path, 'rb') as media_file:
            if download_as_mp3:
                note = "\n\n⚠️ تم الإرسال بالصيغة الأصلية (ffmpeg غير متوفر حاليًا)" if mp3_requested_but_no_ffmpeg else ""
                caption_text = (f"🎵 **{safe_title}**{note}\n\n@{BOT_USERNAME}"
                                 if safe_title else f"@{BOT_USERNAME}{note}")
                await bot.send_audio(
                    chat_id=chat_id,
                    audio=media_file,
                    title=title or "Audio",
                    caption=caption_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup,
                    read_timeout=120,
                    write_timeout=120,
                    connect_timeout=60,
                )
            else:
                caption_text = f"🎥 **{safe_title}**\n\n@{BOT_USERNAME}" if safe_title else f"@{BOT_USERNAME}"
                await bot.send_video(
                    chat_id=chat_id,
                    video=media_file,
                    caption=caption_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup,
                    read_timeout=120,
                    write_timeout=120,
                    connect_timeout=60,
                    supports_streaming=True,
                )

        try:
            await bot.delete_message(chat_id=chat_id, message_id=status_msg_id)
        except Exception:
            pass

    except yt_dlp.utils.DownloadError:
        logger.exception(f"فشلت جميع الاستراتيجيات لتنزيل {url}")
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg_id,
                text=(
                    "❌ **تعذر تنزيل هذا المنشور.**\n"
                    "قد يكون الحساب خاصاً (Private)، أو يفرض المصدر حماية مؤقتة، "
                    "أو أن المنصة غيّرت آلية عملها ويحتاج الأمر تحديث الأداة."
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

    except TelegramError as e:
        logger.exception(f"خطأ تيليجرام أثناء إرسال الملف من الرابط {url}")
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg_id,
                text=f"❌ فشل إرسال الملف عبر تيليجرام: {str(e)[:200]}",
            )
        except Exception:
            pass

    except Exception as e:
        logger.exception(f"خطأ عام أثناء معالجة الرابط {url}")
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg_id,
                text=f"❌ **حدث خطأ أثناء التحميل:**\n`{str(e).splitlines()[0][:200]}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

    finally:
        try:
            if os.path.isdir(download_dir):
                for f in glob.glob(os.path.join(download_dir, "*")):
                    try:
                        os.remove(f)
                    except Exception:
                        pass
                os.rmdir(download_dir)
        except Exception as clean_err:
            logger.warning(f"فشل تنظيف مجلد التحميل {download_dir}: {clean_err}")
