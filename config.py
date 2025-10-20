# config.py

import logging

# ==============================================================================
# 1. STRATEGY API CONFIGURATION
# ==============================================================================
STRATEGY_API = {
    # یک دیکشنری برای نگهداری منابع سیگنال
    # ما فقط یک منبع داریم، اما ساختار برای آینده آماده است
    "SOURCES": {
        "Internal_Arbitrage": "http://103.75.198.172:5005/Internal/arbitrage"
    }
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
        "ORDERS": "/v1/account/orders",          # POST (New Order), DELETE (Cancel Order)
        "GET_ORDER": "/v1/account/orders/"  # GET (Get Order Status) - e.g., /v1/account/orders/CLIENT_ID_123
    }
}

# ==============================================================================
# 3. TRADING PARAMETERS
# ==============================================================================
TRADING = {
    "TRADE_AMOUNT_TMN": 60000,      # مقدار معامله بر حسب تومان
    "QUOTE_ASSET": "TMN",           # بازار پایه ما (تومان)
}

# ==============================================================================
# 4. BOT SETTINGS
# ==============================================================================
BOT = {
    "SIGNAL_CHECK_INTERVAL_SECONDS": 350,    # بررسی سیگنال جدید هر 60 ثانیه
    "ORDER_MANAGEMENT_INTERVAL_SECONDS": 5,# بررسی وضعیت سفارشات هر 30 ثانیه
    "CLEANUP_INTERVAL_SECONDS": 5,         # بررسی سفارشات قدیمی هر 60 ثانیه
    "LOG_LEVEL": logging.INFO,
    "STALE_ORDER_TIMEOUT_MINUTES": 5        # سفارش خرید بعد از 5 دقیقه لغو می‌شود
}

# ==============================================================================
# 5. DATABASE CONFIGURATION
# ==============================================================================
DATABASE = {
    "host": "localhost",
    "user": "bot_user",
    "password": "YourStrongPassword123!", # <-- IMPORTANT: Replace with your password
    "database": "trade_internal"

}
