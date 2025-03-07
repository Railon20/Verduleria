from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import os
import asyncio

async def test_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_user.id, text="Test OK")

async def main():
    token = os.getenv("7564104399:AAHGNFyMSaVSbEQl3MDGFD4g-jaziwTRw_E")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("test", test_handler))
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
