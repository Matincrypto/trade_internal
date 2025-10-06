import requests
import time
import json
import logging
import mysql.connector
import decimal

# Import settings from the config file
import config

# Set up basic logging to see the bot's activity
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s')

# --- Helper Functions ---

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

def get_wallex_balances():
    """Fetches all account balances from Wallex and returns a simplified dictionary."""
    url = config.WALLEX_API["BASE_URL"] + config.WALLEX_API["ENDPOINTS"]["ACCOUNT_BALANCES"]
    headers = {"x-api-key": config.WALLEX_API["API_KEY"]}
    
    logging.info("Fetching account balances from Wallex...")
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200 and response.json().get("success"):
            balances_data = response.json().get("result", {}).get("balances", [])
            balances_map = {
                item['asset']: decimal.Decimal(item['available'])
                for item in balances_data
            }
            logging.info(f"Successfully fetched balances for {len(balances_map)} assets.")
            return balances_map
        else:
            logging.error(f"Failed to fetch balances. Status: {response.status_code}, Response: {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"An error occurred while fetching Wallex balances: {e}")
        return None

def place_wallex_order(symbol, price, quantity, side):
    """Places a new order on the Wallex exchange."""
    url = config.WALLEX_API["BASE_URL"] + config.WALLEX_API["ENDPOINTS"]["ORDERS"]
    headers = {"Content-Type": "application/json", "x-api-key": config.WALLEX_API["API_KEY"]}
    payload = {"symbol": symbol, "price": str(price), "quantity": str(quantity), "side": side, "type": "limit"}
    
    logging.info(f"Placing order: {side.upper()} {quantity} {symbol} @ {price}")
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
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
    """The unified loop for managing the entire order lifecycle after a buy order is placed."""
    logging.info("Unified Order Management script started.")
    while True:
        logging.info("--- Starting new order management cycle ---")

        # --- STEP 1: Check for newly filled buy orders ---
        open_buy_orders = query_db("SELECT * FROM trading_orders WHERE status = 'BUY_ORDER_PLACED'", fetch='all')
        if open_buy_orders:
            logging.info(f"[STEP 1] Found {len(open_buy_orders)} open buy order(s) to check status.")
            for order in open_buy_orders:
                client_id = order["client_order_id"]
                wallex_order_status = get_wallex_order_status(client_id)
                
                if wallex_order_status and wallex_order_status.get("status") == 'DONE':
                    logging.info(f"Buy order {client_id} is filled! Updating status to BUY_ORDER_FILLED.")
                    query_db("UPDATE trading_orders SET status = %s WHERE client_order_id = %s", ("BUY_ORDER_FILLED", client_id))
        else:
            logging.info("[STEP 1] No open buy orders found.")

        # --- STEP 2: Process filled buys, verify balance, and place sell orders ---
        filled_buy_orders = query_db("SELECT * FROM trading_orders WHERE status = 'BUY_ORDER_FILLED'", fetch='all')
        if filled_buy_orders:
            logging.info(f"[STEP 2] Found {len(filled_buy_orders)} filled order(s) to process for selling.")
            
            wallex_balances = get_wallex_balances()
            if wallex_balances is None:
                logging.warning("Could not fetch Wallex balances. Skipping sell processing for this cycle.")
            else:
                for order in filled_buy_orders:
                    asset = order['asset_name']
                    required_quantity = order['quantity']

                    if asset in wallex_balances and wallex_balances[asset] >= required_quantity:
                        logging.info(f"Asset '{asset}' for order {order['client_order_id']} confirmed in wallet. Placing sell order.")
                        
                        sell_response = place_wallex_order(
                            order["symbol"], 
                            order["exit_price"], 
                            order["quantity"], 
                            "sell"
                        )

                        if sell_response:
                            logging.info(f"Sell order for {order['client_order_id']} placed. Marking trade as COMPLETED.")
                            query_db("UPDATE trading_orders SET status = %s WHERE client_order_id = %s", ("COMPLETED", order['client_order_id']))
                        else:
                            logging.error(f"Failed to place sell order for {order['client_order_id']}. Will retry in the next cycle.")
                    else:
                        logging.warning(f"Order for asset '{asset}' found as FILLED, but not enough balance in Wallex wallet. Skipping.")
                        logging.warning(f"DB requires {required_quantity} of {asset}, Wallet has {wallex_balances.get(asset, 0)}.")
        else:
            logging.info("[STEP 2] No filled orders waiting for sell.")

        logging.info(f"--- Management cycle finished. Waiting for {config.BOT['ORDER_MANAGEMENT_INTERVAL_SECONDS']} seconds. ---")
        time.sleep(config.BOT["ORDER_MANAGEMENT_INTERVAL_SECONDS"])
        
# --- Start the Script ---

if __name__ == "__main__":
    order_management_loop()