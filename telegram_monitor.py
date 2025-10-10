import requests
import time
import logging
import mysql.connector
from datetime import datetime

# Import settings from the config file
import config

# Set up basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Helper Functions ---

def create_db_connection():
    """Creates a new connection to the MySQL database."""
    try:
        return mysql.connector.connect(**config.DATABASE)
    except mysql.connector.Error as e:
        logging.error(f"Error connecting to MySQL: {e}")
        return None

def send_telegram_alert(message_text):
    """Sends a message to the configured Telegram chat."""
    token = config.TELEGRAM.get("BOT_TOKEN")
    chat_id = config.TELEGRAM.get("CHAT_ID")
    if not token or not chat_id:
        logging.error("Telegram BOT_TOKEN or CHAT_ID is not configured.")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message_text, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            logging.error(f"Failed to send Telegram alert. Status: {response.status_code}, Response: {response.text}")
    except requests.exceptions.RequestException as e:
        logging.error(f"An error occurred while sending Telegram alert: {e}")

def update_notification_status(client_order_id, new_status):
    """Updates the notified_status in the database for a given order."""
    connection = create_db_connection()
    if not connection: return
    try:
        cursor = connection.cursor()
        query = "UPDATE trading_orders SET notified_status = %s WHERE client_order_id = %s"
        cursor.execute(query, (new_status, client_order_id))
        connection.commit()
    except mysql.connector.Error as e:
        logging.error(f"DB Error while updating notified_status: {e}")
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

# --- Main Monitoring Loop ---

def monitor_loop():
    """
    Sends a comprehensive report every 10 minutes, including recent changes and current active status.
    """
    logging.info("Comprehensive log monitor started.")
    
    while True:
        connection = create_db_connection()
        if not connection:
            time.sleep(60)
            continue

        try:
            cursor = connection.cursor(dictionary=True)
            
            # --- Part 1: Find and Report Recent Changes ---
            query_changes = "SELECT * FROM trading_orders WHERE NOT status <=> notified_status"
            cursor.execute(query_changes)
            orders_with_changes = cursor.fetchall()

            changes_report = "📈 **گزارش تغییرات اخیر** 📈\n\n"
            if not orders_with_changes:
                changes_report += "🔹 در ۱۰ دقیقه گذشته هیچ تغییر وضعیتی ثبت نشده است.\n"
            else:
                for order in orders_with_changes:
                    status = order['status']
                    emoji = {
                        "BUY_ORDER_PLACED": "✅", "BUY_ORDER_FILLED": "🟢",
                        "COMPLETED": "📈", "CANCELED_TIMEOUT": "❌"
                    }.get(status, '⚙️')
                    
                    changes_report += (
                        f"{emoji} سفارش `{order['symbol']}`\n"
                        f"   - **ID:** `{order['client_order_id']}`\n"
                        f"   - **وضعیت جدید:** **{status}**\n"
                        f"------------------------------------\n"
                    )
                    # Mark this status as notified to prevent re-reporting
                    update_notification_status(order['client_order_id'], status)
            
            # --- Part 2: Find and Report Current Active Positions ---
            query_active = "SELECT * FROM trading_orders WHERE status NOT IN ('COMPLETED', 'CANCELED_TIMEOUT') ORDER BY created_at ASC"
            cursor.execute(query_active)
            active_orders = cursor.fetchall()

            active_report = "\n📊 **وضعیت فعلی پوزیشن‌های فعال** 📊\n\n"
            if not active_orders:
                active_report += "✅ **در حال حاضر هیچ پوزیشن فعالی وجود ندارد.**"
            else:
                active_report += f"🔍 **تعداد پوزیشن‌های فعال: {len(active_orders)}**\n\n"
                for order in active_orders:
                    created_time = order['created_at'].strftime('%Y-%m-%d %H:%M:%S')
                    emoji = {"BUY_ORDER_PLACED": "🛒", "BUY_ORDER_FILLED": "💰"}.get(order['status'], '⚙️')
                    active_report += (
                        f"{emoji} **ارز:** `{order['symbol']}`\n"
                        f"   - **وضعیت:** {order['status']}\n"
                        f"   - **قیمت ورود:** {order['entry_price']}\n"
                        f"   - **مقدار:** {order.get('executed_quantity') or order.get('quantity')}\n"
                        f"   - **زمان ثبت:** {created_time}\n"
                        f"------------------------------------\n"
                    )
            
            # --- Combine and Send the Full Report ---
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            full_report = f"🤖 **گزارش جامع ربات تریدر** 🤖\n_زمان: {current_time}_\n\n"
            full_report += changes_report
            full_report += active_report
            
            send_telegram_alert(full_report)

        except mysql.connector.Error as e:
            logging.error(f"A database error occurred in the monitor loop: {e}")
            send_telegram_alert(f"🚨 خطای دیتابیس در ربات لاگ: {e}")
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
        
        interval = config.BOT.get('MONITOR_INTERVAL_SECONDS', 600)
        logging.info(f"Report sent. Waiting for {interval} seconds until the next log report.")
        time.sleep(interval)

# --- Start the Script ---

if __name__ == "__main__":
    monitor_loop()
