# handlers/auth.py

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

# Definición de estados para el ConversationHandler:
# 0: CHOOSING, 1: WAIT_USERNAME, 2: WAIT_PASSWORD, 3: WAIT_ADDRESS
CHOOSING, WAIT_USERNAME, WAIT_PASSWORD, WAIT_ADDRESS = range(4)

def start(update: Update, context: CallbackContext) -> int:
    """
    Punto de entrada con /start.
    Si el usuario ya está registrado, muestra el menú principal.
    Si no, solicita que se autentique (registro o login).
    """
    user_id = update.effective_user.id
    session = get_session()
    user = session.query(User).filter(User.telegram_id == str(user_id)).first()

    if user:
        # Si el usuario ya está registrado, se muestra el menú principal.
        update.message.reply_text("¡Bienvenido de nuevo! Accediendo al menú principal...")
        from handlers.menu import show_main_menu
        show_main_menu(update, context)
        return ConversationHandler.END
    else:
        # Si el usuario no está registrado, se le solicita que elija entre registrarse o iniciar sesión.
        keyboard = [
            [InlineKeyboardButton("Registrarse", callback_data='register')],
            [InlineKeyboardButton("Iniciar Sesión", callback_data='login')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text("No estás registrado. Por favor, elige una opción:", reply_markup=reply_markup)
        return CHOOSING

def auth_choice(update: Update, context: CallbackContext) -> int:
    """
    Captura la elección del usuario (registrarse o iniciar sesión)
    y solicita el nombre de usuario.
    """
    query = update.callback_query
    query.answer()
    choice = query.data
    context.user_data["auth_mode"] = choice  # 'register' o 'login'
    query.edit_message_text("Por favor, envía tu nombre de usuario:")
    return WAIT_USERNAME

def receive_username(update: Update, context: CallbackContext) -> int:
    """
    Recibe el nombre de usuario y solicita la contraseña.
    """
    username = update.message.text
    context.user_data["username"] = username
    update.message.reply_text("Ahora, por favor, envía tu contraseña:")
    return WAIT_PASSWORD

def receive_password(update: Update, context: CallbackContext) -> int:
    """
    Recibe la contraseña. Si es login, valida las credenciales.
    Si es registro, pasa a solicitar la dirección.
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
            # Comparar credenciales (en producción, recuerda hashear la contraseña)
            if existing_user.username == context.user_data.get("username") and existing_user.password_hash == password:
                update.message.reply_text("Inicio de sesión exitoso. ¡Bienvenido!")
                from handlers.menu import show_main_menu
                show_main_menu(update, context)
                return ConversationHandler.END
            else:
                update.message.reply_text("Credenciales incorrectas. Intenta de nuevo.\nPor favor, envía tu nombre de usuario:")
                return WAIT_USERNAME
    else:
        # En registro, después de la contraseña se solicita la dirección.
        update.message.reply_text("Por favor, envía tu dirección:")
        return WAIT_ADDRESS

def receive_address(update: Update, context: CallbackContext) -> int:
    """
    Recibe la dirección del usuario, crea el nuevo usuario y muestra un mensaje
    confirmando el registro, junto con un botón "Menu Principal" para iniciar.
    """
    address = update.message.text
    context.user_data["address"] = address
    user_id = update.effective_user.id
    session = get_session()

    # Verifica si el usuario ya existe (por seguridad)
    if session.query(User).filter(User.telegram_id == str(user_id)).first():
        update.message.reply_text("Ya estás registrado. Por favor, inicia sesión.")
        return WAIT_USERNAME
    else:
        # Crear el nuevo usuario con los datos recogidos
        new_user = User(
            telegram_id=str(user_id),
            username=context.user_data.get("username"),
            password_hash=context.user_data.get("password"),
            address=address  # Asegúrate de que el modelo User tenga el campo 'address'
        )
        session.add(new_user)
        session.commit()
        # Enviar mensaje final con botón para el menú principal
        keyboard = [[InlineKeyboardButton("Menu Principal", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text(
            "Se ha registrado exitosamente, presione el botón 'Menu Principal' para iniciar.",
            reply_markup=reply_markup
        )
        return ConversationHandler.END

def cancel(update: Update, context: CallbackContext) -> int:
    """
    Permite cancelar la operación.
    """
    update.message.reply_text("Operación cancelada.")
    return ConversationHandler.END

def menu_button_handler(update: Update, context: CallbackContext) -> int:
    """
    Maneja el callback del botón "Menu Principal" y muestra el menú.
    """
    query = update.callback_query
    query.answer()
    from handlers.menu import show_main_menu
    show_main_menu(update, context)
    return ConversationHandler.END

# Definición del ConversationHandler para la autenticación
auth_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        CHOOSING: [CallbackQueryHandler(auth_choice, pattern="^(register|login)$")],
        WAIT_USERNAME: [MessageHandler(Filters.text & ~Filters.command, receive_username)],
        WAIT_PASSWORD: [MessageHandler(Filters.text & ~Filters.command, receive_password)],
        WAIT_ADDRESS: [MessageHandler(Filters.text & ~Filters.command, receive_address)],
    },
    fallbacks=[
        CommandHandler("cancel", cancel),
        CallbackQueryHandler(menu_button_handler, pattern="^main_menu$")
    ],
    allow_reentry=True
)
