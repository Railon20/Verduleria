import os
import logging
import urllib.parse
from telegram.ext import Updater, CommandHandler
from config import TELEGRAM_BOT_TOKEN, DEBUG
from handlers.auth import auth_handler
from handlers.menu import menu_handler, show_main_menu
from handlers.ordenar import ordenar_handler
from handlers.carritos import carritos_handler
from handlers.historial import historial_handler
from handlers.pedidos import pending_orders_handler, pedidos_back_handler, complete_order_conv_handler

# Configuración de logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.DEBUG if DEBUG else logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

def error_handler(update, context):
    """Maneja errores y los registra en el log."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

def main():
    """Función principal que inicia el bot y configura los handlers."""

    # Crear el objeto Updater y obtener Dispatcher
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # Registrar los handlers
    dp.add_handler(auth_handler)  # Maneja autenticación y registro de usuarios
    dp.add_handler(menu_handler)  # Maneja el menú principal
    dp.add_handler(ordenar_handler)  # Maneja el flujo de compras
    dp.add_handler(carritos_handler)  # Maneja la gestión de carritos
    dp.add_handler(historial_handler)  # Maneja el historial de pedidos
    dp.add_handler(pending_orders_handler)  # Maneja la lista de pedidos pendientes
    dp.add_handler(pedidos_back_handler)  # Maneja la opción de volver atrás en pedidos
    dp.add_handler(complete_order_conv_handler)  # Maneja la confirmación de entrega de pedidos
    
    # Comando /help para mostrar opciones
    dp.add_handler(CommandHandler("help", lambda update, context: update.message.reply_text(
        "Comandos disponibles:\n"
        "/start - Iniciar el bot\n"
        "/cancel - Cancelar operación\n"
        "/help - Mostrar este mensaje"
    )))

    # Registrar el manejador de errores
    dp.add_error_handler(error_handler)

    # Detectar si estamos en producción (Render) o en modo local
    RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")
    if RENDER_EXTERNAL_URL:
        PORT = int(os.environ.get("PORT", "8443"))  # Puerto interno en Render
        updater.start_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TELEGRAM_BOT_TOKEN
        )
        # Construir la URL pública sin puerto, para que Telegram la acepte correctamente
        parsed_url = urllib.parse.urlparse(RENDER_EXTERNAL_URL)
        webhook_url = f"https://{parsed_url.hostname}/{TELEGRAM_BOT_TOKEN}"
        updater.bot.set_webhook(webhook_url)
        logger.info(f"Webhook configurado en: {webhook_url}")
    else:
        # En modo local, se usa polling
        updater.start_polling()
        logger.info("Bot iniciado en modo polling...")

    updater.idle()

if __name__ == "__main__":
    main()
