# wsgi.py
from bot import app  # Asegúrate de exportar app y run_bot desde bot.py
import threading

# Inicia el bot en un hilo aparte
#threading.Thread(target=run_bot, daemon=True).start()

# La variable 'app' es la aplicación Flask que usa Render.
