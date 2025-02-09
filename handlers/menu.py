from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, CallbackQueryHandler
from utils.db_utils import get_session
from database.models import User
import logging

logger = logging.getLogger(__name__)

def show_main_menu(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("Ordenar", callback_data="menu_ordenar")],
        [InlineKeyboardButton("Historial", callback_data="menu_historial")],
        [InlineKeyboardButton("Pedidos Pendientes", callback_data="menu_pedidos_pendientes")],
        [InlineKeyboardButton("Carritos", callback_data="menu_carritos")],
        [InlineKeyboardButton("Cerrar Sesión", callback_data="logout")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        update.message.reply_text("Seleccione una opción:", reply_markup=reply_markup)
    elif update.callback_query:
        update.callback_query.edit_message_text("Seleccione una opción:", reply_markup=reply_markup)

def logout_handler(update: Update, context: CallbackContext):
    logger.info("logout_handler() llamado")
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    session = get_session()
    user = session.query(User).filter(User.telegram_id == str(user_id)).first()
    if user:
        session.delete(user)
        session.commit()
    keyboard = [
        [InlineKeyboardButton("Iniciar Sesión", callback_data="login")],
        [InlineKeyboardButton("Registrarse", callback_data="register")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text("Sesión Cerrada.", reply_markup=reply_markup)

menu_handler = CallbackQueryHandler(lambda update, context: show_main_menu(update, context), pattern="^menu_")
