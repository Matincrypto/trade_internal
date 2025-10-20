# signal_ingestor.py
import requests
import time
import logging
import config
import db_utils

# تنظیمات لاگ‌گیری
logging.basicConfig(level=config.BOT["LOG_LEVEL"], format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s')

def fetch_signals():
    """سیگنال‌ها را از تمام منابع API تعریف شده در کانفیگ دریافت می‌کند."""
    all_opportunities = []
    api_sources = config.STRATEGY_API.get("SOURCES", {})

    if not api_sources:
        logging.warning("هیچ منبع API سیگنال در 'config.STRATEGY_API.SOURCES' تعریف نشده است.")
        return []

    for name, url in api_sources.items():
        try:
            logging.info(f"در حال بررسی سیگنال از منبع: {name}...")
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                opportunities = data.get("opportunities", [])
                if opportunities:
                    logging.info(f"{len(opportunities)} فرصت جدید از {name} یافت شد.")
                    all_opportunities.extend(opportunities)
            else:
                logging.warning(f"منبع {name} پاسخی با کد وضعیت {response.status_code} برگرداند.")
        except requests.exceptions.RequestException as e:
            logging.error(f"عدم امکان اتصال به منبع API {name}: {e}")
            continue
    return all_opportunities

def ingest_signals_loop():
    """حلقه اصلی برای دریافت سیگنال و ذخیره در دیتابیس."""
    logging.info("ماژول شکارچی سیگنال (Ingestor) شروع به کار کرد.")
    
    while True:
        try:
            signals = fetch_signals()
            if not signals:
                logging.info("هیچ سیگنال جدیدی از منابع یافت نشد.")
                time.sleep(config.BOT["SIGNAL_CHECK_INTERVAL_SECONDS"])
                continue

            logging.info(f"مجموعاً {len(signals)} سیگنال دریافت شد. در حال بررسی در دیتابیس...")
            
            new_signals_saved = 0
            for signal in signals:
                asset_name = signal.get("asset_name")
                if not asset_name:
                    logging.warning("سیگنال دریافت شده فاقد 'asset_name' است. نادیده گرفته شد.")
                    continue

                # --- منطق کلیدی: بررسی پوزیشن تکراری و باز ---
                # ما به دنبال سفارشی برای این دارایی هستیم که هنوز تکمیل نشده یا لغو نشده باشد
                active_order = db_utils.query_db(
                    "SELECT id FROM trade_signals WHERE asset_name = %s AND status NOT IN ('SELL_ORDER_FILLED', 'CANCELED_TIMEOUT', 'ERROR')",
                    (asset_name,),
                    fetch='one'
                )
                
                if active_order:
                    logging.info(f"یک پوزیشن باز برای {asset_name} وجود دارد (ID: {active_order['id']}). سیگنال جدید نادیده گرفته شد.")
                    continue
                
                # --- ذخیره سیگنال جدید در دیتابیس ---
                logging.info(f"سیگنال جدید برای {asset_name} یافت شد. در حال ذخیره در دیتابیس...")
                
                db_utils.query_db(
                    """
                    INSERT INTO trade_signals 
                    (asset_name, pair, entry_price, exit_price, strategy_name, status) 
                    VALUES (%s, %s, %s, %s, %s, 'NEW_SIGNAL')
                    """,
                    (
                        asset_name,
                        signal.get("pair"),
                        signal.get("entry_price"),
                        signal.get("exit_price"),
                        signal.get("strategy_name")
                    )
                )
                new_signals_saved += 1
            
            if new_signals_saved > 0:
                logging.info(f"{new_signals_saved} سیگنال جدید با موفقیت در دیتابیس ذخیره شد.")

        except Exception as e:
            logging.error(f"خطای پیش‌بینی نشده در حلقه شکارچی سیگنال: {e}")
        
        logging.info(f"خواب به مدت {config.BOT['SIGNAL_CHECK_INTERVAL_SECONDS']} ثانیه...")
        time.sleep(config.BOT["SIGNAL_CHECK_INTERVAL_SECONDS"])


if __name__ == "__main__":
    ingest_signals_loop()