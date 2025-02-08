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
    def main():
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # Registro de tus handlers...
    # dp.add_handler(auth_handler)
    # dp.add_handler(menu_handler)
    # ...

    # Configurar el webhook para Render usando un puerto permitido.
    # Si Render no provee la variable PORT o si quieres forzar un puerto permitido, usa 8443.
    PORT = int(os.environ.get("PORT", "8443"))
    RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")

    if RENDER_EXTERNAL_URL:
        updater.start_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TELEGRAM_BOT_TOKEN
        )
        webhook_url = f"{RENDER_EXTERNAL_URL}/{TELEGRAM_BOT_TOKEN}"
        updater.bot.set_webhook(webhook_url)
        print(f"Webhook configurado en: {webhook_url}")
    else:
        updater.start_polling()
        print("Bot iniciado en modo polling...")

    dp.add_error_handler(lambda update, context: print(f"Error: {context.error}"))
    updater.idle()

if __name__ == '__main__':
    main()
