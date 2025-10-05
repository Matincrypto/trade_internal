import requests
import time
import logging
import mysql.connector

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
    payload = {
        "chat_id": chat_id,
        "text": message_text,
        "parse_mode": "Markdown"  # Allows for bold, italics, etc.
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logging.info("Successfully sent Telegram alert.")
        else:
            logging.error(f"Failed to send Telegram alert. Status: {response.status_code}, Response: {response.text}")
    except requests.exceptions.RequestException as e:
        logging.error(f"An error occurred while sending Telegram alert: {e}")

# --- Main Monitoring Loop ---

def monitor_loop():
    """
    The main loop that reads the database and sends status updates to Telegram.
    """
    logging.info("Telegram monitoring script started.")
    
    while True:
        connection = create_db_connection()
        if not connection:
            logging.error("Could not connect to the database. Retrying in 60 seconds.")
            time.sleep(60)
            continue

        try:
            cursor = connection.cursor(dictionary=True)
            # Fetch all orders that are not in a final state
            query = """
                SELECT symbol, status, entry_price, quantity, created_at 
                FROM trading_orders 
                WHERE status NOT IN ('COMPLETED', 'CANCELED_TIMEOUT') 
                ORDER BY created_at ASC
            """
            cursor.execute(query)
            active_orders = cursor.fetchall()

            message = "📈 **گزارش وضعیت ربات تریدر** 📈\n\n"

            if not active_orders:
                message += "✅ **در حال حاضر هیچ پوزیشن فعالی وجود ندارد.**"
            else:
                message += f"🔍 **تعداد پوزیشن‌های فعال: {len(active_orders)}**\n\n"
                for order in active_orders:
                    # Format the creation time to be more readable
                    created_time = order['created_at'].strftime('%Y-%m-%d %H:%M:%S')
                    
                    status_emoji = {
                        "BUY_ORDER_PLACED": "🛒",
                        "BUY_ORDER_FILLED": "✅"
                    }.get(order['status'], '⚙️')

                    message += (
                        f"{status_emoji} **ارز:** `{order['symbol']}`\n"
                        f"   - **وضعیت:** {order['status']}\n"
                        f"   - **قیمت ورود:** {order['entry_price']}\n"
                        f"   - **مقدار:** {order['quantity']}\n"
                        f"   - **زمان ثبت:** {created_time}\n"
                        f"------------------------------------\n"
                    )
            
            send_telegram_alert(message)

        except mysql.connector.Error as e:
            logging.error(f"A database error occurred in the monitor loop: {e}")
            send_telegram_alert(f"🚨 خطای دیتابیس در ربات مانیتورینگ: {e}")
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
        
        # Wait for the next check
        logging.info(f"Waiting for {config.BOT['MONITOR_INTERVAL_SECONDS']} seconds until the next report.")
        time.sleep(config.BOT['MONITOR_INTERVAL_SECONDS'])

# --- Start the Script ---

if __name__ == "__main__":
    monitor_loop()