# handlers/pedidos.py

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackContext,
    CallbackQueryHandler,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    Filters,
)
from database.models import Order, User
from utils.db_utils import get_session
from handlers.menu import show_main_menu  # Para volver al menú principal

# Estado para el ConversationHandler en el proceso de completar un pedido
ORDER_CODE = 0

def show_pending_orders(update: Update, context: CallbackContext):
    """
    Muestra los pedidos pendientes del usuario.  
    Si el usuario tiene rol administrativo (is_admin=True), también se muestra la opción
    de completar pedidos ingresando su código.
    """
    user_id = update.effective_user.id
    session = get_session()
    user = session.query(User).filter(User.telegram_id == str(user_id)).first()

    if not user:
        message = "Usuario no encontrado. Por favor, regístrate o inicia sesión."
    else:
        orders = (
            session.query(Order)
            .filter(Order.user_id == user.id, Order.status == "pending")
            .order_by(Order.created_at.desc())
            .all()
        )
        if orders:
            message = "Tus pedidos pendientes:\n\n"
            for order in orders:
                message += (
                    f"Código: {order.order_code}\n"
                    f"Total: ${order.total_price:.2f}\n"
                    f"Fecha: {order.created_at.strftime('%Y-%m-%d %H:%M')}\n\n"
                )
        else:
            message = "No tienes pedidos pendientes."

    # Definir botones: para volver al menú principal y, si el usuario es admin, para completar pedidos.
    keyboard = []
    if user and user.is_admin:
        keyboard.append([InlineKeyboardButton("Completar pedido", callback_data="complete_order_prompt")])
    keyboard.append([InlineKeyboardButton("Volver atrás", callback_data="pedidos_back")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        update.message.reply_text(message, reply_markup=reply_markup)
    elif update.callback_query:
        update.callback_query.edit_message_text(message, reply_markup=reply_markup)
    return

def pedidos_back(update: Update, context: CallbackContext):
    """
    Vuelve al menú principal desde la sección de pedidos pendientes.
    """
    query = update.callback_query
    query.answer()
    query.edit_message_text("Volviendo al menú principal...")
    show_main_menu(update, context)
    return ConversationHandler.END

# --- Flujo para completar un pedido (función administrativa) ---

def complete_order_prompt(update: Update, context: CallbackContext):
    """
    Solicita al usuario autorizado que ingrese el código del pedido que desea completar.
    """
    query = update.callback_query
    query.answer()
    query.edit_message_text("Por favor, ingresa el código del pedido que deseas completar:")
    return ORDER_CODE

def complete_order_handler(update: Update, context: CallbackContext):
    """
    Recibe el código del pedido, busca el pedido pendiente y, si se encuentra, lo marca como completado.
    """
    order_code = update.message.text.strip()
    session = get_session()
    order = session.query(Order).filter(Order.order_code == order_code, Order.status == "pending").first()

    if not order:
        update.message.reply_text(
            "No se encontró un pedido pendiente con ese código. Intenta nuevamente o escribe /cancel para salir."
        )
        return ORDER_CODE

    # Actualizamos el estado del pedido a "completed"
    order.status = "completed"
    session.commit()
    update.message.reply_text(f"Pedido con código {order_code} marcado como completado.")
    return ConversationHandler.END

def cancel_order_completion(update: Update, context: CallbackContext):
    """
    Permite cancelar el proceso de completado de pedido.
    """
    update.message.reply_text("Operación cancelada.")
    return ConversationHandler.END

# --- Definición de los handlers ---

# Handler para la visualización de pedidos pendientes (se activa desde el menú principal)
pending_orders_handler = CallbackQueryHandler(show_pending_orders, pattern="^menu_pedidos_pendientes$")

# Handler para volver al menú principal desde la sección de pedidos pendientes
pedidos_back_handler = CallbackQueryHandler(pedidos_back, pattern="^pedidos_back$")

# ConversationHandler para el proceso de completar pedido (solo para usuarios autorizados)
complete_order_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(complete_order_prompt, pattern="^complete_order_prompt$")],
    states={
        ORDER_CODE: [MessageHandler(Filters.text & ~Filters.command, complete_order_handler)]
    },
    fallbacks=[CommandHandler("cancel", cancel_order_completion)],
    allow_reentry=True,
)
