from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, CallbackQueryHandler  # IMPORTACIÓN AGREGADA
from utils.db_utils import get_session
from database.models import User

def show_main_menu(update: Update, context: CallbackContext):
    """
    Muestra el menú principal con las opciones:
      - Ordenar, Historial, Pedidos Pendientes, Carritos
      - Un botón adicional "Cerrar Sesión"
    """
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
    """
    Maneja el callback de 'Cerrar Sesión'. Elimina los datos del usuario (por ejemplo,
    borrando su registro de la base de datos) y notifica que se cerró la sesión.
    """
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    session = get_session()
    user = session.query(User).filter(User.telegram_id == str(user_id)).first()
    if user:
        # Aquí se simula el logout eliminando al usuario; en producción quizás quieras
        # simplemente borrar datos de la sesión en memoria o marcarlo como desconectado.
        session.delete(user)
        session.commit()
    query.edit_message_text("Sesión cerrada. Usa /start para iniciar nuevamente.")

# Handler global para el menú principal (se activa con cualquier callback que empiece con "menu_")
menu_handler = CallbackQueryHandler(lambda update, context: show_main_menu(update, context), pattern="^menu_")
