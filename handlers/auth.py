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

# Estados para el ConversationHandler
CHOOSING, WAIT_USERNAME, WAIT_PASSWORD = range(3)

def start(update: Update, context: CallbackContext) -> int:
    """
    Función que se ejecuta con el comando /start.
    Si el usuario ya está registrado (según su telegram_id), se lo dirige al menú principal.
    Si no, se le pide que se autentique (registrarse o iniciar sesión).
    """
    user_id = update.effective_user.id
    session = get_session()
    user = session.query(User).filter(User.telegram_id == str(user_id)).first()

    if user:
        update.message.reply_text("¡Bienvenido de nuevo! Accediendo al menú principal.")
        # Aquí se podría invocar la función que muestra el menú principal, por ejemplo: menu.show_main_menu(update, context)
        return ConversationHandler.END
    else:
        # Usuario no registrado: se le muestra un teclado con opciones para registrarse o iniciar sesión
        keyboard = [
            [InlineKeyboardButton("Registrarse", callback_data='register')],
            [InlineKeyboardButton("Iniciar Sesión", callback_data='login')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text("No estás registrado. Por favor, elige una opción:", reply_markup=reply_markup)
        return CHOOSING

def auth_choice(update: Update, context: CallbackContext) -> int:
    """
    Captura la elección del usuario (registrarse o iniciar sesión) y solicita el nombre de usuario.
    """
    query = update.callback_query
    query.answer()
    choice = query.data
    # Guardamos en user_data el modo de autenticación elegido: 'register' o 'login'
    context.user_data["auth_mode"] = choice
    query.edit_message_text("Por favor, envía tu nombre de usuario:")
    return WAIT_USERNAME

def receive_username(update: Update, context: CallbackContext) -> int:
    """
    Recibe y almacena el nombre de usuario, solicitando luego la contraseña.
    """
    username = update.message.text
    context.user_data["username"] = username
    update.message.reply_text("Ahora, por favor, envía tu contraseña:")
    return WAIT_PASSWORD

def receive_password(update: Update, context: CallbackContext) -> int:
    """
    Recibe la contraseña y, según el modo de autenticación, intenta iniciar sesión o registrar al usuario.
    """
    password = update.message.text
    username = context.user_data.get("username")
    auth_mode = context.user_data.get("auth_mode", "register")  # Por defecto, se asume registro
    user_id = update.effective_user.id
    session = get_session()
    existing_user = session.query(User).filter(User.telegram_id == str(user_id)).first()

    if auth_mode == "login":
        if not existing_user:
            update.message.reply_text("No estás registrado. Por favor, regístrate primero.")
            return WAIT_USERNAME
        else:
            # Validar credenciales (en este ejemplo se compara directamente el texto)
            if existing_user.username == username and existing_user.password_hash == password:
                update.message.reply_text("Inicio de sesión exitoso. ¡Bienvenido!")
                # Aquí se invocaría la función que muestra el menú principal.
                return ConversationHandler.END
            else:
                update.message.reply_text("Credenciales incorrectas. Intenta de nuevo.\nPor favor, envía tu nombre de usuario:")
                return WAIT_USERNAME
    else:  # Registro
        if existing_user:
            update.message.reply_text("Ya estás registrado. Por favor, inicia sesión.")
            return WAIT_USERNAME
        else:
            # Crear el nuevo usuario (recuerda: en producción, hashear la contraseña)
            new_user = User(telegram_id=str(user_id), username=username, password_hash=password)
            session.add(new_user)
            session.commit()
            update.message.reply_text("Registro exitoso. ¡Bienvenido!")
            # Aquí se podría invocar la función que muestra el menú principal.
            return ConversationHandler.END

def cancel(update: Update, context: CallbackContext) -> int:
    """
    Permite cancelar la operación de autenticación.
    """
    update.message.reply_text("Operación cancelada.")
    return ConversationHandler.END

# Definición del ConversationHandler para la autenticación
auth_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        CHOOSING: [CallbackQueryHandler(auth_choice, pattern="^(register|login)$")],
        WAIT_USERNAME: [MessageHandler(Filters.text & ~Filters.command, receive_username)],
        WAIT_PASSWORD: [MessageHandler(Filters.text & ~Filters.command, receive_password)]
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    allow_reentry=True
)
