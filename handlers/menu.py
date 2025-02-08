from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, CallbackQueryHandler  # Asegurarse de importar CallbackQueryHandler
from utils.db_utils import get_session
from database.models import User

def show_main_menu(update: Update, context: CallbackContext):
    """
    Muestra el menú principal con las opciones:
      - Ordenar, Historial, Pedidos Pendientes, Carritos
      - Botón "Cerrar Sesión"
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
    Maneja el callback de "Cerrar Sesión".  
    Elimina el registro del usuario (simulando el cierre de sesión) y muestra un mensaje
    "Sesión Cerrada" con dos botones: "Iniciar Sesión" y "Registrarse".
    """
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    session = get_session()
    user = session.query(User).filter(User.telegram_id == str(user_id)).first()
    
    if user:
        # Para simular el logout, se elimina el registro del usuario.
        # En un entorno real podrías simplemente limpiar la sesión sin eliminar el registro.
        session.delete(user)
        session.commit()
    
    keyboard = [
        [InlineKeyboardButton("Iniciar Sesión", callback_data="login")],
        [InlineKeyboardButton("Registrarse", callback_data="register")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text("Sesión Cerrada.", reply_markup=reply_markup)

# Handler global para capturar callbacks que inician con "menu_"
menu_handler = CallbackQueryHandler(lambda update, context: show_main_menu(update, context), pattern="^menu_")

# (Asegúrate de que en main.py se registre también el logout_handler, por ejemplo:
# dp.add_handler(CallbackQueryHandler(logout_handler, pattern="^logout$"))
# )
