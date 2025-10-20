# order_executor.py
import logging
import time
from decimal import Decimal
import config
import db_utils
import wallex_api

# تنظیمات لاگ‌گیری
logging.basicConfig(level=config.BOT["LOG_LEVEL"], format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s')

def process_new_signals():
    """
    مرحله ۱: سیگنال‌های 'NEW_SIGNAL' را از دیتابیس خوانده و برایشان سفارش خرید ثبت می‌کند.
    """
    logging.info("[مرحله ۱] در حال بررسی سیگنال‌های جدید برای ثبت سفارش خرید...")
    signals = db_utils.query_db("SELECT * FROM trade_signals WHERE status = 'NEW_SIGNAL'", fetch='all')
    
    if not signals:
        logging.info("[مرحله ۱] هیچ سیگنال جدیدی برای اجرا یافت نشد.")
        return

    for signal in signals:
        try:
            symbol = f"{signal['asset_name']}{config.TRADING['QUOTE_ASSET']}"
            
            precision = wallex_api.market_precisions.get(symbol)
            if precision is None:
                logging.warning(f"قانون دقت اعشار برای نماد '{symbol}' یافت نشد. نمی‌توان سفارش ثبت کرد.")
                db_utils.query_db("UPDATE trade_signals SET status = 'ERROR', notes = %s WHERE id = %s", (f"Precision not found for {symbol}", signal['id']))
                continue

            # استفاده از Decimal برای دقت بالا در محاسبات مالی
            entry_price = Decimal(signal['entry_price'])
            trade_amount = Decimal(config.TRADING["TRADE_AMOUNT_TMN"])
            
            if entry_price <= 0:
                 logging.error(f"قیمت ورودی نامعتبر (صفر) برای {symbol}. نادیده گرفته شد.")
                 db_utils.query_db("UPDATE trade_signals SET status = 'ERROR', notes = 'Invalid entry price (zero)' WHERE id = %s", (signal['id'],))
                 continue
                 
            quantity_to_buy_raw = trade_amount / entry_price
            formatted_quantity = wallex_api.format_quantity(quantity_to_buy_raw, precision)
            
            logging.info(f"مقدار محاسبه شده برای {symbol}: {formatted_quantity} (خام: {quantity_to_buy_raw})")

            if formatted_quantity <= 0:
                logging.warning(f"مقدار محاسبه شده برای {symbol} (0) برای معامله بسیار کوچک است.")
                db_utils.query_db("UPDATE trade_signals SET status = 'ERROR', notes = 'Calculated quantity is zero' WHERE id = %s", (signal['id'],))
                continue

            # ثبت سفارش خرید در والکس
            order_response = wallex_api.place_wallex_order(symbol, entry_price, formatted_quantity, "buy")
            
            if order_response:
                client_order_id = order_response.get("result", {}).get("clientOrderId")
                db_utils.query_db(
                    "UPDATE trade_signals SET status = 'BUY_ORDER_PLACED', buy_client_order_id = %s, buy_quantity_raw = %s, buy_quantity_formatted = %s WHERE id = %s",
                    (client_order_id, quantity_to_buy_raw, formatted_quantity, signal['id'])
                )
                logging.info(f"سفارش خرید برای {symbol} با ID: {client_order_id} ثبت شد.")
            else:
                logging.error(f"خطا در ثبت سفارش خرید برای {symbol}.")
                db_utils.query_db("UPDATE trade_signals SET status = 'ERROR', notes = 'Failed to place buy order on Wallex' WHERE id = %s", (signal['id'],))

        except Exception as e:
            logging.error(f"خطای پیش‌بینی نشده در process_new_signals برای ID {signal['id']}: {e}")
            db_utils.query_db("UPDATE trade_signals SET status = 'ERROR', notes = %s WHERE id = %s", (str(e), signal['id']))


def check_filled_buys():
    """
    مرحله ۲: سفارشات 'BUY_ORDER_PLACED' را بررسی می‌کند.
    اگر تکمیل شده باشند، وضعیت را به 'BUY_ORDER_FILLED' تغییر می‌دهد و مقدار خالص را ذخیره می‌کند.
    """
    logging.info("[مرحله ۲] در حال بررسی وضعیت سفارشات خرید ثبت شده...")
    orders = db_utils.query_db("SELECT id, buy_client_order_id FROM trade_signals WHERE status = 'BUY_ORDER_PLACED'", fetch='all')

    if not orders:
        logging.info("[مرحله ۲] هیچ سفارش خریدی در انتظار بررسی وضعیت نیست.")
        return

    for order in orders:
        try:
            wallex_order = wallex_api.get_wallex_order_status(order['buy_client_order_id'])
            
            # فیکس قبلی: تغییر از 'DONE' به 'FILLED'
            if wallex_order and wallex_order.get("status") == 'FILLED':
                logging.info(f"سفارش خرید {order['buy_client_order_id']} تکمیل (FILLED) شده است!")
                
                executed_qty_str = wallex_order.get("executedQty", "0")
                fee_str = wallex_order.get("fee", "0")
                
                # محاسبه مقدار خالص با دقت Decimal
                executed_qty = Decimal(executed_qty_str)
                fee = Decimal(fee_str)
                net_quantity = executed_qty - fee
                
                logging.info(f"مقدار اجرا شده: {executed_qty}, کارمزد: {fee}, مقدار خالص دریافتی: {net_quantity}")
                
                db_utils.query_db(
                    "UPDATE trade_signals SET status = 'BUY_ORDER_FILLED', buy_executed_quantity = %s, buy_fee = %s WHERE id = %s",
                    (net_quantity, fee, order['id'])
                )
            elif wallex_order:
                logging.info(f"سفارش خرید {order['buy_client_order_id']} هنوز باز است (وضعیت: {wallex_order.get('status')}).")
            else:
                logging.warning(f"اطلاعاتی برای سفارش {order['buy_client_order_id']} از والکس دریافت نشد.")

        except Exception as e:
            logging.error(f"خطا در check_filled_buys برای ID {order['id']}: {e}")
            db_utils.query_db("UPDATE trade_signals SET status = 'ERROR', notes = %s WHERE id = %s", (str(e), order['id']))


def place_sell_orders():
    """
    مرحله ۳: رکوردهای 'BUY_ORDER_FILLED' را پیدا کرده و برای آن‌ها سفارش فروش ثبت می‌کند.
    """
    logging.info("[مرحله ۳] در حال بررسی خریدهای تکمیل شده برای ثبت سفارش فروش...")
    orders = db_utils.query_db("SELECT * FROM trade_signals WHERE status = 'BUY_ORDER_FILLED'", fetch='all')

    if not orders:
        logging.info("[مرحله ۳] هیچ خرید تکمیل شده‌ای برای فروش یافت نشد.")
        return

    for order in orders:
        try:
            quantity_to_sell_raw = order.get("buy_executed_quantity")
            if not quantity_to_sell_raw or quantity_to_sell_raw <= 0:
                logging.error(f"مقدار خالص برای فروش (ID: {order['id']}) نامعتبر است: {quantity_to_sell_raw}")
                db_utils.query_db("UPDATE trade_signals SET status = 'ERROR', notes = 'Invalid net quantity for selling' WHERE id = %s", (order['id'],))
                continue

            symbol = f"{order['asset_name']}{config.TRADING['QUOTE_ASSET']}"
            exit_price = order['exit_price']
            
            # ==================================================================
            # ***!!! فیکس جدید: گرد کردن مقدار فروش بر اساس دقت اعشار !!!***
            # ==================================================================
            
            # ۱. گرفتن دقت اعشار برای این نماد
            precision = wallex_api.market_precisions.get(symbol)
            if precision is None:
                logging.warning(f"قانون دقت اعشار برای {symbol} (جهت فروش) یافت نشد. نادیده گرفته شد.")
                db_utils.query_db("UPDATE trade_signals SET status = 'ERROR', notes = %s WHERE id = %s", (f"Precision not found for {symbol} (sell)", order['id']))
                continue
                
            # ۲. گرد کردن مقدار فروش (با همان تابع format_quantity)
            formatted_quantity_to_sell = wallex_api.format_quantity(quantity_to_sell_raw, precision)
            
            logging.info(f"مقدار فروش برای {symbol}: {formatted_quantity_to_sell} (خام: {quantity_to_sell_raw})")

            if formatted_quantity_to_sell <= 0:
                logging.warning(f"مقدار فروش برای {symbol} پس از گرد کردن 0 شد. نادیده گرفته شد.")
                db_utils.query_db("UPDATE trade_signals SET status = 'ERROR', notes = %s WHERE id = %s", (f"Sell quantity 0 after formatting (raw: {quantity_to_sell_raw})", order['id']))
                continue

            # ۳. ثبت سفارش فروش با مقدار گرد شده
            sell_response = wallex_api.place_wallex_order(symbol, exit_price, formatted_quantity_to_sell, "sell")
            
            if sell_response:
                sell_order_id = sell_response.get("result", {}).get("clientOrderId")
                db_utils.query_db(
                    "UPDATE trade_signals SET status = 'SELL_ORDER_PLACED', sell_client_order_id = %s WHERE id = %s",
                    (sell_order_id, order['id'])
                )
                logging.info(f"سفارش فروش برای {symbol} با ID: {sell_order_id} ثبت شد.")
            else:
                logging.error(f"خطا در ثبت سفارش فروش برای {symbol} (ID: {order['id']}).")
                # وضعیت را تغییر نمی‌دهیم تا در چرخه بعدی دوباره تلاش شود
                
        except Exception as e:
            logging.error(f"خطا در place_sell_orders برای ID {order['id']}: {e}")
            db_utils.query_db("UPDATE trade_signals SET status = 'ERROR', notes = %s WHERE id = %s", (str(e), order['id']))


def check_filled_sells():
    """
    مرحله ۴: سفارشات 'SELL_ORDER_PLACED' را بررسی می‌کند.
    اگر تکمیل شده باشند، وضعیت را به 'SELL_ORDER_FILLED' (پایان موفقیت‌آمیز) تغییر می‌دهد.
    """
    logging.info("[مرحله ۴] در حال بررسی وضعیت سفارشات فروش ثبت شده...")
    orders = db_utils.query_db("SELECT id, sell_client_order_id FROM trade_signals WHERE status = 'SELL_ORDER_PLACED'", fetch='all')

    if not orders:
        logging.info("[مرحله ۴] هیچ سفارش فروشی در انتظار بررسی وضعیت نیست.")
        return

    for order in orders:
        try:
            wallex_order = wallex_api.get_wallex_order_status(order['sell_client_order_id'])
            
            # فیکس قبلی: تغییر از 'DONE' به 'FILLED'
            if wallex_order and wallex_order.get("status") == 'FILLED':
                logging.info(f"سفارش فروش {order['sell_client_order_id']} تکمیل (FILLED) شده است!")
                
                executed_qty = Decimal(wallex_order.get("executedQty", "0"))
                fee = Decimal(wallex_order.get("fee", "0"))
                
                db_utils.query_db(
                    "UPDATE trade_signals SET status = 'SELL_ORDER_FILLED', sell_executed_quantity = %s, sell_fee = %s, notes = 'Trade completed successfully' WHERE id = %s",
                    (executed_qty, fee, order['id'])
                )
                logging.info(f"--- چرخه معامله برای ID {order['id']} با موفقیت بسته شد ---")
            
            elif wallex_order:
                logging.info(f"سفارش فروش {order['sell_client_order_id']} هنوز باز است (وضعیت: {wallex_order.get('status')}).")
            else:
                logging.warning(f"اطلاعاتی برای سفارش فروش {order['sell_client_order_id']} از والکس دریافت نشد.")
                
        except Exception as e:
            logging.error(f"خطا در check_filled_sells برای ID {order['id']}: {e}")
            db_utils.query_db("UPDATE trade_signals SET status = 'ERROR', notes = %s WHERE id = %s", (str(e), order['id']))


def main_executor_loop():
    """حلقه اصلی ماژول مجری سفارشات."""
    logging.info("ماژول مجری سفارش (Executor) شروع به کار کرد.")
    
    # بارگذاری قوانین دقت اعشار قبل از شروع حلقه
    if not wallex_api.load_market_precisions():
        logging.critical("امکان بارگذاری قوانین بازار وجود ندارد. مجری سفارش متوقف شد.")
        return

    while True:
        try:
            # اجرای ۴ مرحله به ترتیب
            process_new_signals()
            check_filled_buys()
            place_sell_orders()
            check_filled_sells()
            
        except Exception as e:
            logging.critical(f"خطای بحرانی در حلقه اصلی مجری سفارش: {e}")
            
        logging.info(f"--- پایان چرخه اجرا. خواب به مدت {config.BOT['ORDER_MANAGEMENT_INTERVAL_SECONDS']} ثانیه... ---")
        time.sleep(config.BOT["ORDER_MANAGEMENT_INTERVAL_SECONDS"])


if __name__ == "__main__":
    main_executor_loop()
