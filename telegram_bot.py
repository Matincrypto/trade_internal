# telegram_bot.py
import logging
import os
from dotenv import load_dotenv

# ایمپورت کتابخانه‌های تلگرام
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    ConversationHandler,
    filters,
)

# ایمپورت ابزارهای دیتابیس و امنیت
import db_utils
import security_utils

# بارگذاری متغیرهای محیطی (برای توکن تلگرام)
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# تنظیمات لاگ‌گیری
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(threadName)s - %(levelname)s - %(message)s"
)

# --- متغیرهای جهانی برای مدیریت وضعیت ---

# یک دیکشنری ساده برای نگهداری وضعیت لاگین کاربران در حافظه
# فرمت: {telegram_user_id: user_db_id}
LOGGED_IN_USERS = {}

# تعریف وضعیت‌ها (States) برای مکالمه‌ها
(   
    # ثبت نام
    REGISTER_USERNAME,
    REGISTER_PASSWORD,
    REGISTER_PASSWORD_CONFIRM,
    
    # لاگین
    LOGIN_USERNAME,
    LOGIN_PASSWORD,
    
    # افزودن کلید
    ADD_KEY_NAME,
    ADD_KEY_API_KEY,
    ADD_KEY_AMOUNT
) = range(8)

# --- توابع کمکی ---

async def delete_message_if_private(update: Update):
    """اگر چت خصوصی بود، پیام را برای امنیت حذف می‌کند (مثلاً پسورد)."""
    if update.message.chat.type == "private":
        try:
            await update.message.delete()
        except Exception as e:
            logging.warning(f"امکان حذف پیام نبود: {e}")

async def is_user_logged_in(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """بررسی می‌کند آیا کاربر لاگین کرده است یا خیر."""
    user_id = update.effective_user.id
    if user_id in LOGGED_IN_USERS:
        return True
    
    await update.message.reply_text("⛔️ شما لاگین نکرده‌اید. لطفاً ابتدا با /login وارد شوید.")
    return False

# --- ۱. دستورات پایه (Start, Help, Cancel) ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /start - نقطه شروع."""
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"سلام {user_name}!\n"
        "به ربات مدیریت معامله‌گر خوش آمدید.\n\n"
        "شما می‌توانید با دستور /register ثبت نام کنید یا با /login وارد شوید.\n\n"
        "دستورات موجود:\n"
        "/register - ثبت نام کاربر جدید\n"
        "/login - ورود به حساب کاربری\n"
        "/logout - خروج از حساب کاربری\n"
        "/help - نمایش همین پیام\n\n"
        "پس از ورود می‌توانید از دستورات مدیریتی مانند /addkey استفاده کنید."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /help."""
    await start_command(update, context) # فعلا هلپ همان استارت است

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """هر مکالمه‌ای را لغو می‌کند."""
    await update.message.reply_text(
        "عملیات لغو شد.", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

# --- ۲. مکالمه ثبت نام (/register) ---

async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """شروع فرآیند ثبت نام."""
    user_id = update.effective_user.id
    # بررسی اینکه کاربر از قبل ثبت نام نکرده باشد
    existing_user = db_utils.query_db("SELECT id FROM bot_users WHERE telegram_user_id = %s", (user_id,), fetch='one')
    if existing_user:
        await update.message.reply_text("شما قبلاً ثبت نام کرده‌اید. می‌توانید با /login وارد شوید.")
        return ConversationHandler.END
        
    await update.message.reply_text("✅ **شروع ثبت نام**\n"
"لطفاً یک نام کاربری (Username) برای خود انتخاب کنید (فقط حروف انگلیسی و اعداد).\n"
"برای لغو /cancel را بزنید."
    )
    return REGISTER_USERNAME

async def register_get_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت نام کاربری و درخواست پسورد."""
    username = update.message.text.strip()
    
    # بررسی اینکه نام کاربری قبلاً استفاده نشده باشد
    existing_user = db_utils.query_db("SELECT id FROM bot_users WHERE username = %s", (username,), fetch='one')
    if existing_user:
        await update.message.reply_text("این نام کاربری قبلاً استفاده شده. لطفاً یکی دیگر انتخاب کنید یا /cancel را بزنید.")
        return REGISTER_USERNAME # بازگشت به همین مرحله

    context.user_data['reg_username'] = username
    
    await update.message.reply_text("نام کاربری عالی! ✅\n"
"حالا یک پسورد قوی وارد کنید."
    )
    return REGISTER_PASSWORD

async def register_get_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت پسورد و درخواست تکرار آن."""
    context.user_data['reg_password'] = update.message.text
    # پیام حاوی پسورد را بلافاصله حذف می‌کنیم
    await delete_message_if_private(update) 
    
    await update.message.reply_text("✅ پسورد دریافت شد (و برای امنیت پاک شد).\n"
"لطفاً آن را مجدداً برای تایید وارد کنید."
    )
    return REGISTER_PASSWORD_CONFIRM

async def register_get_password_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """تایید پسورد، ذخیره در دیتابیس و پایان ثبت نام."""
    password_confirm = update.message.text
    password_original = context.user_data.get('reg_password')
    
    # پیام تایید را هم حذف می‌کنیم
    await delete_message_if_private(update)

    if password_confirm != password_original:
        await update.message.reply_text("❌ پسوردها مطابقت ندارند! لطفاً دوباره تلاش کنید.\n"
                                        "پسورد *اصلی* را وارد کنید:")
        # پاک کردن پسورد قبلی و بازگشت به مرحله قبل
        context.user_data.pop('reg_password', None)
        return REGISTER_PASSWORD

    # --- همه چیز درست است، ذخیره در دیتابیس ---
    try:
        username = context.user_data['reg_username']
        telegram_id = update.effective_user.id
        
        # هش کردن پسورد
        hashed_pass = security_utils.hash_password(password_original)
        
        # بررسی اینکه آیا این اولین کاربر است؟
        user_count = db_utils.query_db("SELECT COUNT(*) as count FROM bot_users", fetch='one')['count']
        is_admin = (user_count == 0) # اولین کاربر، ادمین می‌شود
        
        db_utils.query_db(
            "INSERT INTO bot_users (telegram_user_id, username, hashed_password, is_admin) VALUES (%s, %s, %s, %s)",
            (telegram_id, username, hashed_pass, is_admin)
        )
        
        await update.message.reply_text(
            f"🎉 **ثبت نام شما با موفقیت انجام شد، {username}!**\n"
            f"وضعیت ادمین: {'بله' if is_admin else 'خیر'}\n\n"
            "حالا می‌توانید با دستور /login وارد شوید."
        )
        
    except Exception as e:
        logging.error(f"خطا در ذخیره کاربر در دیتابیس: {e}")
        await update.message.reply_text("خطایی در سرور رخ داد. لطفاً بعداً تلاش کنید.")
        
    finally:
        # پاک کردن داده‌های موقت
        context.user_data.clear()
        
    return ConversationHandler.END

# --- ۳. مکالمه لاگین (/login) ---

async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """شروع فرآیند لاگین."""
    user_id = update.effective_user.id
    if user_id in LOGGED_IN_USERS:
        await update.message.reply_text("شما همین حالا لاگین هستید.")
        return ConversationHandler.END

    await update.message.reply_text(
        "▶️ **شروع ورود**\n"
        "لطفاً نام کاربری (Username) خود را وارد کنید:\n"
        "برای لغو /cancel را بزنید."
    )
    return LOGIN_USERNAME

async def login_get_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت نام کاربری و درخواست پسورد."""
    username = update.message.text.strip()
    
    # بررسی وجود کاربر
    user_record = db_utils.query_db("SELECT id, hashed_password FROM bot_users WHERE username = %s", (username,), fetch='one')
    
    if not user_record:
        await update.message.reply_text("کاربری با این نام کاربری یافت نشد. دوباره تلاش کنید یا /cancel را بزنید.")
        return LOGIN_USERNAME
        
    context.user_data['login_user_record'] = user_record
    
    await update.message.reply_text("✅ نام کاربری یافت شد.\n"
"لطفاً پسورد خود را وارد کنید."
    )
    return LOGIN_PASSWORD

async def login_get_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت پسورد، بررسی آن و لاگین کردن کاربر."""
    plain_password = update.message.text
    user_record = context.user_data.get('login_user_record')
    
    await delete_message_if_private(update) # حذف پیام حاوی پسورد

    try:
        hashed_password = user_record['hashed_password']
        
        # بررسی پسورد
        if security_utils.check_password(plain_password, hashed_password):
            # --- لاگین موفقیت آمیز ---
            telegram_id = update.effective_user.id
            user_db_id = user_record['id']
            
            # ثبت کاربر در دیکشنری لاگین‌شده‌ها
            LOGGED_IN_USERS[telegram_id] = user_db_id
            
            await update.message.reply_text("✅ **ورود با موفقیت انجام شد!**\n"
"شما اکنون به دستورات مدیریتی دسترسی دارید.\n\n"
"از /addkey برای افزودن اکانت صرافی استفاده کنید."
            )
            return ConversationHandler.END
        else:
            await update.message.reply_text("❌ پسورد اشتباه است. لطفاً دوباره وارد کنید:")
            return LOGIN_PASSWORD # بازگشت به مرحله دریافت پسورد
            
    except Exception as e:
        logging.error(f"خطا در فرآیند لاگین: {e}")
        await update.message.reply_text("خطایی در سرور رخ داد.")
        return ConversationHandler.END
    finally:
        context.user_data.clear()

# --- ۴. دستور خروج (/logout) ---

async def logout_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """خروج کاربر از سیستم."""
    user_id = update.effective_user.id
    if user_id in LOGGED_IN_USERS:
        # حذف کاربر از دیکشنری لاگین‌شده‌ها
        del LOGGED_IN_USERS[user_id]
        await update.message.reply_text("◀️ شما با موفقیت خارج شدید.")
    else:
        await update.message.reply_text("شما لاگین نکرده بودید.")

# --- ۵. دستورات مدیریتی (Placeholder) ---
# ما اینها را در فاز بعدی کامل خواهیم کرد

async def addkey_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """شروع فرآیند افزودن API Key (فقط برای کاربران لاگین کرده)."""
    if not await is_user_logged_in(update, context):
        return ConversationHandler.END
        
    await update.message.reply_text(
        "🔑 **افزودن اکانت صرافی جدید**\n"
        "این قابلیت به زودی تکمیل می‌شود...\n"
        "(در حال حاضر برای تست /cancel را بزنید)"
    )
    # اینجا ما را به مکالمه ADD_KEY_NAME می‌برد که هنوز پیاده‌سازی نشده
    # return ADD_KEY_NAME 
    # فعلا برای تست، مکالمه را تمام می‌کنیم:
    return ConversationHandler.END

# --- ۶. تابع اصلی و اجرای ربات ---

def run_bot():
    """ربات تلگرام را راه‌اندازی و اجرا می‌کند."""
    if not TELEGRAM_TOKEN:
        logging.critical("توکن تلگرام (TELEGRAM_BOT_TOKEN) در .env یافت نشد.")
        return

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # --- تعریف مکالمه‌ها (Conversations) ---
    
    # مکالمه ثبت نام
    register_conv = ConversationHandler(
        entry_points=[CommandHandler("register", register_start)],
        states={
            REGISTER_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_get_username)],
            REGISTER_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_get_password)],
            REGISTER_PASSWORD_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_get_password_confirm)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
    )

    # مکالمه لاگین
    login_conv = ConversationHandler(
        entry_points=[CommandHandler("login", login_start)],
        states={
            LOGIN_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_get_username)],
            LOGIN_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_get_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
    )
    
    # مکالمه افزودن کلید (فعلا Placeholder)
    addkey_conv = ConversationHandler(
        entry_points=[CommandHandler("addkey", addkey_start)],
        states={
            # این بخش‌ها در فاز بعدی کامل می‌شوند
            # ADD_KEY_NAME: [...],
            # ADD_KEY_API_KEY: [...],
            # ADD_KEY_AMOUNT: [...],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
    )

    # --- افزودن دستورات به ربات ---
    application.add_handler(register_conv)
    application.add_handler(login_conv)
    application.add_handler(addkey_conv)
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("logout", logout_command))

    # شروع به کار ربات
    logging.info("ربات تلگرام در حال اجرا است...")
    application.run_polling()

if __name__ == "__main__":
    run_bot()
