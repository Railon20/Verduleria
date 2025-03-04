import os


class Config:
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    DB_NAME = os.getenv("DB_NAME")
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_HOST = os.getenv("DB_HOST")
    DB_PORT = os.getenv("DB_PORT")
    MP_SDK = os.getenv("MP_SDK")

# Luego en tu bot.py

# Y usa Config.TELEGRAM_TOKEN, etc.
