# cleanup_manager.py
import logging
import time
from datetime import datetime, timedelta
import pytz
import config
import db_utils
import wallex_api

# تنظیمات لاگ‌گیری
logging.basicConfig(level=config.BOT["LOG_LEVEL"], format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s')

def cleanup_loop():
    """
    حلقه اصلی برای بررسی و پاکسازی سفارشات خرید باز که قدیمی شده‌اند.
    """
    logging.info("ماژول پاکسازی (Cleanup Manager) شروع به کار کرد.")
    
    tehran_tz = pytz.timezone("Asia/Tehran")
    timeout_minutes = config.BOT.get("STALE_ORDER_TIMEOUT_MINUTES", 5)
    
    while True:
        try:
            logging.info(f"در حال جستجو برای سفارشات خرید باز مانده (قدیمی‌تر از {timeout_minutes} دقیقه)...")
            
            # فقط سفارشات خرید باز را بررسی می‌کنیم
            open_buy_orders = db_utils.query_db(
                "SELECT id, buy_client_order_id, created_at FROM trade_signals WHERE status = 'BUY_ORDER_PLACED'",
                fetch='all'
            )
            
            if not open_buy_orders:
                logging.info("هیچ سفارش خرید بازی برای پاکسازی یافت نشد.")
            else:
                now_in_tehran = datetime.now(tehran_tz)
                
                for order in open_buy_orders:
                    # زمان در دیتابیس معمولا به صورت UTC ذخیره می‌شود
                    # .replace(tzinfo=pytz.utc) آن را Timezone-aware می‌کند
                    order_time_utc = order['created_at'].replace(tzinfo=pytz.utc)
                    age = now_in_tehran - order_time_utc
                    
                    if age.total_seconds() > (timeout_minutes * 60):
                        logging.warning(f"سفارش {order['buy_client_order_id']} (ID: {order['id']}) قدیمی است (عمر: {age}). در حال لغو...")
                        
                        # ۱. لغو سفارش در والکس
                        if wallex_api.cancel_wallex_order(order['buy_client_order_id']):
                            # ۲. در صورت موفقیت، آپدیت دیتابیس
                            db_utils.query_db(
                                "UPDATE trade_signals SET status = 'CANCELED_TIMEOUT', notes = %s WHERE id = %s",
                                (f"Buy order canceled after {timeout_minutes} min timeout", order['id'])
                            )
                            logging.info(f"سفارش {order['buy_client_order_id']} با موفقیت لغو و در دیتابیس آپدیت شد.")
                        else:
                            logging.error(f"تلاش برای لغو سفارش {order['buy_client_order_id']} در والکس ناموفق بود. در چرخه بعدی دوباره تلاش می‌شود.")
                    else:
                        logging.info(f"سفارش {order['buy_client_order_id']} تازه است (عمر: {age}). نادیده گرفته شد.")

        except Exception as e:
            logging.error(f"خطای پیش‌بینی نشده در حلقه پاکسازی: {e}")
            
        logging.info(f"خواب به مدت {config.BOT['CLEANUP_INTERVAL_SECONDS']} ثانیه...")
        time.sleep(config.BOT["CLEANUP_INTERVAL_SECONDS"])


if __name__ == "__main__":
    cleanup_loop()