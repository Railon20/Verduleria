from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackContext,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    Filters,
)
from database.models import User
from utils.db_utils import get_session

# Estados del ConversationHandler
CHOOSING, WAIT_USERNAME, WAIT_PASSWORD, WAIT_ADDRESS = range(4)

def start(update: Update, context: CallbackContext) -> int:
    """
    Maneja el comando /start.
    Si el usuario ya está registrado, muestra el menú principal.
    Si no, solicita que el usuario elija entre registrarse o iniciar sesión.
    Se adapta para funcionar tanto si el update viene de un mensaje
    como de un callback query.
    """
    # Asignamos el mensaje y el usuario correctamente:
    if update.message:
        msg = update.message
        user_obj = update.effective_user
    elif update.callback_query:
        msg = update.callback_query.message
        user_obj = update.callback_query.from_user
    else:
        return ConversationHandler.END

    # Si se ha forzado un modo (por ejemplo, desde la pantalla de logout)
    if "force_mode" in context.user_data:
        mode = context.user_data.pop("force_mode")
        context.user_data["auth_mode"] = mode
        msg.reply_text("Por favor, envía tu nombre de usuario:")
        return WAIT_USERNAME

    user_id = user_obj.id
    session = get_session()
    user = session.query(User).filter(User.telegram_id == str(user_id)).first()

    if user:
        msg.reply_text("¡Bienvenido de nuevo! Accediendo al menú principal...")
        from handlers.menu import show_main_menu
        show_main_menu(update, context)
        return ConversationHandler.END
    else:
        keyboard = [
            [InlineKeyboardButton("Registrarse", callback_data='register')],
            [InlineKeyboardButton("Iniciar Sesión", callback_data='login')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        msg.reply_text("No estás registrado. Por favor, elige una opción:", reply_markup=reply_markup)
        return CHOOSING

def auth_choice(update: Update, context: CallbackContext) -> int:
    """Captura la elección ('register' o 'login') y solicita el nombre de usuario."""
    query = update.callback_query
    query.answer()
    context.user_data["auth_mode"] = query.data  # 'register' o 'login'
    query.edit_message_text("Por favor, envía tu nombre de usuario:")
    return WAIT_USERNAME

def receive_username(update: Update, context: CallbackContext) -> int:
    """Recibe el nombre de usuario y solicita la contraseña."""
    username = update.message.text
    context.user_data["username"] = username
    update.message.reply_text("Ahora, por favor, envía tu contraseña:")
    return WAIT_PASSWORD

def receive_password(update: Update, context: CallbackContext) -> int:
    """
    Recibe la contraseña.
      - Si es login: valida las credenciales.
      - Si es registro: solicita la dirección.
    """
    password = update.message.text
    context.user_data["password"] = password
    auth_mode = context.user_data.get("auth_mode", "register")

    if auth_mode == "login":
        user_id = update.effective_user.id
        session = get_session()
        existing_user = session.query(User).filter(User.telegram_id == str(user_id)).first()
        if not existing_user:
            update.message.reply_text("No estás registrado. Por favor, regístrate primero.")
            return WAIT_USERNAME
        else:
            if (existing_user.username == context.user_data.get("username") and 
                existing_user.password_hash == password):
                update.message.reply_text("Inicio de sesión exitoso. ¡Bienvenido!")
                from handlers.menu import show_main_menu
                show_main_menu(update, context)
                return ConversationHandler.END
            else:
                update.message.reply_text("Credenciales incorrectas. Intenta de nuevo.\nPor favor, envía tu nombre de usuario:")
                return WAIT_USERNAME
    else:
        update.message.reply_text("Por favor, envía tu dirección:")
        return WAIT_ADDRESS

def receive_address(update: Update, context: CallbackContext) -> int:
    """
    Recibe la dirección, crea el usuario y muestra el mensaje final con el botón "Menu Principal".
    """
    address = update.message.text
    context.user_data["address"] = address
    user_id = update.effective_user.id
    session = get_session()
    if session.query(User).filter(User.telegram_id == str(user_id)).first():
        update.message.reply_text("Ya estás registrado. Por favor, inicia sesión.")
        return WAIT_USERNAME
    else:
        new_user = User(
            telegram_id=str(user_id),
            username=context.user_data.get("username"),
            password_hash=context.user_data.get("password"),
            address=address
        )
        session.add(new_user)
        session.commit()
        keyboard = [[InlineKeyboardButton("Menu Principal", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text("Se ha registrado exitosamente, presione el botón 'Menu Principal' para iniciar.", reply_markup=reply_markup)
        return ConversationHandler.END

def cancel(update: Update, context: CallbackContext) -> int:
    update.message.reply_text("Operación cancelada.")
    return ConversationHandler.END

def menu_button_handler(update: Update, context: CallbackContext) -> int:
    """Maneja el callback "main_menu" y muestra el menú principal."""
    query = update.callback_query
    query.answer()
    from handlers.menu import show_main_menu
    show_main_menu(update, context)
    return ConversationHandler.END

def restart_auth(update: Update, context: CallbackContext) -> int:
    """
    Reinicia el flujo de autenticación.
    Se usa cuando se pulsa "Iniciar Sesión" o "Registrarse" desde la pantalla de logout.
    Establece el modo forzado y llama a start().
    """
    if update.callback_query:
        update.callback_query.answer()
        mode = update.callback_query.data  # "login" o "register"
        context.user_data["force_mode"] = mode
    return start(update, context)

auth_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        CHOOSING: [CallbackQueryHandler(auth_choice, pattern="^(register|login)$")],
        WAIT_USERNAME: [MessageHandler(Filters.text & ~Filters.command, receive_username)],
        WAIT_PASSWORD: [MessageHandler(Filters.text & ~Filters.command, receive_password)],
        WAIT_ADDRESS: [MessageHandler(Filters.text & ~Filters.command, receive_address)]
    },
    fallbacks=[
        CommandHandler("cancel", cancel),
        CallbackQueryHandler(menu_button_handler, pattern="^main_menu$")
    ],
    allow_reentry=True
)
