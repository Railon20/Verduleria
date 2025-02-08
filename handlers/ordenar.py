# handlers/ordenar.py

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackContext,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    Filters,
    ConversationHandler,
)
from database.models import Product, Cart, CartItem, User
from utils.db_utils import get_session

# Estados del ConversationHandler para el flujo de "Ordenar"
PRODUCT_SELECTION, ASK_QUANTITY, CART_SELECTION, NEW_CART, CONFIRM_ADDITION, ASK_MORE, PAYMENT = range(7)

def show_products_menu(update: Update, context: CallbackContext):
    """
    Muestra la lista de productos disponibles con botones para cada uno y un botón para volver atrás.
    """
    session = get_session()
    products = session.query(Product).all()
    keyboard = []
    for product in products:
        button = InlineKeyboardButton(product.name, callback_data=f"product_{product.id}")
        keyboard.append([button])
    # Botón para volver atrás (regresa al menú principal)
    keyboard.append([InlineKeyboardButton("Volver atrás", callback_data="ordenar_back")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        update.message.reply_text("Selecciona un producto:", reply_markup=reply_markup)
    elif update.callback_query:
        update.callback_query.edit_message_text("Selecciona un producto:", reply_markup=reply_markup)
    return PRODUCT_SELECTION

def product_selected(update: Update, context: CallbackContext):
    """
    Captura la selección de un producto, muestra su precio y solicita la cantidad deseada.
    """
    query = update.callback_query
    query.answer()
    data = query.data
    if data == "ordenar_back":
        # Volver al menú principal
        from handlers.menu import show_main_menu
        query.edit_message_text("Volviendo al menú principal...")
        show_main_menu(update, context)
        return ConversationHandler.END

    # Se espera que el callback_data tenga el formato "product_{id}"
    try:
        product_id = int(data.split("_")[1])
    except (IndexError, ValueError):
        query.edit_message_text("Producto no reconocido. Intenta de nuevo.")
        return PRODUCT_SELECTION

    session = get_session()
    product = session.query(Product).filter(Product.id == product_id).first()
    if not product:
        query.edit_message_text("Producto no encontrado.")
        return PRODUCT_SELECTION

    # Guardar información del producto seleccionado en context
    context.user_data["selected_product"] = {
        "id": product.id,
        "name": product.name,
        "sale_unit": product.sale_unit,
        "price": product.price
    }

    # Mostrar información del precio según la unidad de venta
    if product.sale_unit == "gramos":
        price_info = f"Precio por 100 gramos: ${product.price:.2f}"
    else:
        price_info = f"Precio por unidad: ${product.price:.2f}"

    message = (
        f"Has seleccionado: {product.name}\n"
        f"{price_info}\n\n"
        f"Por favor, indica cuántos { 'gramos' if product.sale_unit=='gramos' else 'unidades' } deseas:"
    )
    # Agregar botón para volver a la lista de productos
    keyboard = [[InlineKeyboardButton("Volver atrás", callback_data="back_to_products")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(message, reply_markup=reply_markup)
    return ASK_QUANTITY

def back_to_products(update: Update, context: CallbackContext):
    """
    Permite volver a la lista de productos.
    """
    query = update.callback_query
    query.answer()
    return show_products_menu(update, context)

def receive_quantity(update: Update, context: CallbackContext):
    """
    Recibe la cantidad ingresada por el usuario y muestra los carritos disponibles.
    """
    text = update.message.text
    try:
        quantity = float(text)
        if quantity <= 0:
            raise ValueError
    except ValueError:
        update.message.reply_text("Por favor, ingresa un número válido mayor que cero.")
        return ASK_QUANTITY

    context.user_data["quantity"] = quantity
    return show_cart_options(update, context)

def show_cart_options(update: Update, context: CallbackContext):
    """
    Muestra los carritos del usuario y la opción de crear uno nuevo.
    """
    user_id = update.effective_user.id
    session = get_session()
    user = session.query(User).filter(User.telegram_id == str(user_id)).first()
    keyboard = []
    if user and user.carts:
        for cart in user.carts:
            if cart.is_active:
                button = InlineKeyboardButton(cart.name, callback_data=f"cart_{cart.id}")
                keyboard.append([button])
    # Opción para crear un nuevo carrito
    keyboard.append([InlineKeyboardButton("Crear nuevo carrito", callback_data="new_cart")])
    # Opción para volver atrás
    keyboard.append([InlineKeyboardButton("Volver atrás", callback_data="ordenar_back")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        update.message.reply_text("Selecciona un carrito para agregar el producto:", reply_markup=reply_markup)
    elif update.callback_query:
        update.callback_query.edit_message_text("Selecciona un carrito para agregar el producto:", reply_markup=reply_markup)
    return CART_SELECTION

def new_cart_prompt(update: Update, context: CallbackContext):
    """
    Solicita al usuario el nombre para crear un nuevo carrito.
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
    # Una vez creado el carrito, se muestran nuevamente las opciones de carrito
    return show_cart_options(update, context)

def cart_selection_handler(update: Update, context: CallbackContext):
    """
    Maneja la selección de un carrito existente.
    """
    query = update.callback_query
    query.answer()
    data = query.data
    if data.startswith("cart_"):
        try:
            cart_id = int(data.split("_")[1])
        except (IndexError, ValueError):
            query.edit_message_text("Carrito no reconocido.")
            return CART_SELECTION

        context.user_data["selected_cart_id"] = cart_id

        # Calcular el costo del producto seleccionado
        session = get_session()
        product_data = context.user_data.get("selected_product")
        quantity = context.user_data.get("quantity")
        if not product_data or quantity is None:
            query.edit_message_text("Error: datos del producto o cantidad no encontrados.")
            return ConversationHandler.END

        if product_data["sale_unit"] == "gramos":
            cost = (quantity / 100) * product_data["price"]
        else:
            cost = quantity * product_data["price"]

        # Calcular el total actual del carrito
        cart = session.query(Cart).filter(Cart.id == cart_id).first()
        cart_total = 0
        for item in cart.items:
            prod = item.product
            if prod.sale_unit == "gramos":
                cart_total += (item.quantity / 100) * prod.price
            else:
                cart_total += item.quantity * prod.price

        new_total = cart_total + cost

        message = (
            f"El total del carrito actual es: ${cart_total:.2f}\n"
            f"Con la adhesión de '{product_data['name']}' ({quantity} {'gramos' if product_data['sale_unit']=='gramos' else 'unidades'}), el total sería: ${new_total:.2f}\n\n"
            "¿Deseas agregar este producto a este carrito?"
        )

        keyboard = [
            [InlineKeyboardButton("Sí", callback_data=f"confirm_yes_{cart_id}")],
            [InlineKeyboardButton("No", callback_data="confirm_no")],
            [InlineKeyboardButton("Volver atrás", callback_data="ordenar_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(message, reply_markup=reply_markup)
        return CONFIRM_ADDITION

    elif data == "new_cart":
        return new_cart_prompt(update, context)
    elif data == "ordenar_back":
        from handlers.menu import show_main_menu
        query.edit_message_text("Volviendo al menú principal...")
        show_main_menu(update, context)
        return ConversationHandler.END

def confirm_addition_handler(update: Update, context: CallbackContext):
    """
    Procesa la confirmación de agregar el producto al carrito seleccionado.
    """
    query = update.callback_query
    query.answer()
    data = query.data
    if data.startswith("confirm_yes_"):
        try:
            cart_id = int(data.split("_")[-1])
        except (IndexError, ValueError):
            query.edit_message_text("Error en la selección del carrito.")
            return CART_SELECTION

        session = get_session()
        product_data = context.user_data.get("selected_product")
        quantity = context.user_data.get("quantity")
        if not product_data or quantity is None:
            query.edit_message_text("Datos incompletos. Operación cancelada.")
            return ConversationHandler.END

        new_item = CartItem(cart_id=cart_id, product_id=product_data["id"], quantity=quantity)
        session.add(new_item)
        session.commit()

        query.edit_message_text("Producto agregado exitosamente al carrito.")
        # Preguntar si se desea agregar más productos
        keyboard = [
            [InlineKeyboardButton("Sí, agregar más productos", callback_data="add_more_yes")],
            [InlineKeyboardButton("No, proceder al pago", callback_data="add_more_no")],
            [InlineKeyboardButton("Volver al menú principal", callback_data="ordenar_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.message.reply_text("¿Deseas agregar más productos a este carrito?", reply_markup=reply_markup)
        return ASK_MORE

    elif data == "confirm_no":
        # Si el usuario decide no agregar el producto, se vuelve a mostrar la selección de carritos
        return show_cart_options(update, context)

def add_more_handler(update: Update, context: CallbackContext):
    """
    Maneja la decisión del usuario sobre agregar más productos o proceder al pago.
    """
    query = update.callback_query
    query.answer()
    data = query.data
    if data == "add_more_yes":
        return show_products_menu(update, context)
    elif data == "add_more_no":
        # Mostrar el detalle del carrito y preguntar si se desea proceder al pago
        cart_id = context.user_data.get("selected_cart_id")
        if not cart_id:
            query.edit_message_text("Carrito no encontrado.")
            return ConversationHandler.END
        session = get_session()
        cart = session.query(Cart).filter(Cart.id == cart_id).first()
        if not cart:
            query.edit_message_text("Carrito no encontrado.")
            return ConversationHandler.END

        total = 0
        details = "Detalle del carrito:\n"
        for item in cart.items:
            prod = item.product
            if prod.sale_unit == "gramos":
                item_cost = (item.quantity / 100) * prod.price
            else:
                item_cost = item.quantity * prod.price
            total += item_cost
            details += f"- {prod.name}: {item.quantity} {'gramos' if prod.sale_unit=='gramos' else 'unidades'} = ${item_cost:.2f}\n"

        details += f"\nTotal: ${total:.2f}\n"
        details += "¿Deseas proceder al pago?"
        keyboard = [
            [InlineKeyboardButton("Proceder al pago", callback_data="proceed_payment")],
            [InlineKeyboardButton("Volver al menú principal", callback_data="ordenar_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(details, reply_markup=reply_markup)
        return PAYMENT

def payment_handler(update: Update, context: CallbackContext):
    """
    Inicia el proceso de pago utilizando el Checkout Pro de Mercado Pago.
    """
    query = update.callback_query
    query.answer()
    data = query.data
    if data == "proceed_payment":
        cart_id = context.user_data.get("selected_cart_id")
        if not cart_id:
            query.edit_message_text("Carrito no encontrado.")
            return ConversationHandler.END
        session = get_session()
        cart = session.query(Cart).filter(Cart.id == cart_id).first()
        if not cart:
            query.edit_message_text("Carrito no encontrado.")
            return ConversationHandler.END

        total = 0
        for item in cart.items:
            prod = item.product
            if prod.sale_unit == "gramos":
                total += (item.quantity / 100) * prod.price
            else:
                total += item.quantity * prod.price

        # Aquí se debe integrar la llamada al Checkout Pro de Mercado Pago.
        # Por simplicidad, simulamos este proceso:
        payment_url = "https://www.mercadopago.com/checkout_simulado"
        query.edit_message_text(
            f"Para proceder con el pago, por favor visita el siguiente enlace:\n{payment_url}\n\n"
            "Una vez completado el pago, se generará el código de pedido."
        )
        # Aquí se podría generar el 'order_code' y registrar el pedido en la base de datos.
        return ConversationHandler.END

    elif data == "ordenar_back":
        from handlers.menu import show_main_menu
        query.edit_message_text("Volviendo al menú principal...")
        show_main_menu(update, context)
        return ConversationHandler.END

# Definición del ConversationHandler para el flujo de "Ordenar"
ordenar_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(show_products_menu, pattern="^menu_ordenar$")],
    states={
        PRODUCT_SELECTION: [
            CallbackQueryHandler(product_selected, pattern="^product_"),
            CallbackQueryHandler(back_to_products, pattern="^back_to_products$"),
            CallbackQueryHandler(product_selected, pattern="^ordenar_back$")
        ],
        ASK_QUANTITY: [
            MessageHandler(Filters.text & ~Filters.command, receive_quantity),
            CallbackQueryHandler(back_to_products, pattern="^back_to_products$")
        ],
        CART_SELECTION: [
            CallbackQueryHandler(cart_selection_handler, pattern="^(cart_|new_cart|ordenar_back)")
        ],
        NEW_CART: [
            MessageHandler(Filters.text & ~Filters.command, create_new_cart)
        ],
        CONFIRM_ADDITION: [
            CallbackQueryHandler(confirm_addition_handler, pattern="^(confirm_yes_|confirm_no|ordenar_back)")
        ],
        ASK_MORE: [
            CallbackQueryHandler(add_more_handler, pattern="^(add_more_yes|add_more_no|ordenar_back)")
        ],
        PAYMENT: [
            CallbackQueryHandler(payment_handler, pattern="^(proceed_payment|ordenar_back)")
        ]
    },
    fallbacks=[CommandHandler("cancel", lambda update, context: update.message.reply_text("Operación cancelada."))],
    allow_reentry=True
)
