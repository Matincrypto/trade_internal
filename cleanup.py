import requests
import time
import logging
import mysql.connector
from datetime import datetime, timedelta
import pytz

# Import settings from the config file
import config

# Set up basic logging to see the script's activity
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Helper Functions ---

def create_db_connection():
    """Creates a new connection to the MySQL database."""
    try:
        return mysql.connector.connect(**config.DATABASE)
    except mysql.connector.Error as e:
        logging.error(f"Error connecting to MySQL: {e}")
        return None

def cancel_wallex_order(client_order_id):
    """Sends a request to Wallex to cancel an order."""
    url = config.WALLEX_API["BASE_URL"] + config.WALLEX_API["ENDPOINTS"]["ORDERS"]
    headers = {"Content-Type": "application/json", "x-api-key": config.WALLEX_API["API_KEY"]}
    payload = {"clientOrderId": client_order_id}
    
    logging.info(f"Attempting to cancel order {client_order_id} on Wallex...")
    try:
        response = requests.delete(url, headers=headers, json=payload, timeout=15)
        if response.status_code == 200 and response.json().get("success"):
            logging.info(f"Successfully canceled order {client_order_id} on Wallex.")
            return True
        else:
            logging.error(f"Failed to cancel order {client_order_id}. Status: {response.status_code}, Response: {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        logging.error(f"An error occurred while canceling order on Wallex: {e}")
        return False

def update_order_status(client_order_id, new_status):
    """Updates the status of an order in the database."""
    connection = create_db_connection()
    if not connection: return
    try:
        cursor = connection.cursor()
        query = "UPDATE trading_orders SET status = %s WHERE client_order_id = %s"
        cursor.execute(query, (new_status, client_order_id))
        connection.commit()
        logging.info(f"Successfully updated status for order {client_order_id} to '{new_status}'.")
    except mysql.connector.Error as e:
        logging.error(f"Failed to update status for order {client_order_id} in DB: {e}")
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

# --- Main Cleanup Loop ---

def cleanup_loop():
    """
    The main loop that checks for and cleans up stale orders.
    """
    logging.info("Cleanup script started. Looking for stale orders...")
    
    tehran_tz = pytz.timezone("Asia/Tehran")
    
    while True:
        connection = create_db_connection()
        if not connection:
            time.sleep(60)
            continue

        try:
            cursor = connection.cursor(dictionary=True)
            query = "SELECT client_order_id, created_at FROM trading_orders WHERE status = 'BUY_ORDER_PLACED'"
            cursor.execute(query)
            open_orders = cursor.fetchall()
            
            if open_orders:
                logging.info(f"Found {len(open_orders)} open buy orders. Checking their age...")
                
                now_in_tehran = datetime.now(tehran_tz)
                
                for order in open_orders:
                    order_time_utc = order['created_at'].replace(tzinfo=pytz.utc)
                    age = now_in_tehran - order_time_utc
                    
                    if age.total_seconds() > 300: # 5-minute timeout
                        logging.warning(f"Order {order['client_order_id']} is stale (age: {age}). Starting cancellation process.")
                        
                        # 1. Cancel the order on the exchange
                        if cancel_wallex_order(order['client_order_id']):
                            # 2. If cancellation was successful, UPDATE its status in our database
                            update_order_status(order['client_order_id'], 'CANCELED_TIMEOUT')
                    else:
                        logging.info(f"Order {order['client_order_id']} is fresh (age: {age}). Skipping.")
            else:
                logging.info("No open buy orders to check for cleanup.")

        except mysql.connector.Error as e:
            logging.error(f"A database error occurred in the cleanup loop: {e}")
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
        
        time.sleep(60)

# --- Start the Script ---

if __name__ == "__main__":
    cleanup_loop()