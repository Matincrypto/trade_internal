# wallex_api.py
import requests
import json
import logging
import math
import config
from decimal import Decimal

# دیکشنری برای ذخیره قوانین دقت اعشار
# ما اکنون دو قانون را ذخیره می‌کنیم
market_amount_precisions = {}
market_price_precisions = {}

def load_market_precisions():
    """
    قوانین دقت اعشار (amount_precision و price_precision) را از والکس بارگذاری می‌کند.
    """
    global market_amount_precisions, market_price_precisions
    logging.info("در حال بارگذاری قوانین دقت اعشار بازارها از والکس...")
    url = config.WALLEX_API["BASE_URL"] + config.WALLEX_API["ENDPOINTS"]["ALL_MARKETS"]
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            markets = response.json().get("result", {}).get("markets", [])
            for market in markets:
                symbol = market.get("symbol")
                amount_precision = market.get("amount_precision")
                price_precision = market.get("price_precision") # <-- فیلد جدید
                
                if symbol:
                    if amount_precision is not None:
                        market_amount_precisions[symbol] = int(amount_precision)
                    if price_precision is not None:
                        market_price_precisions[symbol] = int(price_precision)
                        
            logging.info(f"قوانین Amount Precision برای {len(market_amount_precisions)} بازار بارگذاری شد.")
            logging.info(f"قوانین Price Precision برای {len(market_price_precisions)} بازار بارگذاری شد.")
            return True
        else:
            logging.error(f"خطا در بارگذاری قوانین دقت اعشار بازارها. وضعیت: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        logging.error(f"خطا در ارتباط برای دریافت قوانین بازار: {e}")
        return False

def format_quantity(quantity, precision):
    """
    مقدار (Quantity) را بر اساس دقت اعشار مجاز بازار، به پایین گرد می‌کند (Floor).
    """
    factor = Decimal(10) ** precision
    return math.floor(Decimal(quantity) * factor) / factor

# ==================================================================
# ***!!! تابع جدید برای گرد کردن قیمت !!!***
# ==================================================================
def format_price(price, precision):
    """
    قیمت (Price) را بر اساس دقت اعشار مجاز بازار، به پایین گرد می‌کند (Floor).
    * ما از Floor استفاده می‌کنیم تا همیشه یک قیمت معتبر (و اغلب بهتر) برای خرید 
    * و یک قیمت معتبر (کمی محافظه‌کارانه‌تر) برای فروش داشته باشیم.
    """
    factor = Decimal(10) ** precision
    return math.floor(Decimal(price) * factor) / factor

def place_wallex_order(symbol, price, quantity, side):
    """
    یک سفارش جدید (خرید یا فروش) در صرافی والکس ثبت می‌کند.
    """
    url = config.WALLEX_API["BASE_URL"] + config.WALLEX_API["ENDPOINTS"]["ORDERS"]
    headers = {"Content-Type": "application/json", "x-api-key": config.WALLEX_API["API_KEY"]}
    # مقادیر باید به صورت رشته ارسال شوند
    payload = {
        "symbol": symbol, 
        "price": str(price), 
        "quantity": str(quantity), 
        "side": side.lower(), # 'buy' or 'sell'
        "type": "limit"
    }
    
    logging.info(f"در حال ثبت سفارش: {side.UPPER()} {quantity} {symbol} @ {price}")
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=15)
        response_data = response.json()
        
        # 201 Created
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
    """
    جزئیات کامل و وضعیت یک سفارش مشخص را از والکس دریافت می‌کند.
    """
    url = config.WALLEX_API["BASE_URL"] + config.WALLEX_API["ENDPOINTS"]["GET_ORDER"] + client_order_id
    headers = {"x-api-key": config.WALLEX_API["API_KEY"]}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response_data = response.json()
        
        if response.status_code == 200 and response_data.get("success"):
            return response_data.get("result") # بازگرداندن آبجکت کامل سفارش
        else:
            logging.warning(f"عدم موفقیت در دریافت وضعیت سفارش {client_order_id}. پاسخ: {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"خطا در ارتباط برای دریافت وضعیت سفارش {client_order_id}: {e}")
        return None

def cancel_wallex_order(client_order_id):
    """
    یک سفارش باز را در والکس با استفاده از client_order_id لغو می‌کند.
    """
    url = config.WALLEX_API["BASE_URL"] + config.WALLEX_API["ENDPOINTS"]["ORDERS"]
    headers = {"Content-Type": "application/json", "x-api-key": config.WALLEX_API["API_KEY"]}
    payload = {"clientOrderId": client_order_id}
    
    logging.info(f"در حال تلاش برای لغو سفارش {client_order_id} در والکس...")
    try:
        response = requests.delete(url, headers=headers, data=json.dumps(payload), timeout=15)
        response_data = response.json()

        if response.status_code == 200 and response_data.get("success"):
            logging.info(f"سفارش {client_order_id} با موفقیت در والکس لغو شد.")
            return True
        else:
            logging.error(f"خطا در لغو سفارش {client_order_id}. وضعیت: {response.status_code}, پاسخ: {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        logging.error(f"خطا در زمان لغو سفارش در والکس: {e}")
        return False
