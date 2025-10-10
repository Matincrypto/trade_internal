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
    """
    Gets the full details of a specific order from Wallex.
    This function is used both to check status and to get final details.
    """
    url = config.WALLEX_API["BASE_URL"] + config.WALLEX_API["ENDPOINTS"]["GET_ORDER"] + client_order_id
    headers = {"x-api-key": config.WALLEX_API["API_KEY"]}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        # Based on swagger, the response contains the full order resource
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
            balances_map = {item['asset']: decimal.Decimal(item['available']) for item in balances_data}
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

        # --- STEP 1: Check for newly filled buy orders and calculate net quantity ---
        open_buy_orders = query_db("SELECT * FROM trading_orders WHERE status = 'BUY_ORDER_PLACED'", fetch='all')
        if open_buy_orders:
            logging.info(f"[STEP 1] Found {len(open_buy_orders)} open buy order(s) to check.")
            for order in open_buy_orders:
                client_id = order["client_order_id"]
                # Get the full order details from Wallex
                wallex_order_details = get_wallex_order_status(client_id)
                
                if wallex_order_details and wallex_order_details.get("status") == 'DONE':
                    logging.info(f"Buy order {client_id} is filled!")
                    
                    # ==============================================================================
                    # MODIFICATION: Calculate net quantity from the exact fee paid
                    # ==============================================================================
                    executed_qty_str = wallex_order_details.get("executedQty", "0")
                    fee_str = wallex_order_details.get("fee", "0")
                    
                    try:
                        # Convert API string responses to Decimal for precision
                        executed_qty = decimal.Decimal(executed_qty_str)
                        fee = decimal.Decimal(fee_str)
                        
                        # Calculate the net quantity that actually hit the wallet
                        net_quantity = executed_qty - fee
                        
                        logging.info(f"Order {client_id} - Executed Qty: {executed_qty}, Fee: {fee}, Net Quantity: {net_quantity}")

                        # Update the database with the new status AND the precise net quantity
                        query_db(
                            "UPDATE trading_orders SET status = %s, executed_quantity = %s WHERE client_order_id = %s",
                            ("BUY_ORDER_FILLED", net_quantity, client_id)
                        )
                    except (decimal.InvalidOperation, TypeError) as e:
                        logging.error(f"Could not calculate net quantity for {client_id}. Error: {e}. Raw values: executedQty='{executed_qty_str}', fee='{fee_str}'")

        else:
            logging.info("[STEP 1] No open buy orders found.")

        # --- STEP 2: Process filled buys and place sell orders using the precise quantity ---
        filled_buy_orders = query_db("SELECT * FROM trading_orders WHERE status = 'BUY_ORDER_FILLED'", fetch='all')
        if filled_buy_orders:
            logging.info(f"[STEP 2] Found {len(filled_buy_orders)} filled order(s) to process for selling.")
            
            for order in filled_buy_orders:
                # ==============================================================================
                # MODIFICATION: Use the precise executed_quantity from the database for the sell order
                # ==============================================================================
                quantity_to_sell = order.get("executed_quantity")

                if not quantity_to_sell or quantity_to_sell <= 0:
                    logging.warning(f"Order {order['client_order_id']} has an invalid executed_quantity ({quantity_to_sell}). Skipping.")
                    continue

                logging.info(f"Preparing to sell precise quantity of {quantity_to_sell} for {order['symbol']}")
                
                sell_response = place_wallex_order(
                    order["symbol"], 
                    order["exit_price"], 
                    quantity_to_sell, 
                    "sell"
                )

                if sell_response:
                    logging.info(f"Sell order for {order['client_order_id']} placed. Marking trade as COMPLETED.")
                    query_db("UPDATE trading_orders SET status = %s WHERE client_order_id = %s", ("COMPLETED", order['client_order_id']))
                else:
                    logging.error(f"Failed to place sell order for {order['client_order_id']}. Will retry in the next cycle.")
        else:
            logging.info("[STEP 2] No filled orders waiting for sell.")

        logging.info(f"--- Management cycle finished. Waiting for {config.BOT['ORDER_MANAGEMENT_INTERVAL_SECONDS']} seconds. ---")
        time.sleep(config.BOT["ORDER_MANAGEMENT_INTERVAL_SECONDS"])
        
# --- Start the Script ---

if __name__ == "__main__":
    order_management_loop()
