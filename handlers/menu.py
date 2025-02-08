# handlers/menu.py

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from utils.db_utils import get_session
from database.models import User

def show_main_menu(update: Update, context: CallbackContext):
    """
    Muestra el menú principal con opciones y un botón para cerrar sesión.
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
    Maneja el callback de 'Cerrar Sesión'. Elimina los datos del usuario o limpia la sesión,
    y notifica que se cerró la sesión.
    """
    query = update.callback_query
    query.answer()
    user_id = update.effective_user.id
    session = get_session()
    user = session.query(User).filter(User.telegram_id == str(user_id)).first()
    if user:
        # Por ejemplo, se puede eliminar el registro (si eso define el "logout")
        session.delete(user)
        session.commit()
    query.edit_message_text("Sesión cerrada. Usa /start para iniciar nuevamente.")

def menu_callback(update: Update, context: CallbackContext):
    """
    Maneja la respuesta del usuario en el menú principal.
    Según la opción seleccionada, redirige al flujo correspondiente.
    """
    query = update.callback_query
    query.answer()
    data = query.data

    if data == "menu_ordenar":
        query.edit_message_text("Has seleccionado 'Ordenar'. Redirigiendo al catálogo de productos...")
        # Se importa la función del módulo de ordenar y se invoca.
        from handlers.ordenar import show_products_menu
        return show_products_menu(update, context)
    elif data == "menu_historial":
        query.edit_message_text("Has seleccionado 'Historial'. Redirigiendo a tu historial de pedidos...")
        # Se importa la función del módulo de historial y se invoca.
        from handlers.historial import show_history
        return show_history(update, context)
    elif data == "menu_pedidos_pendientes":
        query.edit_message_text("Has seleccionado 'Pedidos Pendientes'. Redirigiendo a tus pedidos pendientes...")
        # Se importa la función del módulo de pedidos y se invoca.
        from handlers.pedidos import show_pending_orders
        return show_pending_orders(update, context)
    elif data == "menu_carritos":
        query.edit_message_text("Has seleccionado 'Carritos'. Redirigiendo a la gestión de carritos...")
        # Se importa la función del módulo de carritos y se invoca.
        from handlers.carritos import show_carts
        return show_carts(update, context)
    else:
        query.edit_message_text("Opción no reconocida. Por favor, intenta de nuevo.")

# Handler para las respuestas del menú principal
menu_handler = CallbackQueryHandler(menu_callback, pattern="^menu_")
