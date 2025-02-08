# main.py (fragmento relevante)

import os
import threading
import time
import logging
from flask import Flask
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler
from config import TELEGRAM_BOT_TOKEN, DEBUG
from handlers.auth import auth_handler, menu_button_handler
from handlers.menu import menu_handler, show_main_menu, logout_handler
from handlers.ordenar import ordenar_handler
from handlers.carritos import carritos_handler
from handlers.historial import historial_handler
from handlers.pedidos import pending_orders_handler, pedidos_back_handler, complete_order_conv_handler

# (Código de Flask y bot initialization como se mostró en la versión anterior)

def start_bot():
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    updater.bot.delete_webhook()
    dp = updater.dispatcher

    # Registrar conversation handler de autenticación
    dp.add_handler(auth_handler)
    # Registrar otros handlers
    dp.add_handler(menu_handler)
    dp.add_handler(ordenar_handler)
    dp.add_handler(carritos_handler)
    dp.add_handler(historial_handler)
    dp.add_handler(pending_orders_handler)
    dp.add_handler(pedidos_back_handler)
    dp.add_handler(complete_order_conv_handler)
    
    # Registrar un handler global para el callback "main_menu"
    dp.add_handler(CallbackQueryHandler(menu_button_handler, pattern="^main_menu$"))
    # Registrar un handler global para el callback "logout"
    dp.add_handler(CallbackQueryHandler(logout_handler, pattern="^logout$"))
    
    dp.add_handler(CommandHandler("help", lambda update, context: update.message.reply_text(
        "Comandos disponibles:\n/start - Iniciar el bot\n/cancel - Cancelar operación\n/help - Mostrar este mensaje"
    )))

    updater.start_polling()
    logging.getLogger(__name__).info("Bot iniciado en modo polling...")
    while True:
        time.sleep(10)

if __name__ == "__main__":
    # Iniciar el bot en un hilo separado
    bot_thread = threading.Thread(target=start_bot)
    bot_thread.daemon = True
    bot_thread.start()

    # Inicia el servidor web (Flask) en el puerto asignado por Render
    port = int(os.environ.get("PORT", 5000))
    app = Flask(__name__)

    @app.route("/")
    def index():
        return "Bot is running!"

    logging.getLogger(__name__).info(f"Iniciando servidor web en el puerto {port}...")
    app.run(host="0.0.0.0", port=port)