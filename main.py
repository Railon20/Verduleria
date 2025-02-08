import os
import logging
import urllib.parse
from telegram.ext import Updater, CommandHandler
from config import TELEGRAM_BOT_TOKEN, DEBUG
# Importa tus handlers
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
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # Registrar los handlers
    dp.add_handler(auth_handler)          # Autenticación y registro de usuarios
    dp.add_handler(menu_handler)          # Menú principal
    dp.add_handler(ordenar_handler)       # Flujo de ordenación de productos
    dp.add_handler(carritos_handler)      # Gestión de carritos
    dp.add_handler(historial_handler)     # Historial de pedidos
    dp.add_handler(pending_orders_handler)  # Listado de pedidos pendientes
    dp.add_handler(pedidos_back_handler)    # Volver atrás en pedidos
    dp.add_handler(complete_order_conv_handler)  # Confirmación de completado de pedidos

    # Comando /help para mostrar información de comandos
    dp.add_handler(CommandHandler("help", lambda update, context: update.message.reply_text(
        "Comandos disponibles:\n"
        "/start - Iniciar el bot\n"
        "/cancel - Cancelar operación\n"
        "/help - Mostrar este mensaje"
    )))

    # Registrar el manejador de errores
    dp.add_error_handler(error_handler)

    # Determinar el modo de operación:
    # Usa webhook si se fuerza mediante la variable de entorno USE_WEBHOOK.
    # En Render, lo ideal es usar polling para evitar problemas de puertos.
    use_webhook = os.environ.get("USE_WEBHOOK", "false").lower() == "true"

    if use_webhook:
        # Modo webhook (útil si usas un proveedor que permita puertos 80, 88, 443 o 8443)
        RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")  # Ej: "https://tu-app.onrender.com"
        PORT = int(os.environ.get("PORT", "8443"))
        updater.start_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TELEGRAM_BOT_TOKEN
        )
        # Construir la URL pública sin especificar un puerto (se asume HTTPS, puerto 443)
        parsed_url = urllib.parse.urlparse(RENDER_EXTERNAL_URL)
        webhook_url = f"https://{parsed_url.hostname}/{TELEGRAM_BOT_TOKEN}"
        updater.bot.set_webhook(webhook_url)
        logger.info(f"Webhook configurado en: {webhook_url}")
    else:
        # Modo polling (recomendado en Render para evitar problemas de puertos)
        updater.start_polling()
        logger.info("Bot iniciado en modo polling...")

    updater.idle()

if __name__ == "__main__":
    main()
