# wallex_api.py
import requests
import json
import logging
import math
import config
from decimal import Decimal

# دیکشنری برای ذخیره قوانین دقت اعشار
# این متغیر به صورت گلوبال در این ماژول ذخیره می‌شود تا فقط یک بار بارگذاری شود
market_precisions = {}

def load_market_precisions():
    """
    قوانین دقت اعشار (amount_precision) را از والکس بارگذاری کرده 
    و در متغیر گلوبال market_precisions ذخیره می‌کند.
    """
    global market_precisions
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
            logging.error(f"خطا در بارگذاری قوانین دقت اعشار بازارها. وضعیت: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        logging.error(f"خطا در ارتباط برای دریافت قوانین بازار: {e}")
        return False

def format_quantity(quantity, precision):
    """
    مقدار (Quantity) را بر اساس دقت اعشار مجاز بازار، به پایین گرد می‌کند (Floor).
    استفاده از Decimal برای جلوگیری از خطاهای ممیز شناور.
    """
    factor = Decimal(10) ** precision
    return math.floor(Decimal(quantity) * factor) / factor

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
    
    logging.info(f"در حال ثبت سفارش: {side.upper()} {quantity} {symbol} @ {price}")
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
    بر اساس مستندات Swagger، والکس از متد DELETE برای لغو استفاده می‌کند 
    و clientOrderId را در بدنه (body) JSON انتظار دارد.
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