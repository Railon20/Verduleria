# config.py

# Token del bot de Telegram
TELEGRAM_BOT_TOKEN = "7912624181:AAHANGp_BehSTkPO_h-PKWQ2Xrq1RZA2LN4"

# Configuración de Mercado Pago (Checkout Pro)
MERCADO_PAGO_ACCESS_TOKEN = "APP_USR-6499289843479865-011213-c4290cd71ad5e17a9cec6f6e90c4de2c-1368333589"
MERCADO_PAGO_PUBLIC_KEY = "APP_USR-d8e6b83e-9e3b-4d81-80f2-5959557cf9bf"

# Configuración de la base de datos
# Para desarrollo se puede usar SQLite. Para producción, cambiar a PostgreSQL, MySQL, etc.
DATABASE_URI = "sqlite:///verduleria_bot.db"

# Configuración de logging
LOG_FILE = "logs/bot.log"

# Otros parámetros de configuración (puedes extender según necesidades)
DEBUG = True
