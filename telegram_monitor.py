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
        "parse_mode": "Markdown"
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logging.info("Successfully sent Telegram alert.")
        else:
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
        logging.info(f"Updated notified_status for {client_order_id} to '{new_status}'")
    except mysql.connector.Error as e:
        logging.error(f"DB Error while updating notified_status: {e}")
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

# --- Main Monitoring Loop ---

def monitor_loop():
    """
    The main loop that finds orders with a new, un-notified status and sends alerts.
    """
    logging.info("Event-based Telegram monitoring script started.")
    
    while True:
        connection = create_db_connection()
        if not connection:
            logging.error("Could not connect to the database. Retrying in 60 seconds.")
            time.sleep(60)
            continue

        try:
            cursor = connection.cursor(dictionary=True)
            # This query finds orders where the current status is different from the last notified status
            # The <=> operator correctly handles NULL values.
            query = "SELECT * FROM trading_orders WHERE NOT status <=> notified_status"
            cursor.execute(query)
            orders_to_notify = cursor.fetchall()

            if not orders_to_notify:
                logging.info("No new status changes to notify.")
            else:
                logging.info(f"Found {len(orders_to_notify)} order(s) with new status changes.")
                for order in orders_to_notify:
                    message = ""
                    status = order['status']
                    
                    if status == "BUY_ORDER_PLACED":
                        message = (
                            f"✅ **ثبت سفارش خرید جدید** ✅\n\n"
                            f"- **ارز:** `{order['symbol']}`\n"
                            f"- **قیمت ورود:** `{order['entry_price']}`\n"
                            f"- **مقدار:** `{order['quantity']}`\n"
                            f"- **ID:** `{order['client_order_id']}`"
                        )
                    elif status == "BUY_ORDER_FILLED":
                        message = (
                            f"🟢 **سفارش خرید تکمیل شد** 🟢\n\n"
                            f"- **ارز:** `{order['symbol']}`\n"
                            f"- **ID:** `{order['client_order_id']}`"
                        )
                    elif status == "COMPLETED":
                        message = (
                            f"📈 **سفارش فروش ثبت شد (تکمیل چرخه)** 📈\n\n"
                            f"- **ارز:** `{order['symbol']}`\n"
                            f"- **قیمت خروج:** `{order['exit_price']}`\n"
                            f"- **مقدار:** `{order['quantity']}`"
                        )
                    elif status == "CANCELED_TIMEOUT":
                        message = (
                            f"❌ **لغو سفارش (Timeout)** ❌\n\n"
                            f"- **ارز:** `{order['symbol']}`\n"
                            f"- **ID:** `{order['client_order_id']}`"
                        )
                    
                    if message:
                        send_telegram_alert(message)
                        # Mark this status as notified to prevent duplicate messages
                        update_notification_status(order['client_order_id'], status)

        except mysql.connector.Error as e:
            logging.error(f"A database error occurred in the monitor loop: {e}")
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
        
        # You can adjust the check interval here. 60 seconds is reasonable.
        check_interval = 60 
        logging.info(f"Waiting for {check_interval} seconds until the next check.")
        time.sleep(check_interval)

# --- Start the Script ---

if __name__ == "__main__":
    monitor_loop()
