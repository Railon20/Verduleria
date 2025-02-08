import os
import threading
import time
import logging
from flask import Flask
from telegram.ext import Updater, CommandHandler
from config import TELEGRAM_BOT_TOKEN, DEBUG

# Importa tus handlers
from handlers.auth import auth_handler
from handlers.menu import menu_handler
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

# Creamos una aplicación Flask mínima para mantener abierto el puerto requerido por Render
app = Flask(__name__)

@app.route("/")
def index():
    return "Bot is running!"

def start_bot():
    # Inicializa el bot con polling
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    # Elimina cualquier webhook que esté configurado para evitar conflictos
    updater.bot.delete_webhook()
    dp = updater.dispatcher

    # Registrar los handlers
    dp.add_handler(auth_handler)               # Registro y login (con flujo modificado)
    dp.add_handler(menu_handler)               # Menú principal
    dp.add_handler(ordenar_handler)            # Flujo de ordenar productos
    dp.add_handler(carritos_handler)           # Gestión de carritos
    dp.add_handler(historial_handler)          # Historial de pedidos
    dp.add_handler(pending_orders_handler)     # Pedidos pendientes
    dp.add_handler(pedidos_back_handler)       # Volver atrás en pedidos
    dp.add_handler(complete_order_conv_handler)  # Confirmación de pedidos completados
    dp.add_handler(CommandHandler("help", lambda update, context: update.message.reply_text(
        "Comandos disponibles:\n/start - Iniciar el bot\n/cancel - Cancelar operación\n/help - Mostrar este mensaje"
    )))

    # Inicia el polling
    updater.start_polling()
    logger.info("Bot iniciado en modo polling...")

    # Mantener el hilo activo sin usar updater.idle() (que usa señales y sólo es válido en el hilo principal)
    while True:
        time.sleep(10)

if __name__ == "__main__":
    # Inicia el bot en un hilo separado (daemon para que finalice cuando termine el proceso principal)
    bot_thread = threading.Thread(target=start_bot)
    bot_thread.daemon = True
    bot_thread.start()

    # Obtén el puerto asignado por Render (o usa 5000 para desarrollo local)
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Iniciando servidor web en el puerto {port}...")
    app.run(host="0.0.0.0", port=port)
