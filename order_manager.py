import requests
import time
import json
import logging
import mysql.connector

# Import settings from the config file
import config

# Set up basic logging to see the bot's activity
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s')

# --- Helper Functions (Copied from main.py) ---

def create_db_connection():
    """Creates a new connection to the MySQL database."""
    try:
        return mysql.connector.connect(**config.DATABASE)
    except mysql.connector.Error as e:
        logging.error(f"Error connecting to MySQL: {e}")
        return None

def query_db(query, params=None, fetch=None):
    """A general-purpose function to query the database."""
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
        logging.error(f"Database query failed: {e}")
        return None
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def get_wallex_order_status(client_order_id):
    """Gets the status of a specific order from Wallex."""
    url = config.WALLEX_API["BASE_URL"] + config.WALLEX_API["ENDPOINTS"]["GET_ORDER"] + client_order_id
    headers = {"x-api-key": config.WALLEX_API["API_KEY"]}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        return response.json().get("result") if response.status_code == 200 and response.json().get("success") else None
    except requests.exceptions.RequestException as e:
        logging.error(f"Error getting order status from Wallex: {e}")
        return None

def place_wallex_order(symbol, price, quantity, side):
    """Places a new order on the Wallex exchange."""
    url = config.WALLEX_API["BASE_URL"] + config.WALLEX_API["ENDPOINTS"]["ORDERS"]
    headers = {"Content-Type": "application/json", "x-api-key": config.WALLEX_API["API_KEY"]}
    payload = {"symbol": symbol, "price": str(price), "quantity": str(quantity), "side": side, "type": "limit"}
    
    logging.info(f"Placing order: {side.upper()} {quantity} {symbol} @ {price}")
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=15)
        response_data = response.json()
        if response.status_code == 201 and response_data.get("success"):
            order_id = response_data.get("result", {}).get("clientOrderId")
            logging.info(f"Successfully placed order! Order ID: {order_id}")
            return response_data
        else:
            logging.error(f"Failed to place order. Status: {response.status_code}, Response: {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"An error occurred while placing order on Wallex: {e}")
        return None
        
# --- Main Order Management Loop ---

def order_management_loop():
    """The loop for managing open orders and placing sell orders."""
    logging.info("Order management script started.")
    while True:
        open_orders = query_db("SELECT * FROM trading_orders WHERE status = 'BUY_ORDER_PLACED'", fetch='all')
        
        if open_orders:
            logging.info(f"Found {len(open_orders)} open buy order(s) to check.")
            for order in open_orders:
                client_id = order["client_order_id"]
                wallex_order_status = get_wallex_order_status(client_id)
                
                if wallex_order_status and wallex_order_status.get("status") == 'DONE':
                    logging.info(f"Buy order {client_id} is filled! Placing sell order.")
                    query_db("UPDATE trading_orders SET status = %s WHERE client_order_id = %s", ("BUY_ORDER_FILLED", client_id))
                    
                    sell_response = place_wallex_order(order["symbol"], order["exit_price"], order["quantity"], "sell")
                    if sell_response:
                        query_db("UPDATE trading_orders SET status = %s WHERE client_order_id = %s", ("SELL_ORDER_PLACED", client_id))
        else:
            logging.info("No open buy orders to manage.")

        time.sleep(config.BOT["ORDER_MANAGEMENT_INTERVAL_SECONDS"])
        
# --- Start the Script ---

if __name__ == "__main__":
    order_management_loop()