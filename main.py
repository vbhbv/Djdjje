import os
import logging
import asyncio
import asyncpg
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, constants
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# ===============================================
#              0. إعدادات قاعدة البيانات
# ===============================================

DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

pool = None

async def get_db_pool():
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(DATABASE_URL)
    return pool

async def init_db():
    """إنشاء الجداول المطلوبة في PostgreSQL"""
    p = await get_db_pool()
    async with p.acquire() as conn:
        # جدول المستخدمين
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                is_banned BOOLEAN DEFAULT FALSE,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # جدول قنوات الاشتراك الإجباري
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                channel_id BIGINT PRIMARY KEY,
                invite_link TEXT,
                button_title TEXT
            )
        ''')
        # جدول متتبع حالة الإدارة (للإذاعة والحظر)
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS admin_state (
                admin_id BIGINT PRIMARY KEY,
                state TEXT
            )
        ''')
    logger.info("✅ تم الاتصال بقاعدة البيانات PostgreSQL وتهيئة الجداول بنجاح.")

# ===============================================
#             1. دالات المستخدمين والحظر
# ===============================================

async def register_user(user_id: int, username: str):
    p = await get_db_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            INSERT INTO users (user_id, username)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username
        ''', user_id, username)

async def is_user_banned(user_id: int) -> bool:
    p = await get_db_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow('SELECT is_banned FROM users WHERE user_id = $1', user_id)
        return row['is_banned'] if row else False

async def set_user_ban(user_id: int, ban_status: bool):
    p = await get_db_pool()
    async with p.acquire() as conn:
        await conn.execute('UPDATE users SET is_banned = $1 WHERE user_id = $2', ban_status, user_id)

# ===============================================
#          2. دالات الاشتراك الإجباري
# ===============================================

async def get_channels():
    p = await get_db_pool()
    async with p.acquire() as conn:
        return await conn.fetch('SELECT channel_id, invite_link, button_title FROM channels')

async def add_channel(channel_id: int, invite_link: str, button_title: str):
    p = await get_db_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            INSERT INTO channels (channel_id, invite_link, button_title)
            VALUES ($1, $2, $3)
            ON CONFLICT (channel_id) DO UPDATE SET invite_link = $2, button_title = $3
        ''', channel_id, invite_link, button_title)

async def delete_channel(channel_id: int):
    p = await get_db_pool()
    async with p.acquire() as conn:
        await conn.execute('DELETE FROM channels WHERE channel_id = $1', channel_id)

async def check_force_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """فحص اشتراك المستخدم في القنوات الإجبارية"""
    channels = await get_channels()
    if not channels:
        return True

    user_id = update.effective_user.id
    unsubscribed_channels = []

    for ch in channels:
        try:
            member = await context.bot.get_chat_member(chat_id=ch['channel_id'], user_id=user_id)
            if member.status in ['left', 'kicked']:
                unsubscribed_channels.append(ch)
        except Exception as e:
            logger.warning(f"تعذر الفحص في القناة {ch['channel_id']}: {e}")

    if unsubscribed_channels:
        keyboard = []
        for ch in unsubscribed_channels:
            keyboard.append([InlineKeyboardButton(ch['button_title'], url=ch['invite_link'])])
        keyboard.append([InlineKeyboardButton("تحقق من الاشتراك 🔄", callback_data="check_subscription")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        msg_text = "⚠️ **عذراً عزيزي، يجب عليك الاشتراك في القنوات التالية لاستخدام البوت:**"

        if update.message:
            await update.message.reply_text(msg_text, reply_markup=reply_markup, parse_mode='Markdown')
        elif update.callback_query:
            await update.callback_query.message.reply_text(msg_text, reply_markup=reply_markup, parse_mode='Markdown')
        return False

    return True

# ===============================================
#             3. لوحة التحكم للإدارة
# ===============================================

async def admin_panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """فتح لوحة تحكم الإدارة"""
    if update.effective_user.id != ADMIN_ID:
        return

    keyboard = [
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="admin_stats"), InlineKeyboardButton("📢 إذاعة للمستخدمين", callback_data="admin_broadcast")],
        [InlineKeyboardButton("➕ إضافة قناة اشتراك", callback_data="admin_add_channel"), InlineKeyboardButton("❌ حذف قناة اشتراك", callback_data="admin_del_channel")],
        [InlineKeyboardButton("🚫 حظر مستخدم", callback_data="admin_ban_user"), InlineKeyboardButton("✅ إلغاء حظر مستخدم", callback_data="admin_unban_user")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("⚙️ **أهلاً بك في لوحة تحكم الأدمن:**", reply_markup=reply_markup, parse_mode='Markdown')

async def set_admin_state(admin_id: int, state: str):
    p = await get_db_pool()
    async with p.acquire() as conn:
        await conn.execute('''
            INSERT INTO admin_state (admin_id, state) VALUES ($1, $2)
            ON CONFLICT (admin_id) DO UPDATE SET state = $2
        ''', admin_id, state)

async def get_admin_state(admin_id: int) -> str:
    p = await get_db_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow('SELECT state FROM admin_state WHERE admin_id = $1', admin_id)
        return row['state'] if row else None

# ===============================================
#        4. معالجة التفاعلات ورسالة التفعيل
# ===============================================

async def handle_admin_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id

    # 🎯 هنا تم التعديل لتصبح نفس رسالة /start تماماً
    if data == "check_subscription":
        await query.answer()
        is_sub = await check_force_subscribe(update, context)
        if is_sub:
            await query.message.delete()
            first_name = query.from_user.first_name
            
            # نفس النص الخاص بأمر /start
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"<b>مرحباً بك {first_name}!</b> 👋\n\n"
                     f"أنا بوت التحميل السريع من (تيك توك، إنستغرام، يوتيوب).\n"
                     f"أرسل رابط الميديا مباشرة وسأعطيك خيارات التحميل صوت أو فيديو! 🚀",
                parse_mode=constants.ParseMode.HTML
            )
        return

    if user_id != ADMIN_ID:
        await query.answer("عذراً، هذا الأمر مخصص للإدارة فقط.", show_alert=True)
        return

    if data == "admin_stats":
        p = await get_db_pool()
        async with p.acquire() as conn:
            total_users = await conn.fetchval('SELECT COUNT(*) FROM users')
            banned_users = await conn.fetchval('SELECT COUNT(*) FROM users WHERE is_banned = TRUE')
            channels_count = await conn.fetchval('SELECT COUNT(*) FROM channels')
        
        await query.edit_message_text(
            f"📊 **إحصائيات البوت:**\n\n"
            f"👤 عدد المستخدمين الكلي: `{total_users}`\n"
            f"🚫 المحظورين: `{banned_users}`\n"
            f"📢 قنوات الاشتراك الإجباري: `{channels_count}`",
            parse_mode='Markdown'
        )

    elif data == "admin_broadcast":
        await set_admin_state(user_id, "WAITING_BROADCAST")
        await query.edit_message_text("📢 **أرسل الآن الرسالة (نص أو ميديا) التي تريد إذاعتها لجميع المستخدمين:**", parse_mode='Markdown')

    elif data == "admin_add_channel":
        await set_admin_state(user_id, "WAITING_ADD_CHANNEL")
        await query.edit_message_text(
            "➕ **لإضافة قناة اشتراك إجباري جديدة:**\n\n"
            "أرسل البيانات مفصولة بفاصلة كالتالي:\n"
            "`ID_القناة, رابط_الدعوة, اسم_الزر`\n\n"
            "💡 مثال:\n`-1001617871951, https://t.me/iiollr, اشترك في القناة 📢`",
            parse_mode='Markdown'
        )

    elif data == "admin_del_channel":
        channels = await get_channels()
        if not channels:
            await query.edit_message_text("❌ لا توجد قنوات اشتراك إجباري حالياً.")
            return

        keyboard = []
        for ch in channels:
            keyboard.append([InlineKeyboardButton(f"❌ حذف {ch['button_title']}", callback_data=f"del_ch_{ch['channel_id']}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("اختر القناة التي تريد حذفها:", reply_markup=reply_markup)

    elif data.startswith("del_ch_"):
        ch_id = int(data.split("_")[2])
        await delete_channel(ch_id)
        await query.edit_message_text("✅ تم حذف القناة بنجاح.")

    elif data == "admin_ban_user":
        await set_admin_state(user_id, "WAITING_BAN_ID")
        await query.edit_message_text("🚫 أرسل **آيدي (ID) المستخدم** الذي تريد حظره:", parse_mode='Markdown')

    elif data == "admin_unban_user":
        await set_admin_state(user_id, "WAITING_UNBAN_ID")
        await query.edit_message_text("✅ أرسل **آيدي (ID) المستخدم** الذي تريد إلغاء حظره:", parse_mode='Markdown')

# ===============================================
#             5. معالجة مدخلات الإدارة
# ===============================================

async def handle_admin_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return False

    state = await get_admin_state(user_id)
    if not state:
        return False

    text = update.message.text.strip() if update.message.text else ""

    if state == "WAITING_BROADCAST":
        await set_admin_state(user_id, "")
        await update.message.reply_text("⏳ جارٍ بدء الإذاعة...")
        
        p = await get_db_pool()
        async with p.acquire() as conn:
            users = await conn.fetch('SELECT user_id FROM users WHERE is_banned = FALSE')
        
        success, failed = 0, 0
        for u in users:
            try:
                await update.message.copy(chat_id=u['user_id'])
                success += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1

        await update.message.reply_text(f"✅ **تمت الإذاعة بنجاح!**\n\n🎯 وصلت: `{success}`\n❌ فشلت: `{failed}`", parse_mode='Markdown')
        return True

    elif state == "WAITING_ADD_CHANNEL":
        await set_admin_state(user_id, "")
        try:
            parts = [p.strip() for p in text.split(',')]
            ch_id = int(parts[0])
            link = parts[1]
            title = parts[2]
            
            await add_channel(ch_id, link, title)
            await update.message.reply_text(f"✅ **تمت إضافة القناة بنجاح!**\n\n📌 **الاسم:** {title}\n🆔 **ID:** `{ch_id}`", parse_mode='Markdown')
        except Exception as e:
            await update.message.reply_text(f"❌ **خطأ في التنسيق!** تأكد من إرسال البيانات بالصيغة الصحيحة:\n`ID_القناة, رابط_الدعوة, اسم_الزر`\n\nالخطأ: `{e}`", parse_mode='Markdown')
        return True

    elif state == "WAITING_BAN_ID":
        await set_admin_state(user_id, "")
        try:
            target_id = int(text)
            await set_user_ban(target_id, True)
            await update.message.reply_text(f"🚫 تم حظر المستخدم `{target_id}` بنجاح.", parse_mode='Markdown')
        except ValueError:
            await update.message.reply_text("❌ الآيدي غير صحيح!")
        return True

    elif state == "WAITING_UNBAN_ID":
        await set_admin_state(user_id, "")
        try:
            target_id = int(text)
            await set_user_ban(target_id, False)
            await update.message.reply_text(f"✅ تم إلغاء حظر المستخدم `{target_id}` بنجاح.", parse_mode='Markdown')
        except ValueError:
            await update.message.reply_text("❌ الآيدي غير صحيح!")
        return True

    return False
