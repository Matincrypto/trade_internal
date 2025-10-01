import requests
import time
import json
import logging
import mysql.connector
import threading
import math # کتابخانه ریاضی برای گرد کردن اعداد

# وارد کردن تنظیمات از فایل کانفیگ
import config

# تنظیمات اولیه لاگ‌ها برای نمایش فعالیت ربات
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s')

# یک دیکشنری سراسری برای ذخیره قوانین دقت اعشار بازارها
market_precisions = {}

# --- تابع جدید برای بارگذاری قوانین بازار ---
def load_market_precisions():
    """قوانین تمام بازارها را از والکس دریافت و دقت اعشار آنها را ذخیره می‌کند."""
    logging.info("در حال بارگذاری قوانین دقت اعشار بازارها از والکس...")
    url = config.WALLEX_API["BASE_URL"] + config.WALLEX_API["ENDPOINTS"]["ALL_MARKETS"]
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            markets = response.json().get("result", {}).get("markets", [])
            for market in markets:
                symbol = market.get("symbol")
                # ما 'amount_precision' که مربوط به مقدار (quantity) است را ذخیره می‌کنیم
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

# --- تابع کمکی برای فرمت کردن مقدار ---
def format_quantity(quantity, precision):
    """مقدار را بر اساس دقت اعشار مجاز، به پایین گرد (floor) می‌کند."""
    factor = 10 ** precision
    return math.floor(quantity * factor) / factor

# --- توابع دیگر (بدون تغییر باقی می‌مانند) ---
def get_strategy_signal():
    try:
        response = requests.get(config.STRATEGY_API["URL"], timeout=10)
        return response.json() if response.status_code == 200 else None
    except requests.exceptions.RequestException as e:
        logging.error(f"عدم امکان اتصال به API استراتژی: {e}")
        return None

def place_wallex_order(symbol, price, quantity, side):
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

def get_wallex_order_status(client_order_id):
    url = config.WALLEX_API["BASE_URL"] + config.WALLEX_API["ENDPOINTS"]["GET_ORDER"] + client_order_id
    headers = {"x-api-key": config.WALLEX_API["API_KEY"]}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        return response.json().get("result") if response.status_code == 200 and response.json().get("success") else None
    except requests.exceptions.RequestException as e:
        logging.error(f"خطا در دریافت وضعیت سفارش از والکس: {e}")
        return None

def create_db_connection():
    try:
        return mysql.connector.connect(**config.DATABASE)
    except mysql.connector.Error as e:
        logging.error(f"خطا در اتصال به پایگاه داده MySQL: {e}")
        return None

def query_db(query, params=None, fetch=None):
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

# --- حلقه اصلی پیدا کردن سیگنال (به‌روز شده) ---
def signal_checking_loop():
    logging.info("حلقه بررسی سیگنال شروع به کار کرد.")
    while True:
        signal_data = get_strategy_signal()
        if signal_data and signal_data.get("opportunities_found", 0) > 0:
            for opportunity in signal_data["opportunities"]:
                asset_name = opportunity.get("asset_name")
                entry_price = opportunity.get("entry_price")
                if not all([asset_name, entry_price]):
                    logging.warning("اطلاعات ناقص در سیگنال دریافت شده، نادیده گرفته شد.")
                    continue
                
                symbol = f"{asset_name}{config.TRADING['QUOTE_ASSET']}"
                
                # --- منطق جدید برای کنترل دقت اعشار ---
                precision = market_precisions.get(symbol)
                if precision is None:
                    logging.warning(f"قانون دقت اعشار برای نماد '{symbol}' یافت نشد. نادیده گرفته شد.")
                    continue

                open_order = query_db("SELECT COUNT(*) as count FROM trading_orders WHERE asset_name = %s AND status NOT IN ('COMPLETED', 'CANCELLED')", (asset_name,), fetch='one')
                if open_order and open_order['count'] > 0:
                    logging.info(f"یک سفارش باز برای '{asset_name}' وجود دارد. نادیده گرفته شد.")
                    continue
                
                quantity_raw = config.TRADING["TRADE_AMOUNT_TMN"] / entry_price
                formatted_quantity = format_quantity(quantity_raw, precision)
                
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
            logging.info("فرصت جدیدی یافت نشد.")
        
        time.sleep(config.BOT["SIGNAL_CHECK_INTERVAL_SECONDS"])

# --- حلقه مدیریت سفارشات (به‌روز شده) ---
def order_management_loop():
    logging.info("حلقه مدیریت سفارشات شروع به کار کرد.")
    while True:
        open_orders = query_db("SELECT * FROM trading_orders WHERE status = 'BUY_ORDER_PLACED'", fetch='all')
        if open_orders:
            logging.info(f"{len(open_orders)} سفارش خرید باز برای بررسی یافت شد.")
            for order in open_orders:
                client_id = order["client_order_id"]
                wallex_order_status = get_wallex_order_status(client_id)
                if wallex_order_status and wallex_order_status.get("status") == 'DONE':
                    logging.info(f"سفارش خرید {client_id} انجام شد! در حال ثبت سفارش فروش.")
                    query_db("UPDATE trading_orders SET status = %s WHERE client_order_id = %s", ("BUY_ORDER_FILLED", client_id))
                    
                    sell_response = place_wallex_order(order["symbol"], order["exit_price"], order["quantity"], "sell")
                    if sell_response:
                        query_db("UPDATE trading_orders SET status = %s WHERE client_order_id = %s", ("SELL_ORDER_PLACED", client_id))
        else:
            logging.info("سفارش خرید بازی برای مدیریت وجود ندارد.")

        time.sleep(config.BOT["ORDER_MANAGEMENT_INTERVAL_SECONDS"])
        
# --- شروع به کار ربات ---
if __name__ == "__main__":
    logging.info("در حال شروع به کار ربات تریدر...")

    if load_market_precisions():
        signal_thread = threading.Thread(target=signal_checking_loop, name="SignalChecker")
        order_thread = threading.Thread(target=order_management_loop, name="OrderManager")

        signal_thread.start()
        order_thread.start()

        signal_thread.join()
        order_thread.join()
    else:
        logging.critical("امکان بارگذاری قوانین بازار وجود ندارد. ربات متوقف شد.")
    
    logging.info("ربات متوقف شد.")
