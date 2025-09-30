# config.py

# ==============================================================================
# 1. STRATEGY API CONFIGURATION
# ==============================================================================
STRATEGY_API = {
    "URL": "http://103.75.198.172:5005/Internal/arbitrage"
}

# ==============================================================================
# 2. WALLEX EXCHANGE API CONFIGURATION
# ==============================================================================
WALLEX_API = {
    "API_KEY": "16452|hHtZAYX8YU1pHZdpfJ8AIIdeJ1d94UY699AdM8pB", # <-- IMPORTANT: Replace with your actual key
    "BASE_URL": "https://api.wallex.ir",
    "ENDPOINTS": {
        "ALL_MARKETS": "/hector/web/v1/markets",
        "ACCOUNT_BALANCES": "/v1/account/balances",
        "ORDERS": "/v1/account/orders",
        "GET_ORDER": "/v1/account/orders/" # Endpoint to get a specific order's status
    }
}

# ==============================================================================
# 3. TRADING PARAMETERS
# ==============================================================================
TRADING = {
    "TRADE_AMOUNT_TMN": 60000,
    "QUOTE_ASSET": "TMN",
    "MIN_PROFIT_PERCENTAGE": 0.5
}

# ==============================================================================
# 4. BOT SETTINGS
# ==============================================================================
BOT = {
    "SIGNAL_CHECK_INTERVAL_SECONDS": 60, # Check for new signals every 60 seconds
    "ORDER_MANAGEMENT_INTERVAL_SECONDS": 30 # Manage open orders every 30 seconds
}

# ==============================================================================
# 5. DATABASE CONFIGURATION
# ==============================================================================
DATABASE = {
    "host": "localhost",
    "user": "bot_user",
    "password": "YourStrongPassword123!", # <-- IMPORTANT: Replace with the password you created
    "database": "trade_internal"
}