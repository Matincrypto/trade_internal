# bot_runner.py
import threading
import logging
import time
import sys

# ایمپورت کردن حلقه‌های اصلی از فایل‌های دیگر
import signal_ingestor
import order_executor
import cleanup_manager
import wallex_api
import config

# تنظیمات لاگ‌گیری اصلی
logging.basicConfig(level=config.BOT["LOG_LEVEL"], format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s')

if __name__ == "__main__":
    logging.info("=============================================")
    logging.info("     شروع به کار ربات معامله‌گر (نسخه ۳ ماژول)     ")
    logging.info("=============================================")
    
    # --- گام حیاتی: بارگذاری قوانین بازار قبل از شروع هر کاری ---
    logging.info("در حال بارگذاری اولیه قوانین بازار از والکس...")
    if not wallex_api.load_market_precisions():
        logging.critical("امکان بارگذاری قوانین بازار وجود ندارد. ربات نمی‌تواند ادامه دهد.")
        sys.exit("خطای بحرانی: عدم بارگذاری قوانین بازار.")
    logging.info("قوانین بازار با موفقیت بارگذاری شد.")

    # --- ساختن Thread ها ---
    # هر ماژول در یک رشته (Thread) جداگانه اجرا می‌شود
    
    # ۱. رشته شکارچی سیگنال
    signal_thread = threading.Thread(
        target=signal_ingestor.ingest_signals_loop, 
        name="SignalIngestor"
    )
    
    # ۲. رشته مجری سفارشات
    executor_thread = threading.Thread(
        target=order_executor.main_executor_loop, 
        name="OrderExecutor"
    )
    
    # ۳. رشته پاکسازی سفارشات
    cleanup_thread = threading.Thread(
        target=cleanup_manager.cleanup_loop, 
        name="CleanupManager"
    )

    # --- شروع به کار Thread ها ---
    logging.info("در حال فعال‌سازی ماژول‌ها...")
    signal_thread.start()
    time.sleep(1) # وقفه کوتاه برای نظم در لاگ‌ها
    executor_thread.start()
    time.sleep(1)
    cleanup_thread.start()

    logging.info("--- تمام ماژول‌ها فعال شدند. ربات در حال اجرا است ---")

    # --- منتظر ماندن برای پایان کار Thread ها (که هرگز اتفاق نمی‌افتد مگر با خطا) ---
    signal_thread.join()
    executor_thread.join()
    cleanup_thread.join()

    logging.info("--- ربات متوقف شد ---")