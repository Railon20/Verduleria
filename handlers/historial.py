# handlers/historial.py

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, CallbackQueryHandler
from database.models import Order, User
from utils.db_utils import get_session

def show_history(update: Update, context: CallbackContext):
    """
    Muestra los últimos 20 pedidos completados del usuario.
    """
    user_id = update.effective_user.id
    session = get_session()
    user = session.query(User).filter(User.telegram_id == str(user_id)).first()
    
    if not user:
        message = "Usuario no encontrado. Por favor, regístrate o inicia sesión."
    else:
        orders = (
            session.query(Order)
            .filter(Order.user_id == user.id, Order.status == "completed")
            .order_by(Order.created_at.desc())
            .limit(20)
            .all()
        )
        if orders:
            message = "Historial de pedidos completados:\n\n"
            for order in orders:
                message += (
                    f"Código: {order.order_code}\n"
                    f"Total: ${order.total_price:.2f}\n"
                    f"Fecha: {order.created_at.strftime('%Y-%m-%d %H:%M')}\n\n"
                )
        else:
            message = "No tienes pedidos completados en tu historial."

    # Botón para volver atrás al menú principal
    keyboard = [[InlineKeyboardButton("Volver atrás", callback_data="historial_back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        update.message.reply_text(message, reply_markup=reply_markup)
    elif update.callback_query:
        update.callback_query.edit_message_text(message, reply_markup=reply_markup)
    return

def historial_back(update: Update, context: CallbackContext):
    """
    Vuelve al menú principal desde el historial.
    """
    query = update.callback_query
    query.answer()
    from handlers.menu import show_main_menu
    query.edit_message_text("Volviendo al menú principal...")
    show_main_menu(update, context)
    return

# Handler para la acción del botón "Volver atrás" en el historial
historial_handler = CallbackQueryHandler(historial_back, pattern="^historial_back$")
