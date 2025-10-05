import requests
import time
import json
import logging
import mysql.connector
import threading
import math

# Import settings from the config file
import config

# Set up basic logging to see the bot's activity
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s')

# A global dictionary to store market rules (precision)
market_precisions = {}

# --- Helper Functions ---

def load_market_precisions():
    """Fetches all market rules from Wallex and stores their precision."""
    logging.info("Loading market precision rules from Wallex...")
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
            logging.info(f"Successfully loaded precision rules for {len(market_precisions)} markets.")
            return True
        else:
            logging.error("Failed to load market precision rules.")
            return False
    except requests.exceptions.RequestException as e:
        logging.error(f"Error loading market precision rules: {e}")
        return False

def format_quantity(quantity, precision):
    """Formats the quantity to the correct number of decimal places by flooring it."""
    factor = 10 ** precision
    return math.floor(quantity * factor) / factor

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
            
# --- The Main Loop for Finding Signals and Placing BUY Orders ---

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
                
                symbol = f"{asset_name}{config.TRADING['QUOTE_ASSET']}"
                
                precision = market_precisions.get(symbol)
                if precision is None:
                    logging.warning(f"No precision rule found for symbol '{symbol}'. Skipping.")
                    continue

                # Updated query to ignore timed-out orders
                open_order = query_db(
                    "SELECT COUNT(*) as count FROM trading_orders WHERE asset_name = %s AND status NOT IN ('COMPLETED', 'CANCELED_TIMEOUT')",
                    (asset_name,), 
                    fetch='one'
                )
                if open_order and open_order['count'] > 0:
                    logging.info(f"An open order for '{asset_name}' already exists. Skipping.")
                    continue
                
                quantity_to_buy_raw = config.TRADING["TRADE_AMOUNT_TMN"] / entry_price
                formatted_quantity = format_quantity(quantity_to_buy_raw, precision)
                
                if formatted_quantity <= 0:
                    logging.warning(f"Calculated quantity for {symbol} is too small to trade after formatting. Skipping.")
                    continue

                order_response = place_wallex_order(symbol, entry_price, formatted_quantity, "buy")
                
                if order_response:
                    order_result = order_response.get("result", {})
                    query_db(
                        "INSERT INTO trading_orders (client_order_id, symbol, asset_name, entry_price, exit_price, quantity, status) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (order_result.get("clientOrderId"), symbol, asset_name, opportunity.get("entry_price"), opportunity.get("exit_price"), formatted_quantity, "BUY_ORDER_PLACED")
                    )
        else:
            logging.info("No new opportunities found.")
        
        time.sleep(config.BOT["SIGNAL_CHECK_INTERVAL_SECONDS"])

# --- Start the Bot ---

if __name__ == "__main__":
    logging.info("Starting the Signal Checker bot...")
    
    if load_market_precisions():
        signal_thread = threading.Thread(target=signal_checking_loop, name="SignalChecker")
        signal_thread.start()
        signal_thread.join()
    else:
        logging.critical("Could not load market rules. Bot is shutting down.")
    
    logging.info("Signal Checker bot has stopped.")