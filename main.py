import requests
import time
import json
import logging
import mysql.connector
import threading

# Import settings from the config file
import config

# Set up basic logging to see the bot's activity
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s')

# --- API & DATABASE FUNCTIONS ---

def get_strategy_signal():
    """Fetches the arbitrage signal from your custom API."""
    try:
        response = requests.get(config.STRATEGY_API["URL"], timeout=10)
        return response.json() if response.status_code == 200 else None
    except requests.exceptions.RequestException as e:
        logging.error(f"Could not connect to Strategy API: {e}")
        return None

def place_wallex_order(symbol, price, quantity, side):
    """Places a new order on the Wallex exchange."""
    url = config.WALLEX_API["BASE_URL"] + config.WALLEX_API["ENDPOINTS"]["ORDERS"]
    headers = {"Content-Type": "application/json", "x-api-key": config.WALLEX_API["API_KEY"]}
    payload = {"symbol": symbol, "price": str(price), "quantity": str(quantity), "side": side, "type": "limit"}
    
    logging.info(f"Placing order: {side.upper()} {quantity:.6f} {symbol} @ {price}")
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

def create_db_connection():
    """Creates a new connection to the MySQL database."""
    try:
        return mysql.connector.connect(**config.DATABASE)
    except mysql.connector.Error as e:
        logging.error(f"Error connecting to MySQL Database: {e}")
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

# --- BOT LOGIC LOOPS ---

def signal_checking_loop():
    """The main loop for checking for new trading signals."""
    logging.info("Signal checking loop started.")
    while True:
        signal_data = get_strategy_signal()
        if signal_data and signal_data.get("opportunities_found", 0) > 0:
            for opportunity in signal_data["opportunities"]:
                asset_name = opportunity.get("asset_name")
                entry_price = opportunity.get("entry_price")
                if not all([asset_name, entry_price]):
                    logging.warning("Incomplete data in opportunity, skipping.")
                    continue
                
                # Check if an open order already exists for this asset
                open_order = query_db("SELECT COUNT(*) as count FROM trading_orders WHERE asset_name = %s AND status NOT IN ('COMPLETED', 'CANCELLED')", (asset_name,), fetch='one')
                if open_order and open_order['count'] > 0:
                    logging.info(f"An open order for '{asset_name}' already exists. Skipping.")
                    continue
                
                symbol = f"{asset_name}{config.TRADING['QUOTE_ASSET']}"
                quantity_to_buy = config.TRADING["TRADE_AMOUNT_TMN"] / entry_price
                
                order_response = place_wallex_order(symbol, entry_price, quantity_to_buy, "buy")
                
                if order_response:
                    order_result = order_response.get("result", {})
                    query_db(
                        "INSERT INTO trading_orders (client_order_id, symbol, asset_name, entry_price, exit_price, quantity, status) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (order_result.get("clientOrderId"), symbol, asset_name, opportunity.get("entry_price"), opportunity.get("exit_price"), quantity_to_buy, "BUY_ORDER_PLACED")
                    )
        else:
            logging.info("No new opportunities found.")
        
        time.sleep(config.BOT["SIGNAL_CHECK_INTERVAL_SECONDS"])

def order_management_loop():
    """The loop for managing open orders and placing sell orders."""
    logging.info("Order management loop started.")
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

# --- START THE BOT ---

if __name__ == "__main__":
    logging.info("Starting the trading bot...")

    # Create two separate threads for our two main loops
    signal_thread = threading.Thread(target=signal_checking_loop, name="SignalChecker")
    order_thread = threading.Thread(target=order_management_loop, name="OrderManager")

    # Start the threads
    signal_thread.start()
    order_thread.start()

    # Keep the main script alive
    signal_thread.join()
    order_thread.join()
    
    logging.info("Bot has stopped.")