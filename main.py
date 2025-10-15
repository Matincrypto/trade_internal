# main.py (نسخه نهایی با پشتیبانی از چند API)
import requests
import time
import json
import logging
import mysql.connector
import threading
import math

# وارد کردن تنظیمات از فایل کانفیگ
import config

# تنظیمات لاگ‌ها
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s')

# دیکشنری برای ذخیره قوانین دقت اعشار
market_precisions = {}

# --- توابع کمکی ---

def load_market_precisions():
    """قوانین دقت اعشار را از والکس بارگذاری می‌کند."""
    logging.info("در حال بارگذاری قوانین دقت اعشار بازارها از والکس...")
    url = config.WALLEX_API["BASE_URL"] + config.WALLEX_API["ENDPOINTS"]["ALL_MARKETS"]
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            markets = response.json().get("result", {}).get("markets", [])
            for market in markets:
                symbol = market.get("symbol")
                precision = market.get("amount_precision")
                if symbol and precision is not None:
                    market_precisions[symbol] = int(precision)
            logging.info(f"قوانین دقت اعشار برای {len(market_precisions)} بازار با موفقیت بارگذاری شد.")
            return True
        else:
            logging.error("خطا در بارگذاری قوانین دقت اعشار بازارها.")
            return False
    except requests.exceptions.RequestException as e:
        logging.error(f"خطا در ارتباط برای دریافت قوانین بازار: {e}")
        return False

def format_quantity(quantity, precision):
    """مقدار را بر اساس دقت اعشار مجاز گرد می‌کند."""
    factor = 10 ** precision
    return math.floor(quantity * factor) / factor

# === تابع کلیدی به‌روز شده ===
def get_strategy_signals():
    """سیگنال‌ها را از تمام منابع API تعریف شده در کانفیگ دریافت و ادغام می‌کند."""
    all_opportunities = []
    api_sources = config.STRATEGY_API.get("SOURCES", {})

    # حلقه برای بررسی هر منبع API
    for name, url in api_sources.items():
        try:
            logging.info(f"در حال بررسی سیگنال از منبع: {name}...")
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                opportunities = data.get("opportunities", [])
                if opportunities:
                    logging.info(f"{len(opportunities)} فرصت جدید از {name} یافت شد.")
                    all_opportunities.extend(opportunities) # اضافه کردن فرصت‌ها به لیست کلی
            else:
                logging.warning(f"منبع {name} پاسخی با کد وضعیت {response.status_code} برگرداند.")
        except requests.exceptions.RequestException as e:
            logging.error(f"عدم امکان اتصال به منبع API {name}: {e}")
            continue # در صورت خطا، به سراغ منبع بعدی برو

    # بازگرداندن خروجی در همان فرمت استاندارد قبلی
    return {
        "opportunities": all_opportunities,
        "opportunities_found": len(all_opportunities)
    }

def place_wallex_order(symbol, price, quantity, side):
    """یک سفارش جدید در صرافی والکس ثبت می‌کند."""
    url = config.WALLEX_API["BASE_URL"] + config.WALLEX_API["ENDPOINTS"]["ORDERS"]
    headers = {"Content-Type": "application/json", "x-api-key": config.WALLEX_API["API_KEY"]}
    payload = {"symbol": symbol, "price": str(price), "quantity": str(quantity), "side": side, "type": "limit"}
    
    logging.info(f"در حال ثبت سفارش: {side.upper()} {quantity} {symbol} @ {price}")
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=15)
        response_data = response.json()
        if response.status_code == 201 and response_data.get("success"):
            order_id = response_data.get("result", {}).get("clientOrderId")
            logging.info(f"سفارش با موفقیت ثبت شد! شناسه سفارش: {order_id}")
            return response_data
        else:
            logging.error(f"خطا در ثبت سفارش. وضعیت: {response.status_code}, پاسخ: {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"خطا در زمان ثبت سفارش در والکس: {e}")
        return None

def create_db_connection():
    """یک اتصال جدید به پایگاه داده ایجاد می‌کند."""
    try:
        return mysql.connector.connect(**config.DATABASE)
    except mysql.connector.Error as e:
        logging.error(f"خطا در اتصال به پایگاه داده MySQL: {e}")
        return None

def query_db(query, params=None, fetch=None):
    """یک تابع عمومی برای اجرای کوئری روی پایگاه داده."""
    connection = create_db_connection()
    if not connection: return None
    try:
        cursor = connection.cursor(dictionary=(fetch is not None))
        cursor.execute(query, params or ())
        if fetch == 'one': return cursor.fetchone()
        if fetch == 'all': return cursor.fetchall()
        connection.commit()
        return True
    except mysql.connector.Error as e:
        logging.error(f"خطای کوئری پایگاه داده: {e}")
        return None
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()
            
# --- حلقه اصلی برای پیدا کردن سیگنال و ثبت سفارش خرید (به‌روز شده) ---

def signal_checking_loop():
    """حلقه اصلی برای بررسی سیگنال‌های جدید معاملاتی."""
    logging.info("حلقه بررسی سیگنال شروع به کار کرد.")
    while True:
        # فراخوانی تابع جدید برای گرفتن سیگنال از همه منابع
        signal_data = get_strategy_signals() 
        
        if signal_data and signal_data.get("opportunities_found", 0) > 0:
            logging.info(f"مجموعاً {signal_data['opportunities_found']} فرصت جدید از تمام منابع یافت شد.")
            for opportunity in signal_data["opportunities"]:
                asset_name = opportunity.get("asset_name")
                entry_price = opportunity.get("entry_price")
                if not all([asset_name, entry_price]):
                    logging.warning("اطلاعات ناقص در سیگنال دریافت شده، نادیده گرفته شد.")
                    continue
                
                symbol = f"{asset_name}{config.TRADING['QUOTE_ASSET']}"
                
                precision = market_precisions.get(symbol)
                if precision is None:
                    logging.warning(f"قانون دقت اعشار برای نماد '{symbol}' یافت نشد. نادیده گرفته شد.")
                    continue

                open_order = query_db("SELECT COUNT(*) as count FROM trading_orders WHERE asset_name = %s AND status NOT IN ('COMPLETED', 'CANCELLED', 'CANCELED_TIMEOUT')", (asset_name,), fetch='one')
                if open_order and open_order['count'] > 0:
                    logging.info(f"یک سفارش باز برای '{asset_name}' وجود دارد. نادیده گرفته شد.")
                    continue
                
                quantity_to_buy_raw = config.TRADING["TRADE_AMOUNT_TMN"] / entry_price
                formatted_quantity = format_quantity(quantity_to_buy_raw, precision)
                
                if formatted_quantity <= 0:
                    logging.warning(f"مقدار محاسبه شده برای {symbol} پس از گرد کردن، برای معامله بسیار کوچک است. نادیده گرفته شد.")
                    continue

                order_response = place_wallex_order(symbol, entry_price, formatted_quantity, "buy")
                
                if order_response:
                    order_result = order_response.get("result", {})
                    query_db(
                        "INSERT INTO trading_orders (client_order_id, symbol, asset_name, entry_price, exit_price, quantity, status) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (order_result.get("clientOrderId"), symbol, asset_name, opportunity.get("entry_price"), opportunity.get("exit_price"), formatted_quantity, "BUY_ORDER_PLACED")
                    )
        else:
            logging.info("هیچ فرصت جدیدی در هیچ‌کدام از منابع یافت نشد.")
        
        time.sleep(config.BOT["SIGNAL_CHECK_INTERVAL_SECONDS"])

# --- شروع به کار ربات ---

if __name__ == "__main__":
    logging.info("در حال شروع به کار ربات جستجوگر سیگنال...")
    
    if load_market_precisions():
        signal_thread = threading.Thread(target=signal_checking_loop, name="SignalChecker")
        signal_thread.start()
        signal_thread.join()
    else:
        logging.critical("امکان بارگذاری قوانین بازار وجود ندارد. ربات متوقف شد.")
    
    logging.info("ربات جستجوگر سیگنال متوقف شد.")
