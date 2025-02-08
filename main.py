# main.py

import logging
import os
from telegram.ext import Updater, CommandHandler
from config import TELEGRAM_BOT_TOKEN, DEBUG, LOG_FILE
from handlers.auth import auth_handler
from handlers.menu import menu_handler, show_main_menu
from handlers.ordenar import ordenar_handler
from handlers.carritos import carritos_handler
from handlers.historial import historial_handler
from handlers.pedidos import pending_orders_handler, pedidos_back_handler, complete_order_conv_handler

# Configuración de logging: se escribe tanto en consola como en el archivo de logs.
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG if DEBUG else logging.INFO,
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def error_handler(update, context):
    """Maneja y registra los errores ocurridos durante la actualización."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

def main():
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # Registro de todos los handlers...
    # dp.add_handler(auth_handler)
    # dp.add_handler(menu_handler)
    # dp.add_handler(ordenar_handler)
    # dp.add_handler(carritos_handler)
    # dp.add_handler(historial_handler)
    # dp.add_handler(pending_orders_handler)
    # dp.add_handler(pedidos_back_handler)
    # dp.add_handler(complete_order_conv_handler)
    # ... y demás comandos/handlers

    # Comprobar si estamos en un entorno de producción (por ejemplo, Heroku)
    HEROKU_APP_NAME = os.environ.get("HEROKU_APP_NAME")
    if HEROKU_APP_NAME:
        # Configuración de Webhook para Heroku
        PORT = int(os.environ.get("PORT", "8443"))
        updater.start_webhook(listen="0.0.0.0",
                              port=PORT,
                              url_path=TELEGRAM_BOT_TOKEN)
        webhook_url = f"https://{HEROKU_APP_NAME}.herokuapp.com/{TELEGRAM_BOT_TOKEN}"
        updater.bot.setWebhook(webhook_url)
        print(f"Webhook configurado en: {webhook_url}")
    else:
        # Modo polling para desarrollo
        updater.start_polling()
        print("Bot iniciado en modo polling...")

    dp.add_error_handler(lambda update, context: print(f"Error: {context.error}"))
    updater.idle()

if __name__ == '__main__':
    main()
