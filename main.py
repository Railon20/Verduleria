import os
import threading
import time
import logging
from flask import Flask
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler
from config import TELEGRAM_BOT_TOKEN, DEBUG
from handlers.auth import auth_handler, restart_auth, menu_button_handler
from handlers.menu import menu_handler, show_main_menu, logout_handler
from handlers.ordenar import ordenar_handler
from handlers.carritos import carritos_handler
from handlers.historial import historial_handler
from handlers.pedidos import pending_orders_handler, pedidos_back_handler, complete_order_conv_handler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.DEBUG if DEBUG else logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route("/")
def index():
    return "Bot is running!"

def global_error_handler(update, context):
    try:
        raise context.error
    except Exception as e:
        logger.error("Update %s caused error %s", update, context.error)

def start_bot():
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    updater.bot.delete_webhook()
    dp = updater.dispatcher

    dp.add_handler(auth_handler)
    dp.add_handler(menu_handler)
    dp.add_handler(ordenar_handler)
    dp.add_handler(carritos_handler)
    dp.add_handler(historial_handler)
    dp.add_handler(pending_orders_handler)
    dp.add_handler(pedidos_back_handler)
    dp.add_handler(complete_order_conv_handler)
    
    # Global handlers para reiniciar el flujo (para "login" y "register")
    dp.add_handler(CallbackQueryHandler(restart_auth, pattern="^(login|register)$"))
    # Handler para "Cerrar Sesión"
    dp.add_handler(CallbackQueryHandler(logout_handler, pattern="^logout$"))
    
    dp.add_handler(CommandHandler("help", lambda update, context: update.message.reply_text(
        "Comandos disponibles:\n/start - Iniciar el bot\n/cancel - Cancelar operación\n/help - Mostrar este mensaje"
    )))
    
    dp.add_error_handler(global_error_handler)
    
    updater.start_polling()
    logger.info("Bot iniciado en modo polling...")
    while True:
        time.sleep(10)

if __name__ == "__main__":
    bot_thread = threading.Thread(target=start_bot)
    bot_thread.daemon = True
    bot_thread.start()
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Iniciando servidor web en el puerto {port}...")
    app.run(host="0.0.0.0", port=port)
