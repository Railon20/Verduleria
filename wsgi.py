# wsgi.py
from bot import app  # Solo importa app

# No inicies el bot con run_bot(), ya que el webhook lo manejará a través de Flask.
