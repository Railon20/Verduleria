# handlers/carritos.py

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackContext,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    Filters
)
from database.models import Cart, CartItem, Product, User
from utils.db_utils import get_session

# Definición de estados para el ConversationHandler
SHOW_CARTS, NEW_CART, CART_DETAIL, REMOVE_ITEM = range(4)

def show_carts(update: Update, context: CallbackContext):
    """
    Muestra la lista de carritos del usuario con la opción de crear un nuevo carrito.
    """
    user_id = update.effective_user.id
    session = get_session()
    user = session.query(User).filter(User.telegram_id == str(user_id)).first()

    keyboard = []
    if user and user.carts:
        for cart in user.carts:
            if cart.is_active:
                button = InlineKeyboardButton(cart.name, callback_data=f"select_cart_{cart.id}")
                keyboard.append([button])
    # Botón para crear un nuevo carrito
    keyboard.append([InlineKeyboardButton("Crear nuevo carrito", callback_data="carrito_new")])
    # Botón para volver al menú principal
    keyboard.append([InlineKeyboardButton("Volver atrás", callback_data="carrito_back")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        update.message.reply_text("Estos son tus carritos:", reply_markup=reply_markup)
    elif update.callback_query:
        update.callback_query.edit_message_text("Estos son tus carritos:", reply_markup=reply_markup)
    return SHOW_CARTS

def new_cart_prompt(update: Update, context: CallbackContext):
    """
    Solicita al usuario que ingrese el nombre para un nuevo carrito.
    """
    query = update.callback_query
    query.answer()
    query.edit_message_text("Por favor, envía el nombre para el nuevo carrito:")
    return NEW_CART

def create_new_cart(update: Update, context: CallbackContext):
    """
    Crea un nuevo carrito con el nombre proporcionado por el usuario.
    """
    cart_name = update.message.text
    user_id = update.effective_user.id
    session = get_session()
    user = session.query(User).filter(User.telegram_id == str(user_id)).first()
    if not user:
        update.message.reply_text("Usuario no encontrado.")
        return ConversationHandler.END
    new_cart = Cart(name=cart_name, user_id=user.id)
    session.add(new_cart)
    session.commit()
    update.message.reply_text(f"Carrito '{cart_name}' creado exitosamente.")
    return show_carts(update, context)

def cart_detail(update: Update, context: CallbackContext):
    """
    Muestra el detalle del carrito seleccionado y ofrece opciones:
    Agregar productos, Eliminar productos, Eliminar carrito y Volver atrás.
    """
    query = update.callback_query
    query.answer()
    data = query.data

    if data.startswith("select_cart_"):
        try:
            cart_id = int(data.split("_")[-1])
        except (IndexError, ValueError):
            query.edit_message_text("Carrito no reconocido.")
            return SHOW_CARTS

        context.user_data["selected_cart_id"] = cart_id
        session = get_session()
        cart = session.query(Cart).filter(Cart.id == cart_id).first()
        if not cart:
            query.edit_message_text("Carrito no encontrado.")
            return SHOW_CARTS

        # Preparar el detalle del carrito
        details = f"Detalles del carrito '{cart.name}':\n"
        if cart.items:
            for item in cart.items:
                prod = item.product
                details += f"- {prod.name}: {item.quantity} {'gramos' if prod.sale_unit=='gramos' else 'unidades'}\n"
        else:
            details += "El carrito está vacío.\n"
        
        # Opciones disponibles para el carrito
        keyboard = [
            [InlineKeyboardButton("Agregar productos", callback_data="action_add")],
            [InlineKeyboardButton("Eliminar productos", callback_data="action_remove")],
            [InlineKeyboardButton("Eliminar carrito", callback_data="action_delete")],
            [InlineKeyboardButton("Volver atrás", callback_data="action_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(details, reply_markup=reply_markup)
        return CART_DETAIL

def cart_action_handler(update: Update, context: CallbackContext):
    """
    Procesa la acción seleccionada en el detalle del carrito.
    """
    query = update.callback_query
    query.answer()
    data = query.data

    if data == "action_add":
        # Redirige al flujo de "Ordenar" para agregar productos al carrito
        from handlers.ordenar import show_products_menu
        query.edit_message_text("Redirigiendo a la selección de productos...")
        return show_products_menu(update, context)
    elif data == "action_remove":
        return show_remove_items(update, context)
    elif data == "action_delete":
        return delete_cart(update, context)
    elif data == "action_back":
        return show_carts(update, context)
    else:
        query.edit_message_text("Acción no reconocida.")
        return CART_DETAIL

def show_remove_items(update: Update, context: CallbackContext):
    """
    Muestra los ítems del carrito para que el usuario seleccione cuál eliminar.
    """
    query = update.callback_query
    user_cart_id = context.user_data.get("selected_cart_id")
    if not user_cart_id:
        query.edit_message_text("No se ha seleccionado ningún carrito.")
        return SHOW_CARTS

    session = get_session()
    cart = session.query(Cart).filter(Cart.id == user_cart_id).first()
    if not cart or not cart.items:
        query.edit_message_text("El carrito está vacío, no hay productos para eliminar.")
        return CART_DETAIL

    keyboard = []
    for item in cart.items:
        button = InlineKeyboardButton(
            f"Eliminar {item.product.name} ({item.quantity} {'gramos' if item.product.sale_unit=='gramos' else 'unidades'})",
            callback_data=f"remove_item_{item.id}"
        )
        keyboard.append([button])
    keyboard.append([InlineKeyboardButton("Volver atrás", callback_data="remove_back")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text("Selecciona el producto que deseas eliminar:", reply_markup=reply_markup)
    return REMOVE_ITEM

def remove_item_handler(update: Update, context: CallbackContext):
    """
    Elimina el ítem seleccionado del carrito.
    """
    query = update.callback_query
    query.answer()
    data = query.data
    if data.startswith("remove_item_"):
        try:
            item_id = int(data.split("_")[-1])
        except (IndexError, ValueError):
            query.edit_message_text("Ítem no reconocido.")
            return REMOVE_ITEM

        session = get_session()
        item = session.query(CartItem).filter(CartItem.id == item_id).first()
        if not item:
            query.edit_message_text("Ítem no encontrado.")
            return REMOVE_ITEM

        session.delete(item)
        session.commit()
        query.edit_message_text("Producto eliminado del carrito.")
        # Se muestra nuevamente el detalle actualizado del carrito
        return cart_detail(update, context)
    elif data == "remove_back":
        # Volver al detalle del carrito
        return cart_detail(update, context)

def delete_cart(update: Update, context: CallbackContext):
    """
    Elimina el carrito seleccionado.
    """
    query = update.callback_query
    query.answer()
    cart_id = context.user_data.get("selected_cart_id")
    if not cart_id:
        query.edit_message_text("Carrito no encontrado.")
        return SHOW_CARTS

    session = get_session()
    cart = session.query(Cart).filter(Cart.id == cart_id).first()
    if not cart:
        query.edit_message_text("Carrito no encontrado.")
        return SHOW_CARTS

    session.delete(cart)
    session.commit()
    query.edit_message_text("Carrito eliminado exitosamente.")
    return show_carts(update, context)

def carrito_back_to_menu(update: Update, context: CallbackContext):
    """
    Vuelve al menú principal.
    """
    query = update.callback_query
    query.answer()
    from handlers.menu import show_main_menu
    query.edit_message_text("Volviendo al menú principal...")
    show_main_menu(update, context)
    return ConversationHandler.END

# Definición del ConversationHandler para la gestión de carritos
carritos_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(show_carts, pattern="^menu_carritos$")],
    states={
        SHOW_CARTS: [
            CallbackQueryHandler(new_cart_prompt, pattern="^carrito_new$"),
            CallbackQueryHandler(cart_detail, pattern="^select_cart_"),
            CallbackQueryHandler(carrito_back_to_menu, pattern="^carrito_back$")
        ],
        NEW_CART: [
            MessageHandler(Filters.text & ~Filters.command, create_new_cart)
        ],
        CART_DETAIL: [
            CallbackQueryHandler(cart_action_handler, pattern="^(action_add|action_remove|action_delete|action_back)$")
        ],
        REMOVE_ITEM: [
            CallbackQueryHandler(remove_item_handler, pattern="^(remove_item_.*|remove_back)$")
        ]
    },
    fallbacks=[],
    allow_reentry=True
)
