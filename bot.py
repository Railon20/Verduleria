#!/usr/bin/env python
# -*- coding: utf-8 -*-
# IMPORTANTE: Asegúrate de tener instalada la tabla "products" en tu base de datos.

# --- Forzamos que tzlocal retorne una zona de pytz (si fuera necesario) ---
import asyncio
import tzlocal
import pytz
# Forzamos que tzlocal.get_localzone() retorne pytz.utc
tzlocal.get_localzone = lambda: pytz.utc

# Parche para que AsyncIOScheduler use siempre pytz.utc
import apscheduler.schedulers.asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler

original_configure = AsyncIOScheduler._configure
def patched_configure(self, config):
    # Forzamos la zona horaria a pytz.utc, ignorando lo que traiga la configuración
    config['timezone'] = pytz.utc
    original_configure(self, config)
AsyncIOScheduler._configure = patched_configure


import logging
import psycopg2
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)
import sys  # Asegúrate de importarlo para forzar el vaciado del buffer de stdout
from cachetools import cached, TTLCache
import mercadopago
import datetime
import random
import os
from flask import Flask, request, jsonify
import threading
from psycopg2 import pool
from telegram.error import BadRequest


app = Flask(__name__)

BOT_LOOP = None

ADMIN_CHAT_ID = 6952319386  # Reemplaza con el chat ID de tu administrador
PROVIDER_CHAT_ID = 222222222  # Reemplaza con el chat ID del proveedor

TELEGRAM_BOT = None             # Se asignará luego de crear la aplicación

allowed_ids = [ADMIN_CHAT_ID, PROVIDER_CHAT_ID]  # Puedes agregar los IDs del personal adicional aquí


def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in allowed_ids:
            # Si viene por mensaje
            if update.message:
                await update.message.reply_text("No tienes permisos para usar esta función.")
            # Si viene por callback query
            elif update.callback_query:
                await update.callback_query.answer("No tienes permisos para usar esta función.", show_alert=True)
            return ConversationHandler.END
        return await func(update, context)
    return wrapper


# Configuración de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Nuevos estados (asegúrate de que no colisionen con los existentes)
# Estado para el historial (si lo manejas como conversación, sino solo una función de consulta)
# Estados nuevos (asegúrate de que no colisionen con los ya existentes)
# Definición de estados de conversación (todos en un solo bloque)
(
    NAME, 
    ADDRESS, 
    MAIN_MENU, 
    ORDERING, 
    ASK_QUANTITY, 
    SELECT_CART, 
    NEW_CART, 
    POST_ADHESION, 
    CHANGE_STATUS, 
    GESTION_PEDIDOS, 
    CARTS_LIST, 
    CART_MENU, 
    ASIGNAR_CONJUNTOS, 
    SELECCIONAR_EQUIPO, 
    REVOCAR_CONJUNTOS, 
    VER_EQUIPOS, 
    CREAR_NUEVO_EQUIPO,
    CAMBIAR_DIRECCION
) = range(18)
 

# Crea un cache con un tiempo de vida de 300 segundos (5 minutos)
user_info_cache = TTLCache(maxsize=1000, ttl=300)

# Nota: Los estados CARTS_LIST y CART_MENU ya están definidos anteriormente (ej. 8 y 9).
# Configura el pool (ajusta los parámetros según tu entorno)
db_pool = pool.ThreadedConnectionPool(
    minconn=1,
    maxconn=20,
    dbname=os.getenv('DB_NAME'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD'),
    host=os.getenv('DB_HOST'),
    port=os.getenv('DB_PORT')
)

#DB_NAME = ""
#DB_USER = ""
#DB_PASSWORD = ""
#DB_HOST = "localhost"
#DB_PORT = ""

TOKEN = os.getenv("TELEGRAM_TOKEN")
#TOKEN = ""
if not TOKEN:
    raise ValueError("No se encontró la variable de entorno TELEGRAM_TOKEN.")


MP_SDK = os.getenv('MP_SDK')
#MP_SDK = ""
# Conjunto para registrar los IDs de pago ya procesados
processed_payment_ids = set()

application = Application.builder().token(TOKEN).build()
TELEGRAM_BOT = application.bot

#def set_telegram_webhook():
#    url = "https://verduleria.onrender.com/webhook2"  # Reemplaza con el dominio de tu servicio
#    s = TELEGRAM_BOT.set_webhook(url)
#    if s:
#        logger.info("Webhook configurado correctamente")
#    else:
#        logger.error("Error configurando el webhook")

@cached(cache=user_info_cache)
def get_user_info_cached(telegram_id):
    conn = connect_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT name, address FROM users WHERE telegram_id = %s", (telegram_id,))
        row = cur.fetchone()
        return {'name': row[0], 'address': row[1]} if row else None
    except Exception as e:
        logger.error(f"Error al obtener info del usuario: {e}")
        return None
    finally:
        cur.close()
        release_db(conn)

class SimpleContext:
    def __init__(self, bot):
        self.bot = bot

def start_bot_loop(loop):
    asyncio.set_event_loop(loop)
    logger.info("Iniciando el event loop del bot")
    loop.run_forever()


def ensure_bot_loop():
    """Se asegura de que BOT_LOOP esté inicializado y corriendo.
    Si no está creado, lo crea, inicia el hilo y ejecuta la inicialización de la aplicación.
    """
    global BOT_LOOP
    if BOT_LOOP is None:
        BOT_LOOP = asyncio.new_event_loop()
        # Inicia el bucle en un hilo separado (daemon)
        threading.Thread(target=start_bot_loop, args=(BOT_LOOP,), daemon=True).start()
        # Inicializa la aplicación en ese bucle
        future = asyncio.run_coroutine_threadsafe(application.initialize(), BOT_LOOP)
        future.result()  # Espera a que se inicialice
    return BOT_LOOP

def connect_db():
    """Obtiene una conexión del pool."""
    try:
        conn = db_pool.getconn()
        if conn:
            return conn
    except Exception as e:
        logger.error(f"Error obteniendo conexión del pool: {e}")
        raise e

    #return psycopg2.connect(
    #    dbname=DB_NAME,
    #    user=DB_USER,
    #    password=DB_PASSWORD,
    #    host=DB_HOST,
    #    port=DB_PORT
    #)


def release_db(conn):
    """Devuelve la conexión al pool."""
    try:
        db_pool.putconn(conn)
    except Exception as e:
        logger.error(f"Error devolviendo conexión al pool: {e}")

def init_db():
    """Crea la tabla 'users' si no existe."""
    conn = connect_db()
    cur = None
    try:
    # ... usar conn
        conn.commit()  # si es necesario
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id BIGINT PRIMARY KEY,
                name TEXT NOT NULL,
                address TEXT NOT NULL
            );
        """)
        # Crear tabla de conjuntos
        cur.execute("""
            CREATE TABLE IF NOT EXISTS conjuntos (
                id SERIAL PRIMARY KEY,
                numero_conjunto INTEGER NOT NULL,
                equipo_id INTEGER  -- Puede ser NULL si no se ha asignado un equipo
            );
        """)
        # Aquí podrías agregar también las tablas de trabajadores y equipos si aún no existen.
        conn.commit()
    except Exception as e:
        logger.error(f"Error al inicializar la base de datos: {e}")
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            release_db(conn)

async def show_carts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Muestra la lista de carritos del usuario con botones para crear nuevo carrito y volver al menú principal."""
    query = update.callback_query
    await query.answer()
    telegram_id = query.from_user.id
    carts = get_user_carts(telegram_id)
    logger.info(f"Mostrando carritos para usuario {telegram_id}: {carts}")
    keyboard = []
    if not carts:
        # Si no hay carritos, mostramos botón para crear uno nuevo y volver al menú principal
        keyboard.append([InlineKeyboardButton("Nuevo Carrito", callback_data="new_cart")])
        keyboard.append([InlineKeyboardButton("Volver al Menú Principal", callback_data="back_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("No tienes carritos creados.", reply_markup=reply_markup)
        return CARTS_LIST
    else:
        for cart in carts:
            # Se crea el callback data con el formato "cartmenu_{cart_id}"
            keyboard.append([InlineKeyboardButton(f"{cart['name']} (Total: {cart['total']:.2f})", callback_data=f"cartmenu_{cart['id']}")])
        # Botón para crear un nuevo carrito
        keyboard.append([InlineKeyboardButton("Nuevo Carrito", callback_data="new_cart")])
        # Botón para volver al menú principal
        keyboard.append([InlineKeyboardButton("Volver al Menú Principal", callback_data="back_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Tus carritos:", reply_markup=reply_markup)
        return CARTS_LIST

def update_order_status(confirmation_code):
    """Busca un pedido pendiente con el código dado y lo actualiza a 'entregado'.
       Retorna el telegram_id del usuario si se actualizó correctamente, o None si no se encontró."""
    conn = connect_db()
    cur = None
    try:
    # ... usar conn
        cur = conn.cursor()
        # Se busca el pedido pendiente con el código dado
        cur.execute("SELECT id, telegram_id FROM orders WHERE confirmation_code = %s AND status = 'pendiente'", (confirmation_code,))
        row = cur.fetchone()
        if not row:
            return None
        order_id, telegram_id = row
        # Actualizar el estado a 'entregado'
        cur.execute("UPDATE orders SET status = 'entregado', order_date = NOW() WHERE id = %s", (order_id,))
        conn.commit()
        return telegram_id
    except Exception as e:
        logger.error(f"Error al actualizar el estado del pedido: {e}")
        if conn:
            conn.rollback()
        return None
    finally:
        release_db(conn)

async def change_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Maneja la entrada del código de confirmación para cambiar el estado de un pedido."""
    code = update.message.text.strip()
    user_id = update_order_status(code)
    if user_id is None:
        await update.message.reply_text("Código inválido. Por favor, ingrese un código válido:")
        return CHANGE_STATUS  # Permite reintentar
    else:
        # Notificar al usuario cuyo pedido se actualizó
        try:
            await context.bot.send_message(chat_id=user_id, text="Su pedido ha sido marcado como entregado.")
        except Exception as e:
            logger.error(f"Error al notificar al usuario: {e}")
        await update.message.reply_text("Cambio de estado exitoso.")
        return MAIN_MENU

def get_delivered_orders(telegram_id, limit=20):
    """Obtiene los últimos 'limit' pedidos entregados para el usuario."""
    conn = None
    cur = None
    try:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, cart_id, confirmation_code, order_date FROM orders WHERE telegram_id = %s AND status = 'entregado' ORDER BY order_date DESC LIMIT %s",
            (telegram_id, limit)
        )
        orders = cur.fetchall()
        return orders
    except Exception as e:
        logger.error(f"Error al obtener pedidos entregados: {e}")
        return []
    finally:
        release_db(conn)

async def show_history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Muestra los últimos 20 pedidos entregados del usuario (historial)."""
    query = update.callback_query
    await query.answer()
    telegram_id = query.from_user.id
    orders = get_delivered_orders(telegram_id, limit=20)
    if not orders:
        keyboard = [[InlineKeyboardButton("Volver al Menú Principal", callback_data="back_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("No tienes pedidos entregados en tu historial.", reply_markup=reply_markup)
        return MAIN_MENU
    text = "Historial de pedidos entregados:\n\n"
    for order in orders:
        order_id, cart_id, confirmation_code, order_date = order
        if isinstance(order_date, datetime.datetime):
            order_date_str = order_date.strftime("%Y-%m-%d %H:%M:%S")
        else:
            order_date_str = str(order_date)
        text += f"Pedido #{order_id}: Código {confirmation_code} - Fecha {order_date_str}\n"
    keyboard = [[InlineKeyboardButton("Volver al Menú Principal", callback_data="back_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup)
    return MAIN_MENU

#########################################
# NUEVAS FUNCIONES PARA GESTIÓN DE CONJUNTOS
#########################################

def get_last_conjunto():
    """
    Retorna el último conjunto creado (con su id y número de conjunto)
    o None si aún no existe.
    """
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT id, numero_conjunto FROM conjuntos ORDER BY id DESC LIMIT 1")
    result = cur.fetchone()
    cur.close()
    release_db(conn)
    return result  # Ej: (3, 1) => id=3, numero_conjunto=1

def count_pending_orders_in_conjunto(conjunto_id):
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM orders WHERE conjunto_id = %s AND status = 'pendiente'", (conjunto_id,))
    count = cur.fetchone()[0]
    cur.close()
    release_db(conn)
    return count

# 1. Función para generar el PDF de un conjunto

def generate_conjunto_pdf(conjunto_id, show_confirmation=True):
    """
    Genera un PDF para el conjunto especificado.
    Se listan los pedidos del conjunto con su fecha/hora de pago, artículos (nombre, cantidad, subtotal),
    datos del cliente y código de confirmación (este último solo se muestra si show_confirmation es True).
    También se muestra la cantidad de pedidos restantes al inicio y al final.
    
    Retorna el nombre del archivo PDF generado.
    """
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    
    # Obtener la cantidad de pedidos pendientes en el conjunto
    pendientes = count_pending_orders_in_conjunto(conjunto_id)
    pdf.cell(0, 10, txt=f"Pedidos restantes: {pendientes}", ln=True)
    pdf.ln(5)
    
    # Obtener todos los pedidos del conjunto ordenados por fecha
    conn = connect_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, cart_id, confirmation_code, order_date, telegram_id FROM orders WHERE conjunto_id = %s ORDER BY order_date",
        (conjunto_id,)
    )
    pedidos = cur.fetchall()
    cur.close()
    release_db(conn)
    
    for pedido in pedidos:
        order_id, cart_id, confirmation_code, order_date, client_id = pedido
        # Formatear la fecha
        if isinstance(order_date, datetime.datetime):
            fecha = order_date.strftime("%Y-%m-%d %H:%M:%S")
        else:
            fecha = str(order_date)
        pdf.cell(0, 10, txt=f"Fecha y Hora del pedido: {fecha}", ln=True)
        pdf.ln(2)
        pdf.cell(0, 10, txt="Artículos:", ln=True)
        # Obtener los items del carrito (usando tu función get_cart_details)
        items = get_cart_details(cart_id)
        for item in items:
            line = f"{item['name']}: {item['quantity']} = {item['subtotal']:.2f}"
            pdf.cell(0, 10, txt=line, ln=True)
        pdf.ln(2)
        pdf.cell(0, 10, txt="Cliente:", ln=True)
        # Obtener información del cliente (usando tu función get_user_info)
        client_info = get_user_info_cached(client_id)
        if client_info:
            pdf.cell(0, 10, txt=f"Nombre: {client_info['name']}", ln=True)
            pdf.cell(0, 10, txt=f"Dirección: {client_info['address']}", ln=True)
        else:
            pdf.cell(0, 10, txt="Nombre: Desconocido", ln=True)
            pdf.cell(0, 10, txt="Dirección: Desconocida", ln=True)
        # Mostrar el código de confirmación solo si se solicita
        if show_confirmation:
            pdf.cell(0, 10, txt=f"Código de Confirmación: {confirmation_code}", ln=True)
        pdf.ln(5)
    
    pdf.ln(5)
    pdf.cell(0, 10, txt=f"Pedidos restantes: {pendientes}", ln=True)
    
    filename = f"conjunto_{conjunto_id}.pdf"
    pdf.output(filename)
    return filename

# -----------------------------------------------------------------------------
# 2. Función para obtener el equipo al que pertenece un trabajador

def get_equipo_del_trabajador(telegram_id):
    """
    Retorna un diccionario con los datos del equipo al que pertenece el trabajador
    (si el trabajador está en la tabla 'equipos' en alguna de las columnas trabajador1 o trabajador2).
    Si no se encuentra, retorna None.
    """
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT id, trabajador1, trabajador2 FROM equipos WHERE trabajador1 = %s OR trabajador2 = %s", (telegram_id, telegram_id))
    row = cur.fetchone()
    cur.close()
    release_db(conn)
    if row:
        equipo_id, t1, t2 = row
        return {"id": equipo_id, "trabajador1": t1, "trabajador2": t2}
    else:
        return None

# -----------------------------------------------------------------------------
# 3. Función para obtener los conjuntos asignados a un equipo, ordenados por pendientes

def get_conjuntos_por_equipo(equipo_id):
    """
    Retorna una lista de diccionarios con los conjuntos asignados al equipo indicado.
    Cada diccionario contiene: id, numero (numero_conjunto) y pendientes.
    Se ordena de menor a mayor según la cantidad de pedidos pendientes.
    """
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT id, numero_conjunto FROM conjuntos WHERE equipo_id = %s", (equipo_id,))
    rows = cur.fetchall()
    cur.close()
    release_db(conn)
    conjuntos = []
    for row in rows:
        conjunto_id, numero = row
        pendientes = count_pending_orders_in_conjunto(conjunto_id)
        conjuntos.append({"id": conjunto_id, "numero": numero, "pendientes": pendientes})
    conjuntos.sort(key=lambda c: c["pendientes"])
    return conjuntos

# -----------------------------------------------------------------------------
# 4. Handler para la opción "Gestión de Pedidos" para el personal (trabajadores)

async def gestion_pedidos_personal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Este handler muestra un mensaje indicando que el trabajador y su compañero tienen asignados ciertos conjuntos,
    y presenta botones (uno por cada conjunto asignado al equipo del trabajador) con:
      "Conjunto <número>: <pendientes> pendientes"
    Al presionar alguno se descargará el PDF correspondiente.
    """
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    equipo = get_equipo_del_trabajador(user_id)
    if not equipo:
        await query.edit_message_text("No se encontró un equipo asignado a su cuenta.")
        return MAIN_MENU
    equipo_id = equipo["id"]
    conjuntos = get_conjuntos_por_equipo(equipo_id)
    if not conjuntos:
        await query.edit_message_text("Usted y su compañero de equipo no tienen conjuntos asignados.")
        return MAIN_MENU
    buttons = []
    for c in conjuntos:
        btn_text = f"Conjunto {c['numero']}: {c['pendientes']} pendientes"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"descargarpdf_{c['id']}")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text("Usted y su compañero de equipo tienen asignado los siguientes conjuntos (presione en un conjunto para consultarlo):", reply_markup=reply_markup)
    return GESTION_PEDIDOS

# -----------------------------------------------------------------------------
# 5. Handler para descargar el PDF de un conjunto seleccionado

async def descargar_pdf_conjunto_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Cuando se presiona en un conjunto (botón con callback_data "descargarpdf_<conjunto_id>"),
    se genera el PDF con la información de ese conjunto y se envía al usuario.
    Si el usuario es trabajador, se omite el código de confirmación.
    """
    query = update.callback_query
    await query.answer()
    try:
        # Extraer el id del conjunto del callback data "descargarpdf_<conjunto_id>"
        conjunto_id = int(query.data.split("_")[1])
    except Exception as e:
        await query.edit_message_text("Error al procesar el conjunto seleccionado.")
        return GESTION_PEDIDOS
    # Determinar si se debe mostrar el código de confirmación
    user_id = query.from_user.id
    show_conf = not es_trabajador(user_id)
    filename = generate_conjunto_pdf(conjunto_id, show_confirmation=show_conf)
    # Enviar el PDF como documento
    with open(filename, "rb") as doc_file:
        await context.bot.send_document(chat_id=user_id, document=doc_file, filename=filename)
    # Mostrar un botón para volver al menú de Gestión de Pedidos
    keyboard = [[InlineKeyboardButton("Volver a Gestión de Pedidos", callback_data="gestion_pedidos_personal")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("PDF generado y enviado. Presione el botón para volver a Gestión de Pedidos.", reply_markup=reply_markup)
    return GESTION_PEDIDOS

# -----------------------------------------------------------------------------
# Nota de integración en el ConversationHandler:
# En tu main_menu_handler, si el usuario es trabajador (es_trabajador(user_id)==True),
# añade un botón con callback_data "gestion_pedidos_personal" para esta opción.
#
# Por ejemplo, en main_menu_handler:
#
#   if es_trabajador(user_id):
#       keyboard.append([InlineKeyboardButton("Gestión de Pedidos", callback_data="gestion_pedidos_personal")])
#
# Y en tu ConversationHandler, añade:
#
#   SELECCIONAR_EQUIPO: [
#       CallbackQueryHandler(gestion_pedidos_personal_handler, pattern="^gestion_pedidos_personal$"),
#       CallbackQueryHandler(descargar_pdf_conjunto_handler, pattern="^descargarpdf_\\d+$")
#   ]
#
# Asegúrate de asignar un estado adecuado (por ejemplo, reutiliza GESTION_PEDIDOS o crea un nuevo estado si es necesario).


def create_new_conjunto(numero_conjunto):
    """
    Crea un nuevo registro en la tabla 'conjuntos' con el número de conjunto dado.
    Retorna el id del nuevo conjunto.
    """
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO conjuntos (numero_conjunto) VALUES (%s) RETURNING id", (numero_conjunto,))
    new_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    release_db(conn)
    return new_id

def insert_order_with_conjunto(cart_id, telegram_id, confirmation_code):
    """
    Inserta un nuevo pedido y lo asigna a un conjunto.
    La lógica es:
      - Si no existe ningún conjunto, se crea el conjunto 1.
      - Si existe un conjunto y éste tiene menos de 3 pedidos, se asigna ese mismo conjunto.
      - Si el conjunto actual ya tiene 3 pedidos, se crea un nuevo conjunto con el siguiente número.
    Retorna una tupla (order_id, conjunto_id).
    """
    last = get_last_conjunto()
    if last is None:
        new_num = 1
        conjunto_id = create_new_conjunto(new_num)
    else:
        last_conjunto_id, last_num = last
        if count_orders_in_conjunto(last_conjunto_id) < 3:
            conjunto_id = last_conjunto_id
        else:
            new_num = last_num + 1
            conjunto_id = create_new_conjunto(new_num)
    conn = connect_db()
    cur = conn.cursor()
    cur.execute(
         "INSERT INTO orders (cart_id, telegram_id, confirmation_code, status, conjunto_id) VALUES (%s, %s, %s, %s, %s) RETURNING id",
         (cart_id, telegram_id, confirmation_code, "pendiente", conjunto_id)
    )
    order_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    release_db(conn)
    return order_id, conjunto_id

def count_pending_orders_in_conjunto(conjunto_id):
    """
    Retorna la cantidad de pedidos pendientes en el conjunto.
    """
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM orders WHERE conjunto_id = %s AND status = 'pendiente'", (conjunto_id,))
    count = cur.fetchone()[0]
    cur.close()
    release_db(conn)
    return count

def finalize_conjunto(conjunto_id):
    """
    Finaliza (elimina) el conjunto cuando ya no quedan pedidos pendientes.
    """
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM conjuntos WHERE id = %s", (conjunto_id,))
    conn.commit()
    cur.close()
    release_db(conn)

def update_order_state(order_id, new_state):
    """
    Actualiza el estado de un pedido.
    Si se actualiza a 'entregado', y el conjunto del pedido ya no tiene pedidos pendientes,
    se finaliza el conjunto (se elimina).
    """
    now = datetime.datetime.now()
    conn = connect_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE orders SET status = %s, entrega_date = %s WHERE id = %s RETURNING conjunto_id",
        (new_state, now, order_id)
    )
    result = cur.fetchone()
    conn.commit()
    cur.close()
    release_db(conn)
    if result:
         conjunto_id = result[0]
         if new_state == "entregado" and count_pending_orders_in_conjunto(conjunto_id) == 0:
              finalize_conjunto(conjunto_id)
    return

#########################################
# GENERACIÓN DE PDF DE CONJUNTO (STUB)
#########################################

def es_trabajador(telegram_id):
    """
    Devuelve True si el telegram_id pertenece a un trabajador (o a alguien del personal),
    consultando la tabla "trabajadores".
    """
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM trabajadores WHERE telegram_id = %s", (telegram_id,))
    result = cur.fetchone()
    cur.close()
    release_db(conn)
    return result is not None

#########################################
# MODIFICACIONES EN EL HANDLER DE WEBHOOK
#########################################

# En el handler del webhook (mp_webhook) donde se inserta un pedido, en lugar de llamar a insert_order(),
# se debe llamar a insert_order_with_conjunto(). Por ejemplo:

# Reemplaza esta parte:
# order_id = insert_order(cart_id, user_id, confirmation_code)
# Por:
# order_id, conjunto_id = insert_order_with_conjunto(cart_id, user_id, confirmation_code)
# (Además, podrías registrar o notificar el conjunto asignado si lo deseas)

#########################################
# NOTA SOBRE LAS TABLAS "conjuntos", "trabajadores" y "equipos"
#########################################

# Deberás crear (o modificar) tus scripts de creación de base de datos para incluir las tablas:
#
# CREATE TABLE conjuntos (
#     id SERIAL PRIMARY KEY,
#     numero_conjunto INTEGER NOT NULL,
#     -- Puedes agregar un campo "estado" si lo requieres (por ejemplo: 'activo', 'finalizado')
# );
#
# CREATE TABLE trabajadores (
#     id SERIAL PRIMARY KEY,
#     nombre TEXT NOT NULL,
#     telegram_id BIGINT UNIQUE NOT NULL
# );
#
# CREATE TABLE equipos (
#     id SERIAL PRIMARY KEY,
#     trabajador1 BIGINT NOT NULL,
#     trabajador2 BIGINT NOT NULL,
#     -- Puedes agregar un campo para el nombre del equipo, etc.
# );
#
# Y en la tabla orders asegúrate de agregar un campo:
# ALTER TABLE orders ADD COLUMN conjunto_id INTEGER REFERENCES conjuntos(id);
#
# De esta forma se podrá asociar cada pedido a un conjunto.
#
# Además, para la asignación de conjuntos a equipos y la gestión de pedidos en conjunto,
# deberás implementar los handlers correspondientes en el menú "Gestión de Pedidos y Equipos",
# utilizando las nuevas funciones y realizando las consultas correspondientes.

#########################################
# FIN DE LAS MODIFICACIONES NECESARIAS
#########################################


async def cart_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Muestra el menú para un carrito específico con sus opciones y botones para volver."""
    query = update.callback_query
    await query.answer()
    logger.info(f"cart_menu_handler invocado con callback data: {query.data}")
    try:
        data = query.data
        # Se espera que el callback data tenga el formato "cartmenu_{cart_id}"
        if data.startswith("cartmenu_"):
            parts = data.split("_")
            cart_id = int(parts[1])
        elif data.startswith("back_cart_"):
            parts = data.split("_")
            cart_id = int(parts[2])
        else:
            raise ValueError("Formato de callback data no reconocido")
    except Exception as e:
        logger.error(f"Error al procesar callback data en cart_menu_handler: {e}")
        await query.edit_message_text("Error al procesar el carrito.")
        return MAIN_MENU
    context.user_data['selected_cart_id'] = cart_id
    carts = get_user_carts(query.from_user.id)
    logger.info(f"Carritos del usuario: {carts}")
    cart_info = next((c for c in carts if c['id'] == cart_id), None)
    if not cart_info:
        await query.edit_message_text("Carrito no encontrado.")
        return MAIN_MENU
    text = f"Menú del carrito: {cart_info['name']} (Total: {cart_info['total']:.2f})"
    keyboard = [
        [InlineKeyboardButton("Ver detalles del carrito", callback_data=f"cart_details_{cart_id}")],
        [InlineKeyboardButton("Agregar productos", callback_data=f"cart_add_{cart_id}")],
        [InlineKeyboardButton("Quitar productos", callback_data=f"cart_remove_{cart_id}")],
        [InlineKeyboardButton("Eliminar carrito", callback_data=f"cart_delete_{cart_id}")],
        [InlineKeyboardButton("Pagar carrito", callback_data=f"cart_pay_{cart_id}")],
        [InlineKeyboardButton("Volver a la lista de carritos", callback_data="show_carts")],
        [InlineKeyboardButton("Volver al Menú Principal", callback_data="back_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup)
    return CART_MENU

async def new_cart_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Manejador para el botón "Nuevo Carrito" en la opción Carritos del menú principal.
    Solicita al usuario que ingrese el nombre del nuevo carrito y cambia el estado a NEW_CART.
    """
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Ingrese el nombre del nuevo carrito:")
    return NEW_CART


async def cart_details_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Muestra los detalles del carrito: nombre, lista de productos con cantidad y subtotal, y total.
    Incluye un botón para volver al menú del carrito.
    """
    query = update.callback_query
    await query.answer()
    try:
        # Se espera que la callback_data tenga el formato "cart_details_{cart_id}"
        cart_id = int(query.data.split("_")[2])
    except Exception as e:
        await query.edit_message_text("Error al procesar el carrito.")
        return CART_MENU

    # Obtener la información del carrito del usuario
    carts = get_user_carts(query.from_user.id)
    cart_info = next((c for c in carts if c['id'] == cart_id), None)
    if not cart_info:
        await query.edit_message_text("Carrito no encontrado.")
        return CART_MENU

    # Obtener los detalles de los items del carrito
    details = get_cart_details(cart_id)
    details_text = f"Detalles del carrito '{cart_info['name']}':\n\n"
    if details:
        for item in details:
            details_text += f"• {item['name']}: {item['quantity']} = {item['subtotal']:.2f}\n"
    else:
        details_text += "El carrito está vacío.\n"
    details_text += f"\nTotal: {cart_info['total']:.2f}"

    # Botón para volver al menú del carrito
    keyboard = [[InlineKeyboardButton("Volver al menú del carrito", callback_data=f"cartmenu_{cart_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(details_text, reply_markup=reply_markup)
    return CART_MENU


async def cart_add_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Redirige al flujo de agregar productos usando el carrito seleccionado."""
    query = update.callback_query
    await query.answer()
    try:
        cart_id = int(query.data.split("_")[2])
    except Exception as e:
        await query.edit_message_text("Error al procesar el carrito.")
        return CART_MENU
    context.user_data['selected_cart_id'] = cart_id
    products = get_products()
    if not products:
        await query.edit_message_text("No hay productos disponibles.")
        return CART_MENU
    keyboard = []
    for product in products:
        keyboard.append([InlineKeyboardButton(product['name'], callback_data=f"product_{product['id']}")])
    # El botón "Volver" regresa al menú del carrito específico
    keyboard.append([InlineKeyboardButton("Volver al menú del carrito", callback_data=f"back_cart_{cart_id}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Seleccione un producto para agregar:", reply_markup=reply_markup)
    return ORDERING

async def cart_remove_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Muestra la lista de productos del carrito para quitar uno, con detalles y botón para volver al menú del carrito."""
    query = update.callback_query
    await query.answer()
    logger.info(f"[cart_remove_handler] Callback data recibida: {query.data}")
    try:
        # Se espera que el callback data tenga el formato "cart_remove_{cart_id}"
        parts = query.data.split("_")
        if len(parts) < 3:
            raise ValueError("Formato de callback data incorrecto")
        cart_id = int(parts[2])
    except Exception as e:
        logger.error(f"[cart_remove_handler] Error al parsear callback data: {e}")
        await query.edit_message_text("Error al procesar el carrito.")
        return CART_MENU

    # Obtener la información del carrito
    carts = get_user_carts(query.from_user.id)
    cart_info = next((c for c in carts if c['id'] == cart_id), None)
    if not cart_info:
        await query.edit_message_text("Carrito no encontrado.")
        return CART_MENU

    # Obtener los detalles actuales de los productos del carrito
    details = get_cart_details(cart_id)
    if not details:
        await query.edit_message_text("El carrito está vacío.")
        return CART_MENU

    # Armar mensaje y teclado con la lista de productos
    msg = f"Carrito: {cart_info['name']} (Total: {cart_info['total']:.2f})\n\n"
    msg += "Seleccione un producto para quitarlo:\n\n"
    keyboard = []
    for item in details:
        # Se genera callback data en el formato "cart_removeitem_{cart_id}_{product_id}"
        button_text = f"{item['name']} - {item['quantity']} = {item['subtotal']:.2f}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"cart_removeitem_{cart_id}_{item['product_id']}")])
    # Botón para volver al menú del carrito
    keyboard.append([InlineKeyboardButton("Volver al menú del carrito", callback_data=f"cartmenu_{cart_id}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(msg, reply_markup=reply_markup)
    return CART_MENU


def remove_product_from_cart(cart_id, product_id):
    """
    Elimina el producto del carrito (todas las entradas con ese product_id) y actualiza el total del carrito.
    """
    conn = None
    cur = None
    try:
        conn = connect_db()
        cur = conn.cursor()
        # Eliminar el producto del carrito
        cur.execute("DELETE FROM cart_items WHERE cart_id = %s AND product_id = %s", (cart_id, product_id))
        
        # Recalcular el total sumando los subtotales restantes en el carrito
        cur.execute("SELECT COALESCE(SUM(subtotal), 0) FROM cart_items WHERE cart_id = %s", (cart_id,))
        new_total = cur.fetchone()[0]
        
        # Actualizar el total del carrito en la tabla 'carts'
        cur.execute("UPDATE carts SET total = %s WHERE id = %s", (new_total, cart_id))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error al eliminar producto del carrito: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if cur:
            cur.close()
        if conn:
            release_db(conn)

async def cambiar_direccion_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Muestra la dirección actual del usuario y le pide ingresar la nueva dirección.
    Se muestra un botón 'Cancelar' que permite abortar el cambio y regresar al menú principal.
    """
    query = update.callback_query
    await query.answer()
    telegram_id = query.from_user.id
    user_info = get_user_info_cached(telegram_id)
    current_address = user_info.get("address", "No definida") if user_info else "No definida"
    
    # Mostrar la dirección actual y pedir la nueva
    keyboard = [[InlineKeyboardButton("Cancelar", callback_data="cancelar_direccion")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        text=f"Tu dirección actual es: {current_address}\n\nPor favor, ingresa la nueva dirección:",
        reply_markup=reply_markup
    )
    # Pasa al estado CAMBIAR_DIRECCION para esperar la entrada de texto
    return CAMBIAR_DIRECCION

async def procesar_cambio_direccion_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Toma la nueva dirección ingresada por el usuario, actualiza la base de datos
    y muestra un mensaje de confirmación con un botón 'Aceptar' que regresa al menú principal.
    """
    new_address = update.message.text.strip()
    telegram_id = update.effective_user.id
    conn = None
    cur = None
    try:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("UPDATE users SET address = %s WHERE telegram_id = %s", (new_address, telegram_id))
        conn.commit()
    except Exception as e:
        logger.error(f"Error al actualizar la dirección: {e}")
        await update.message.reply_text("Ocurrió un error al actualizar la dirección. Inténtalo nuevamente.")
        return CAMBIAR_DIRECCION
    finally:
        if cur:
            cur.close()
        if conn:
            release_db(conn)
    
    keyboard = [[InlineKeyboardButton("Aceptar", callback_data="back_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        text=f"Dirección actualizada exitosamente. Los pedidos serán enviados a: {new_address}",
        reply_markup=reply_markup
    )
    # Regresa al menú principal
    return MAIN_MENU

async def cancelar_cambio_direccion_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Cancela el cambio de dirección y regresa al menú principal.
    """
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("Aceptar", callback_data="back_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Cambio de dirección cancelado.", reply_markup=reply_markup)
    return MAIN_MENU

async def cart_removeitem_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Elimina el producto seleccionado del carrito y muestra la lista actualizada de productos para quitar."""
    query = update.callback_query
    await query.answer()
    try:
        # Se espera que la callback_data tenga el formato "cart_removeitem_{cart_id}_{product_id}"
        parts = query.data.split("_")
        cart_id = int(parts[2])
        product_id = int(parts[3])
    except Exception as e:
        await query.edit_message_text("Error al procesar la selección.")
        return CART_MENU

    # Intentar eliminar el producto del carrito
    success = remove_product_from_cart(cart_id, product_id)
    if success:
        msg = "Producto eliminado del carrito.\n\n"
    else:
        msg = "Error al eliminar el producto del carrito.\n\n"

    # Re-obtener la información actualizada del carrito
    carts = get_user_carts(query.from_user.id)
    cart_info = next((c for c in carts if c['id'] == cart_id), None)
    if not cart_info:
        await query.edit_message_text("Carrito no encontrado.")
        return MAIN_MENU

    # Obtener los detalles actualizados de los productos en el carrito
    details = get_cart_details(cart_id)
    if details:
        msg += f"Carrito: {cart_info['name']} (Total: {cart_info['total']:.2f})\nSeleccione otro producto para quitarlo:\n\n"
        keyboard = []
        for item in details:
            # Genera el callback data con el formato correcto
            keyboard.append([InlineKeyboardButton(
                f"{item['name']} - {item['quantity']} = {item['subtotal']:.2f}",
                callback_data=f"cart_removeitem_{cart_id}_{item['product_id']}"
            )])
        keyboard.append([InlineKeyboardButton("Volver al menú del carrito", callback_data=f"cartmenu_{cart_id}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(msg, reply_markup=reply_markup)
    else:
        msg += "El carrito está vacío."
        keyboard = [[InlineKeyboardButton("Volver al menú del carrito", callback_data=f"cartmenu_{cart_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(msg, reply_markup=reply_markup)
    return CART_MENU



def delete_cart(cart_id):
    """Elimina el carrito y sus items de la base de datos."""
    conn = None
    cur = None
    try:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM cart_items WHERE cart_id = %s", (cart_id,))
        cur.execute("DELETE FROM carts WHERE id = %s", (cart_id,))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error al eliminar el carrito: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if cur:
            cur.close()
        if conn:
            release_db(conn)

async def cart_delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Elimina el carrito seleccionado y muestra la lista actualizada de carritos."""
    query = update.callback_query
    await query.answer()
    try:
        cart_id = int(query.data.split("_")[2])
    except Exception as e:
        await query.edit_message_text("Error al procesar el carrito.")
        return CART_MENU
    if delete_cart(cart_id):
        await query.edit_message_text("Carrito eliminado correctamente.")
    else:
        await query.edit_message_text("Error al eliminar el carrito.")
    # Mostrar la lista actualizada de carritos
    return await show_carts_handler(update, context)

async def cart_pay_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Muestra el botón para pagar el carrito seleccionado."""
    query = update.callback_query
    await query.answer()
    try:
        cart_id = int(query.data.split("_")[2])
    except Exception as e:
        await query.edit_message_text("Error al procesar el carrito.")
        return CART_MENU
    context.user_data['selected_cart_id'] = cart_id
    cart_name, init_point = create_payment_preference_for_cart(cart_id)
    if not init_point:
        await query.edit_message_text("Error al crear la preferencia de pago.")
        return CART_MENU
    keyboard = [
        [InlineKeyboardButton("Pagar", url=init_point)],
        [InlineKeyboardButton("Volver al menú del carrito", callback_data=f"cartmenu_{cart_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = (f"Para pagar el carrito '{cart_name}', haga clic en 'Pagar'.\n"
           "El mensaje de confirmación se enviará cuando se complete el pago.")
    await query.edit_message_text(msg, reply_markup=reply_markup)
    return CART_MENU


def get_user_carts(telegram_id):
    """Obtiene la lista de carritos del usuario."""
    conn = None
    cur = None
    try:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("SELECT id, name, total FROM carts WHERE telegram_id = %s", (telegram_id,))
        rows = cur.fetchall()
        carts = []
        for row in rows:
            carts.append({'id': row[0], 'name': row[1], 'total': float(row[2])})
        return carts
    except Exception as e:
        logger.error(f"Error al obtener carritos: {e}")
        return []
    finally:
        if cur: cur.close()
        if conn: release_db(conn)

def get_cart_details(cart_id):
    """Obtiene los detalles de los items del carrito, incluyendo el id del producto."""
    conn = None
    cur = None
    try:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT p.id, p.name, ci.quantity, ci.subtotal
            FROM cart_items ci
            JOIN products p ON ci.product_id = p.id
            WHERE ci.cart_id = %s
        """, (cart_id,))
        rows = cur.fetchall()
        items = []
        for row in rows:
            items.append({
                'product_id': row[0],
                'name': row[1],
                'quantity': float(row[2]),
                'subtotal': float(row[3])
            })
        return items
    except Exception as e:
        logger.error(f"Error al obtener detalles del carrito: {e}")
        return []
    finally:
        if cur:
            cur.close()
        if conn:
            release_db(conn)


def get_user_info(telegram_id):
    """Obtiene el nombre y dirección del usuario."""
    conn = None
    cur = None
    try:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("SELECT name, address FROM users WHERE telegram_id = %s", (telegram_id,))
        row = cur.fetchone()
        if row:
            return {'name': row[0], 'address': row[1]}
        else:
            return None
    except Exception as e:
        logger.error(f"Error al obtener info del usuario: {e}")
        return None
    finally:
        if cur: cur.close()
        if conn: release_db(conn)

async def send_order_notifications(cart_id, confirmation_code, context, user_id):
    """
    Envía un mensaje con los datos del pedido a:
      - El usuario (user_id)
      - El administrador (ADMIN_CHAT_ID)
      - El proveedor (PROVIDER_CHAT_ID)
    """
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    items = get_cart_details(cart_id)  # Ya definida en tu código previamente
    items_text = ""
    for item in items:
        items_text += f"<b>{item['name']}</b>: {item['quantity']} = {item['subtotal']:.2f}\n\n"
    user_info = get_user_info_cached(user_id)  # Ya definida en tu código
    if user_info is None:
        user_info = {"name": "Desconocido", "address": "Desconocida"}
    message = (
        f"Fecha y Hora del pedido: <b>{now}</b>\n\n"
        f"Artículos:\n{items_text}\n"
        f"Cliente:\n"
        f"Nombre: <b>{user_info['name']}</b>\n"
        f"Dirección: <b>{user_info['address']}</b>\n\n"
        f"Código de Confirmación: <b>{confirmation_code}</b>\n\n"
        f"El pedido se llevará a la dirección proporcionada.\n\n"
        f"Escriba /start para abrir el menu principal"
    )
    await context.bot.send_message(chat_id=user_id, text=message, parse_mode="HTML")
    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=message, parse_mode="HTML")
    await context.bot.send_message(chat_id=PROVIDER_CHAT_ID, text=message, parse_mode="HTML")


def add_product_to_cart(cart_id, product, quantity):
    """
    Agrega un producto a un carrito.
    Calcula el subtotal y actualiza el total del carrito.
    Retorna: (total_anterior, subtotal, nuevo_total)
    """
    conn = None
    cur = None
    try:
        # Calcular subtotal según el tipo de venta
        if product['sale_type'] == 'unidad':
            subtotal = quantity * float(product['price'])
        else:
            # Se asume que 'price' es por 100 gramos y 'quantity' se ingresa en gramos
            subtotal = quantity * float(product['price']) / 100

        conn = connect_db()
        cur = conn.cursor()
        # Obtener el total actual del carrito
        cur.execute("SELECT total FROM carts WHERE id = %s", (cart_id,))
        row = cur.fetchone()
        if row is None:
            raise Exception("Carrito no encontrado")
        total_anterior = float(row[0])
        nuevo_total = total_anterior + subtotal

        # Insertar el producto en la tabla de items del carrito
        cur.execute(
            "INSERT INTO cart_items (cart_id, product_id, quantity, subtotal) VALUES (%s, %s, %s, %s)",
            (cart_id, product['id'], quantity, subtotal)
        )
        # Actualizar el total del carrito
        cur.execute("UPDATE carts SET total = %s WHERE id = %s", (nuevo_total, cart_id))
        conn.commit()
        return total_anterior, subtotal, nuevo_total
    except Exception as e:
        logger.error(f"Error al agregar producto al carrito: {e}")
        if conn:
            conn.rollback()
        return None, None, None
    finally:
        if cur: cur.close()
        if conn: release_db(conn)

def create_new_cart(telegram_id, cart_name):
    """
    Crea un nuevo carrito para el usuario.
    Retorna el id del carrito creado.
    """
    conn = None
    cur = None
    try:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO carts (telegram_id, name, total) VALUES (%s, %s, %s) RETURNING id",
            (telegram_id, cart_name, 0)
        )
        cart_id = cur.fetchone()[0]
        conn.commit()
        return cart_id
    except Exception as e:
        logger.error(f"Error al crear nuevo carrito: {e}")
        if conn:
            conn.rollback()
        return None
    finally:
        if cur: cur.close()
        if conn: release_db(conn)



def get_products():
    """Obtiene la lista de productos de la base de datos."""
    conn = None
    cur = None
    try:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("SELECT id, name, price, sale_type FROM products")
        products = cur.fetchall()
        product_list = []
        for row in products:
            product_list.append({
                'id': row[0],
                'name': row[1],
                'price': row[2],
                'sale_type': row[3]
            })
        return product_list
    except Exception as e:
        logger.error(f"Error al obtener productos: {e}")
        return []
    finally:
        if cur: cur.close()
        if conn: release_db(conn)

def get_product(product_id):
    """Obtiene los datos de un producto específico."""
    conn = None
    cur = None
    try:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("SELECT id, name, price, sale_type FROM products WHERE id = %s", (product_id,))
        row = cur.fetchone()
        if row:
            return {'id': row[0], 'name': row[1], 'price': row[2], 'sale_type': row[3]}
        else:
            return None
    except Exception as e:
        logger.error(f"Error al obtener producto: {e}")
        return None
    finally:
        if cur: cur.close()
        if conn: release_db(conn)

# ----------------- HANDLERS -----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Comando /start recibido de usuario %s", update.effective_user.id)
    telegram_id = update.effective_user.id

    # Consultar si el usuario está registrado
    try:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
        user = cur.fetchone()
        logger.info("Resultado de consulta para usuario %s: %s", telegram_id, user)
    except Exception as e:
        logger.exception("Error al consultar la base de datos")
        await update.message.reply_text("Error al conectar a la base de datos.")
        return ConversationHandler.END
    finally:
        if cur:
            cur.close()
        if conn:
            release_db(conn)

    # Si el usuario no está registrado, solicita el nombre
    if not user:
        logger.info("Usuario no registrado, pidiendo nombre")
        await update.message.reply_text("Bienvenido. Para comenzar, ingresa tu nombre:")
        return NAME

    # Si el usuario ya está registrado, envía el menú principal
    logger.info("Usuario registrado, enviando menú principal")
    keyboard = [
        [InlineKeyboardButton("Ordenar", callback_data="menu_ordenar")],
        [InlineKeyboardButton("Historial", callback_data="menu_historial")],
        [InlineKeyboardButton("Pedidos Pendientes", callback_data="menu_pedidos")],
        [InlineKeyboardButton("Carritos", callback_data="menu_carritos")],
        [InlineKeyboardButton("Cambiar Dirección", callback_data="menu_cambiar")],
        [InlineKeyboardButton("Contacto", callback_data="menu_contacto")],
        [InlineKeyboardButton("Ayuda", callback_data="menu_ayuda")]
    ]
    if telegram_id in allowed_ids:
        keyboard.append([InlineKeyboardButton("Gestión de Pedidos y Equipos", callback_data="gestion_pedidos")])
    if es_trabajador(telegram_id):
        keyboard.append([InlineKeyboardButton("Gestión de Pedidos", callback_data="gestion_pedidos_personal")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Enviar un mensaje de prueba adicional para confirmar el envío
    try:
        await update.message.reply_text("Enviando mensaje de prueba...", reply_markup=reply_markup)
        logger.info("Mensaje de prueba enviado correctamente")
    except Exception as e:
        logger.exception("Error al enviar el mensaje de prueba")
    
    return MAIN_MENU



async def name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Solicita y guarda el nombre para el registro."""
    name = update.message.text
    context.user_data['name'] = name
    await update.message.reply_text(
        "Gracias. Ahora, ingresa tu dirección. A esta dirección se enviarán los pedidos y podrás cambiarla después si quieres:"
    )
    return ADDRESS

async def address_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Guarda la dirección en la base de datos y muestra el menú principal."""
    address = update.message.text
    name = context.user_data.get('name')
    telegram_id = update.effective_user.id

    conn = None
    cur = None
    try:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (telegram_id, name, address) VALUES (%s, %s, %s)",
            (telegram_id, name, address)
        )
        conn.commit()
        await update.message.reply_text("Registro exitoso.")
    except Exception as e:
        logger.error(f"Error al registrar el usuario: {e}")
        await update.message.reply_text("Fallo al registrar el usuario.")
    finally:
        if cur: cur.close()
        if conn: release_db(conn)

    # Mostrar menú principal tras el registro
    keyboard = [
        [InlineKeyboardButton("Ordenar", callback_data="menu_ordenar")],
        [InlineKeyboardButton("Historial", callback_data="menu_historial")],
        [InlineKeyboardButton("Pedidos Pendientes", callback_data="menu_pedidos")],
        [InlineKeyboardButton("Carritos", callback_data="menu_carritos")],
        [InlineKeyboardButton("Cambiar Direccion", callback_data="menu_cambiar")],
        [InlineKeyboardButton("Contacto", callback_data="menu_contacto")],
        [InlineKeyboardButton("Ayuda", callback_data="menu_ayuda")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Menú Principal:", reply_markup=reply_markup)
    return MAIN_MENU


# Dentro de la función main_menu_handler, agrega las nuevas opciones.
async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    logger.info(f"main_menu_handler invoked with data: {data}")
    user_id = query.from_user.id

    if data == "menu_ordenar":
        context.user_data["origin"] = "ordenar"
        products = get_products()
        if not products:
            await query.edit_message_text("No hay productos disponibles.")
            return MAIN_MENU
        keyboard = []
        for product in products:
            keyboard.append([InlineKeyboardButton(product['name'], callback_data=f"product_{product['id']}")])
        keyboard.append([InlineKeyboardButton("Volver", callback_data="menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Seleccione un producto:", reply_markup=reply_markup)
        return ORDERING

    elif data == "menu_historial":
        return await show_history_handler(update, context)

    elif data == "menu_pedidos":
        return await pending_orders_handler(update, context)

    elif data == "menu_carritos":
        context.user_data["origin"] = "carrito"
        return await show_carts_handler(update, context)

    elif data == "menu_cambiar":
        return await cambiar_direccion_handler(update, context)

    elif data == "menu_contacto":
        return await contacto_handler(update, context)

    elif data == "menu_ayuda":
        return await ayuda_handler(update, context)

    elif data == "gestion_pedidos":
        return await gestion_pedidos_handler(update, context)

    elif data == "gestion_pedidos_personal":
        return await gestion_pedidos_personal_handler(update, context)

    elif data in ["back_main", "menu"]:
        keyboard = [
            [InlineKeyboardButton("Ordenar", callback_data="menu_ordenar")],
            [InlineKeyboardButton("Historial", callback_data="menu_historial")],
            [InlineKeyboardButton("Pedidos Pendientes", callback_data="menu_pedidos")],
            [InlineKeyboardButton("Carritos", callback_data="menu_carritos")],
            [InlineKeyboardButton("Cambiar Dirección", callback_data="menu_cambiar")],
            [InlineKeyboardButton("Contacto", callback_data="menu_contacto")],
            [InlineKeyboardButton("Ayuda", callback_data="menu_ayuda")]
        ]
        if user_id in allowed_ids:
            keyboard.append([InlineKeyboardButton("Gestión de Pedidos y Equipos", callback_data="gestion_pedidos")])
        if es_trabajador(user_id):
            keyboard.append([InlineKeyboardButton("Gestión de Pedidos", callback_data="gestion_pedidos_personal")])
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        rand_val = random.randint(0, 9999)
        new_text = f"Menú Principal: {now} - {rand_val}"
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.edit_message_text(new_text, reply_markup=reply_markup)
        except BadRequest as e:
            if "Message is not modified" in str(e):
                logger.info("El mensaje ya tenía ese contenido. Se ignora el error.")
            else:
                raise e
        return MAIN_MENU

    else:
        await query.edit_message_text("Opción no implementada aún.")
        return MAIN_MENU
    
async def cancelar_cambio_direccion_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Cancela el cambio de dirección y regresa al menú principal.
    """
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("Aceptar", callback_data="back_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Cambio de dirección cancelado.", reply_markup=reply_markup)
    return MAIN_MENU


# 1. Agrega la siguiente función (por ejemplo, justo después de las otras funciones de gestión de conjuntos):

async def asignar_conjuntos_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    conjuntos = get_all_conjuntos()  # Esta función obtiene la lista de conjuntos
    if not conjuntos:
        await query.edit_message_text("No existen conjuntos creados.")
        return GESTION_PEDIDOS

    buttons = []
    for c in conjuntos:
        equipo_text = "Sin equipo asignado"
        if c["equipo_id"] is not None:
            equipo_info = get_equipo_info(c["equipo_id"])
            if equipo_info:
                equipo_text = f"Equipo {equipo_info['id']} ({equipo_info['trabajador1']} y {equipo_info['trabajador2']})"
        btn_text = f"Conjunto {c['numero']}: {c['pendientes']} pendientes, {equipo_text}"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"select_conjunto_{c['id']}")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text("Seleccione un conjunto para asignar:", reply_markup=reply_markup)
    
    # Retornamos SELECCIONAR_EQUIPO para que el handler de "select_conjunto_\\d+" se active
    return SELECCIONAR_EQUIPO


async def revocar_conjuntos_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_text("Funcionalidad de Revocar Conjuntos en construcción.")
    except Exception as e:
        if "Message is not modified" in str(e):
            pass
        else:
            raise e
    return GESTION_PEDIDOS

async def ver_equipos_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_text("Funcionalidad de Ver Equipos en construcción.")
    except Exception as e:
        if "Message is not modified" in str(e):
            pass
        else:
            raise e
    return GESTION_PEDIDOS

async def crear_nuevo_equipo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_text("Funcionalidad de Crear Nuevo Equipo en construcción.")
    except Exception as e:
        if "Message is not modified" in str(e):
            pass
        else:
            raise e
    return GESTION_PEDIDOS

async def contacto_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Muestra la información de contacto de la verdulería y un botón para volver al menú principal.
    """
    query = update.callback_query
    await query.answer()
    # Mensaje de ejemplo (modifícalo con la información real)
    mensaje = (
        "📞 *Contacto Verdulería Online*\n\n"
        "Teléfono: +1 234 567 890\n"
        "Email: contacto@verduleriaonline.com\n"
        "Dirección: Calle Falsa 123, Ciudad Ejemplo\n\n"
        "Para más información, visita nuestro sitio web: https://www.verduleriaonline.com"
    )
    keyboard = [[InlineKeyboardButton("Volver al Menú Principal", callback_data="back_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text=mensaje, reply_markup=reply_markup, parse_mode="Markdown")
    return MAIN_MENU

async def ayuda_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Muestra un tutorial de uso del bot y un botón para volver al menú principal.
    """
    query = update.callback_query
    await query.answer()
    # Mensaje de ejemplo (modifícalo con el tutorial deseado)
    mensaje = (
        "A continuacion se explican las funciones del bot\n\n"
        "El boton Ordenar, mostrara una lista de productos que podra seleccionar para agregar a un carrito, debera ingresar cuanto de ese producto quiere y agregarlo a un carrito existente o a uno nuevo que cree durante el proceso. Al finalizar, podra agregar mas productos, volver al menu principal o pagar el carrito, lo que enviara una notificacion al personal de la verduleria para que se realize una entrega a la direccion que proporciono al registrarse.\n\n"
        "El boton Historial, mostrara los ultimos 20 pedidos entregdos exitosamente.\n\n"
        "El boton Pedidos Pendientes, mostrara los ultimos 20 pedidos que esten pendientes de ser entregados.\n\n"
        "El boton Carritos mostrara sus carritos, y al clickear uno, podra elegir entre ver los productos que ya tiene el carrito, agregar productos a ese carrito, quitarlos y eliminar el carrito.\n\n"
        "El boton Cambiar Direccion, le permitira actualizar la direccion asociada a su cuenta.\n\n"
        "El boton Contacto le mostrara una serie de datos de contacto de la verduleria.\n\n"
    )
    keyboard = [[InlineKeyboardButton("Volver al Menú Principal", callback_data="back_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text=mensaje, reply_markup=reply_markup, parse_mode="Markdown")
    return MAIN_MENU


async def gestion_pedidos_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("Asignar Conjuntos", callback_data="asignar_conjuntos")],
        [InlineKeyboardButton("Revocar Conjuntos", callback_data="revocar_conjuntos")],
        [InlineKeyboardButton("Ver Equipos", callback_data="ver_equipos")],
        [InlineKeyboardButton("Crear Nuevo Equipo", callback_data="crear_nuevo_equipo")],
        [InlineKeyboardButton("Eliminar Equipos", callback_data="eliminar_equipos")],
        [InlineKeyboardButton("Ver Conjuntos No Terminados", callback_data="ver_conjuntos_no_terminados")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Gestión de Pedidos y Equipos:", reply_markup=reply_markup)
    return GESTION_PEDIDOS

#########################################
# NUEVAS FUNCIONES PARA ASIGNAR CONJUNTOS
#########################################

def get_all_conjuntos():
    """
    Retorna una lista de conjuntos que NO están asignados a ningún equipo,
    cada uno con su id, número de conjunto, cantidad de pedidos pendientes y 'equipo_id' (que será None).
    """
    conn = connect_db()
    cur = conn.cursor()
    # Filtramos los conjuntos que no tengan asignado un equipo (equipo_id IS NULL)
    cur.execute("SELECT id, numero_conjunto FROM conjuntos WHERE equipo_id IS NULL")
    conjuntos = cur.fetchall()
    cur.close()
    release_db(conn)
    conjuntos_list = []
    for row in conjuntos:
        conjunto_id, numero_conjunto = row
        pendientes = count_pending_orders_in_conjunto(conjunto_id)
        conjuntos_list.append({
            "id": conjunto_id,
            "numero": numero_conjunto,
            "pendientes": pendientes,
            "equipo_id": None  # Agregamos explícitamente este valor para evitar KeyError
        })
    conjuntos_list.sort(key=lambda c: c["pendientes"])
    return conjuntos_list


def get_all_equipos():
    """
    Retorna una lista de equipos con sus datos y la información de los integrantes
    (nombres en lugar de IDs) obtenida mediante get_equipo_info.
    """
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM equipos")
    equipos = cur.fetchall()
    cur.close()
    release_db(conn)
    equipos_list = []
    for row in equipos:
        equipo_id = row[0]
        info = get_equipo_info(equipo_id)
        # Para este ejemplo, asignamos 0 pedidos pendientes; actualiza según tu lógica
        pendientes = 0  
        equipos_list.append({
            "id": equipo_id,
            "pendientes": pendientes,
            "info": info  # Diccionario con nombres de integrantes
        })
    equipos_list.sort(key=lambda e: e["pendientes"])
    return equipos_list


def assign_conjunto_to_equipo(conjunto_id, equipo_id):
    """
    Asigna el conjunto al equipo actualizando la columna equipo_id en la tabla conjuntos.
    """
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("UPDATE conjuntos SET equipo_id = %s WHERE id = %s", (equipo_id, conjunto_id))
    conn.commit()
    cur.close()
    release_db(conn)
    return True

#########################################
# HANDLERS PARA ASIGNAR CONJUNTOS
#########################################

async def asignar_conjuntos_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Muestra los conjuntos existentes (ordenados por pedidos pendientes ascendente)
    en botones inline. Cada botón muestra: "Conjunto {numero}: {pendientes} pendientes, Equipo: {equipo_info}".
    Se solicita al usuario que seleccione un conjunto para asignar.
    """
    query = update.callback_query
    await query.answer()
    # Obtenemos todos los conjuntos
    conjuntos = get_all_conjuntos()  # Asegúrate de que esta función devuelva registros
    if not conjuntos:
        await query.edit_message_text("No existen conjuntos creados.")
        return GESTION_PEDIDOS

    buttons = []
    for c in conjuntos:
        equipo_text = "Sin equipo asignado"
        if c["equipo_id"] is not None:
            equipo_info = get_equipo_info(c["equipo_id"])
            if equipo_info:
                equipo_text = f"Equipo {equipo_info['id']} ({equipo_info['trabajador1']} y {equipo_info['trabajador2']})"
        btn_text = f"Conjunto {c['numero']}: {c['pendientes']} pendientes, {equipo_text}"
        # El callback_data debe coincidir con el patrón "^select_conjunto_\d+$"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"select_conjunto_{c['id']}")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text("Seleccione un conjunto para asignar:", reply_markup=reply_markup)
    # Retornamos el estado SELECCIONAR_EQUIPO para que se active el handler correspondiente
    return SELECCIONAR_EQUIPO

async def select_conjunto_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Cuando se selecciona un conjunto, se verifica si ya tiene asignado un equipo y 
    se muestran los equipos disponibles (con los nombres de los integrantes) para asignarlo.
    """
    query = update.callback_query
    await query.answer()
    try:
        # Se espera que el callback_data tenga el formato "select_conjunto_{id}"
        parts = query.data.split("_")
        conjunto_id = int(parts[2])
    except Exception as e:
        logger.error(f"Error al procesar el conjunto seleccionado: {e}")
        await query.edit_message_text("Error al procesar el conjunto seleccionado.")
        return SELECCIONAR_EQUIPO

    # Consultamos el conjunto para ver si ya tiene asignado un equipo
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT equipo_id, numero_conjunto FROM conjuntos WHERE id = %s", (conjunto_id,))
    row = cur.fetchone()
    cur.close()
    release_db(conn)
    if not row:
        await query.edit_message_text("Conjunto no encontrado.")
        return SELECCIONAR_EQUIPO
    equipo_id, num_conjunto = row
    if equipo_id:
        equipo_info = get_equipo_info(equipo_id)
        if equipo_info:
            info = f"{equipo_info['trabajador1']} y {equipo_info['trabajador2']}"
        else:
            info = "equipo desconocido"
    else:
        info = "sin equipo asignado"

    await query.edit_message_text(
        f"Ha seleccionado el Conjunto {num_conjunto} ({info}).\n\nAhora, seleccione un equipo para asignarlo:"
    )

    # Mostramos la lista de equipos disponibles (se asume que get_all_equipos utiliza get_equipo_info)
    equipos = get_all_equipos()  # Esta función debe devolver cada equipo con un campo "info" con los nombres.
    if not equipos:
        await query.edit_message_text("No existen equipos creados.")
        return SELECCIONAR_EQUIPO

    equipo_buttons = []
    for equipo in equipos:
        eq_info = equipo["info"]
        # Mostramos solo los nombres de los integrantes, sin el ID
        btn_text = f"{eq_info['trabajador1']} y {eq_info['trabajador2']} (Pendientes: {equipo['pendientes']})"
        # Se utiliza el id del equipo para el callback
        equipo_buttons.append([InlineKeyboardButton(btn_text, callback_data=f"asignar_{conjunto_id}_equipo_{equipo['id']}")])
    reply_markup = InlineKeyboardMarkup(equipo_buttons)
    await query.edit_message_text("Seleccione el equipo al cual asignar el conjunto:", reply_markup=reply_markup)
    context.user_data['selected_conjunto_id'] = conjunto_id
    return SELECCIONAR_EQUIPO



async def asignar_equipo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Una vez seleccionado un equipo, asigna el conjunto al equipo (actualizando la columna equipo_id en la tabla conjuntos)
    y notifica al usuario.
    """
    query = update.callback_query
    await query.answer()
    logger.info(f"asignar_equipo_handler triggered with data: {query.data}")
    try:
        # Se espera el callback_data con formato "asignar_{conjunto_id}_equipo_{equipo_id}"
        parts = query.data.split("_")
        conjunto_id = int(parts[1])
        equipo_id = int(parts[3])
    except Exception as e:
        logger.error(f"Error al procesar la selección del equipo: {e}")
        await query.edit_message_text("Error al procesar la selección del equipo.")
        return SELECCIONAR_EQUIPO

    # Asignamos el conjunto al equipo
    assign_conjunto_to_equipo(conjunto_id, equipo_id)
    equipo_info = get_equipo_info(equipo_id)
    if equipo_info:
        await query.edit_message_text(f"Conjunto asignado exitosamente al Equipo {equipo_info['id']} ({equipo_info['trabajador1']} y {equipo_info['trabajador2']}).")
    else:
        await query.edit_message_text("Conjunto asignado, pero no se pudo obtener la información del equipo.")
    return MAIN_MENU
    
#########################################
# REGISTRO DE LOS NUEVOS HANDLERS EN EL CONVERSATIONHANDLER
#########################################

# Cuando configures el ConversationHandler, asegúrate de agregar los nuevos estados y sus handlers.
# Por ejemplo, en el diccionario de estados:
#
# {
#   ...,
#   GESTION_PEDIDOS: [CallbackQueryHandler(gestion_pedidos_handler, pattern="^gestion_pedidos$")],
#   ASIGNAR_CONJUNTOS: [CallbackQueryHandler(asignar_conjuntos_handler, pattern="^asignar_conjuntos$")],
#   SELECCIONAR_EQUIPO: [CallbackQueryHandler(select_conjunto_handler, pattern="^select_conjunto_\\d+$"),
#                        CallbackQueryHandler(asignar_equipo_handler, pattern="^asignar_\\d+_equipo_\\d+$")],
#   REVOCAR_CONJUNTOS: [CallbackQueryHandler(revocar_conjuntos_handler, pattern="^revocar_conjuntos$")],
#   VER_EQUIPOS: [CallbackQueryHandler(ver_equipos_handler, pattern="^ver_equipos$")],
#   CREAR_NUEVO_EQUIPO: [CallbackQueryHandler(crear_nuevo_equipo_handler, pattern="^crear_nuevo_equipo$")],
#   ...
# }
#
# Asegúrate de que estos estados (GESTION_PEDIDOS, ASIGNAR_CONJUNTOS, SELECCIONAR_EQUIPO, etc.) estén definidos y no colisionen con los existentes.


async def product_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Manejador cuando se selecciona un producto o se pulsa 'Volver'."""
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("product_"):
        product_id = data.split("_")[1]
        product = get_product(product_id)
        if not product:
            await query.edit_message_text("Producto no encontrado.")
            return ORDERING
        # Guardamos el producto seleccionado para usarlo en la siguiente etapa
        context.user_data['selected_product'] = product
        # Mostrar precio según tipo de venta
        if product['sale_type'] == 'unidad':
            price_text = f"Precio por unidad: {product['price']}"
        else:
            price_text = f"Precio por 100 gramos: {product['price']}"
        await query.edit_message_text(
            f"{product['name']}\n{price_text}\n\n¿Cuánto desea agregar?"
        )
        return ASK_QUANTITY
    elif data == "menu":
        # Construir el menú principal y regresar a él
        keyboard = [
            [InlineKeyboardButton("Ordenar", callback_data="menu_ordenar")],
            [InlineKeyboardButton("Historial", callback_data="menu_historial")],
            [InlineKeyboardButton("Pedidos Pendientes", callback_data="menu_pedidos")],
            [InlineKeyboardButton("Carritos", callback_data="menu_carritos")],
            [InlineKeyboardButton("Cambiar Direccion", callback_data="menu_cambiar")],
            [InlineKeyboardButton("Contacto", callback_data="menu_contacto")],
        [   InlineKeyboardButton("Ayuda", callback_data="menu_ayuda")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Menú Principal:", reply_markup=reply_markup)
        return MAIN_MENU
    else:
        return MAIN_MENU


async def quantity_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    try:
        quantity = float(text)
    except ValueError:
        await update.message.reply_text("Por favor, ingresa un número válido.")
        return ASK_QUANTITY

    context.user_data['quantity'] = quantity
    product = context.user_data.get('selected_product')
    if not product:
        await update.message.reply_text("Error: Producto no seleccionado.")
        return ORDERING

    # Calcular subtotal
    if product['sale_type'] == 'unidad':
        subtotal = quantity * float(product['price'])
    else:
        subtotal = quantity * float(product['price']) / 100
    context.user_data['subtotal'] = subtotal

    # Si se inició desde "carritos", es que ya hay un carrito preseleccionado
    if context.user_data.get("origin") == "carrito" and 'selected_cart_id' in context.user_data:
        cart_id = context.user_data['selected_cart_id']
        total_anterior, sub, nuevo_total = add_product_to_cart(cart_id, product, quantity)
        if total_anterior is None:
            await update.message.reply_text("Error al agregar el producto al carrito.")
            return SELECT_CART
        keyboard = [
            [InlineKeyboardButton("Agregar más productos", callback_data="add_more")],
            [InlineKeyboardButton("Pagar Carrito", callback_data="pay_cart")],
            [InlineKeyboardButton("Volver al menú del carrito", callback_data=f"back_cart_{cart_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        msg = (f"Se agregó al carrito.\n"
               f"Total anterior: {total_anterior:.2f}\n"
               f"Subtotal: {sub:.2f}\n"
               f"Nuevo total: {nuevo_total:.2f}\n\n"
               "¿Qué desea hacer a continuación?")
        await update.message.reply_text(msg, reply_markup=reply_markup)
        return POST_ADHESION
    else:
        # Si se inició desde "ordenar", siempre se debe pedir seleccionar un carrito
        # (ignoramos cualquier 'selected_cart_id' que se tenga)
        context.user_data.pop('selected_cart_id', None)
        # Mostrar la lista de carritos para elegir
        telegram_id = update.effective_user.id
        carts = get_user_carts(telegram_id)
        keyboard = []
        for cart in carts:
            keyboard.append([InlineKeyboardButton(cart['name'], callback_data=f"select_cart_{cart['id']}")])
        keyboard.append([InlineKeyboardButton("Volver", callback_data="back_quantity")])
        keyboard.append([InlineKeyboardButton("Nuevo Carrito", callback_data="new_cart")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        msg = (f"Subtotal para {product['name']} ({quantity} " +
               ("unidades" if product['sale_type']=='unidad' else "gramos") +
               f"): {subtotal:.2f}\nElige uno de tus carritos para agregar el producto:")
        await update.message.reply_text(msg, reply_markup=reply_markup)
        return SELECT_CART


async def back_cart_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Manejador para volver al menú del carrito desde la lista de productos."""
    query = update.callback_query
    await query.answer()
    try:
        # Se espera que la callback_data tenga el formato "back_cart_{cart_id}"
        cart_id = int(query.data.split("_")[2])
    except Exception as e:
        await query.edit_message_text("Error al procesar el carrito.")
        return CART_MENU
    # Llama al menú del carrito usando la función ya definida
    return await cart_menu_handler(update, context)

def eliminar_equipo(equipo_id):
    """
    Función que elimina el equipo de la base de datos dado su ID.
    Retorna True si se eliminó correctamente, False en caso contrario.
    """
    conn = None
    cur = None
    try:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM equipos WHERE id = %s", (equipo_id,))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error al eliminar el equipo {equipo_id}: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if cur:
            cur.close()
        if conn:
            release_db(conn)

@admin_only
async def eliminar_equipo_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Maneja el comando para eliminar un equipo.
    Se espera que se invoque con el formato: /eliminar_equipo <equipo_id>
    Este handler funcionará tanto si se invoca desde un mensaje como desde un botón.
    """
    # Primero comprobamos si viene como mensaje (comando de texto)
    if update.message:
        args = update.message.text.split()[1:]
        if not args:
            await update.message.reply_text("Uso: /eliminar_equipo <equipo_id>")
            return ConversationHandler.END  # O el estado que corresponda
        equipo_id = args[0]
        # Aquí puedes agregar la lógica para eliminar el equipo (p.ej., llamar a una función eliminar_equipo(equipo_id))
        # Por ejemplo:
        resultado = eliminar_equipo(equipo_id)
        if resultado:
            await update.message.reply_text(f"Equipo {equipo_id} eliminado exitosamente.")
        else:
            await update.message.reply_text(f"Error al eliminar el equipo {equipo_id}.")
        return ConversationHandler.END

    # Si viene como callback query (desde un botón)
    elif update.callback_query:
        # Si se invoca desde un botón, lo ideal es mostrar las instrucciones o redirigir a la pantalla de eliminación.
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Uso: /eliminar_equipo <equipo_id>\n\nPor favor, envía el comando con el ID del equipo que deseas eliminar.")
        return ConversationHandler.END

    # Fallback
    else:
        return ConversationHandler.END

def get_conjuntos_no_terminados():
    """
    Retorna una lista de conjuntos que tienen al menos un pedido pendiente.
    Cada elemento es un diccionario con: id, numero y pendientes.
    """
    try:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("SELECT id, numero_conjunto FROM conjuntos")
        rows = cur.fetchall()
        cur.close()
        release_db(conn)
        conjuntos = []
        for row in rows:
            conjunto_id, numero = row
            pendientes = count_pending_orders_in_conjunto(conjunto_id)
            if pendientes > 0:
                conjuntos.append({"id": conjunto_id, "numero": numero, "pendientes": pendientes})
        return conjuntos
    except Exception as e:
        logger.error(f"Error al obtener conjuntos no terminados: {e}")
        return []

@admin_only
async def crear_equipo_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Comando para crear un nuevo equipo.
    Uso: /crear_equipo <id_trabajador1> <id_trabajador2>
    """
    try:
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("Uso: /crear_equipo <id_trabajador1> <id_trabajador2>")
            return MAIN_MENU
        id1 = int(args[0])
        id2 = int(args[1])
    except ValueError:
        await update.message.reply_text("Los IDs deben ser números.")
        return MAIN_MENU

    equipo_id = crear_nuevo_equipo_db(id1, id2)
    if equipo_id:
        await update.message.reply_text(f"Equipo creado exitosamente: Equipo {equipo_id} - {id1} y {id2}.")
    else:
        await update.message.reply_text("Error al crear el equipo.")
    return MAIN_MENU

def asignar_conjunto_por_numero(numero_conjunto: int, equipo_id: int) -> bool:
    """
    Asigna un conjunto (buscado por su número) al equipo especificado.
    Se actualiza el campo equipo_id en el conjunto cuyo número coincide.
    """
    try:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("UPDATE conjuntos SET equipo_id = %s WHERE numero_conjunto = %s", (equipo_id, numero_conjunto))
        conn.commit()
        cur.close()
        release_db(conn)
        return True
    except Exception as e:
        logger.error(f"Error al asignar conjunto: {e}")
        if conn:
            conn.rollback()
        return False

@admin_only
async def asignar_conjunto_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Comando para asignar un conjunto a un equipo.
    Uso: /asignar_conjunto <numero_conjunto> <id_equipo>
    """
    try:
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("Uso: /asignar_conjunto <numero_conjunto> <id_equipo>")
            return MAIN_MENU
        numero_conjunto = int(args[0])
        equipo_id = int(args[1])
    except ValueError:
        await update.message.reply_text("Los valores deben ser números.")
        return MAIN_MENU

    if asignar_conjunto_por_numero(numero_conjunto, equipo_id):
        await update.message.reply_text(f"Conjunto {numero_conjunto} asignado al Equipo {equipo_id} exitosamente.")
    else:
        await update.message.reply_text("Error al asignar el conjunto.")
    return MAIN_MENU

def revocar_conjunto_por_numero(numero_conjunto: int) -> bool:
    """
    Revoca (desasigna) un conjunto identificándolo por su número.
    Es decir, se pone a NULL el campo equipo_id para el conjunto cuyo número coincide.
    """
    try:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("UPDATE conjuntos SET equipo_id = NULL WHERE numero_conjunto = %s", (numero_conjunto,))
        conn.commit()
        cur.close()
        release_db(conn)
        return True
    except Exception as e:
        logger.error(f"Error al revocar conjunto: {e}")
        if conn:
            conn.rollback()
        return False

@admin_only
async def revocar_conjunto_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Comando para revocar un conjunto (desasignarlo de un equipo) por su número.
    Uso: /revocar_conjunto <numero_conjunto>
    """
    try:
        args = context.args
        if len(args) < 1:
            await update.message.reply_text("Uso: /revocar_conjunto <numero_conjunto>")
            return MAIN_MENU
        numero_conjunto = int(args[0])
    except ValueError:
        await update.message.reply_text("El número del conjunto debe ser un número.")
        return MAIN_MENU

    if revocar_conjunto_por_numero(numero_conjunto):
        await update.message.reply_text(f"Conjunto {numero_conjunto} revocado exitosamente.")
    else:
        await update.message.reply_text("Error al revocar el conjunto.")
    return MAIN_MENU

@admin_only
async def ver_conjuntos_no_terminados_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Muestra una lista de todos los conjuntos no terminados (con pedidos pendientes).
    Al presionar uno se descargará el PDF correspondiente.
    """
    query = update.callback_query
    await query.answer()
    conjuntos = get_conjuntos_no_terminados()
    if not conjuntos:
        await query.edit_message_text("No hay conjuntos no terminados.")
        return GESTION_PEDIDOS
    buttons = []
    for c in conjuntos:
        btn_text = f"Conjunto {c['numero']} - {c['pendientes']} pendientes"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"descargar_conjunto_{c['id']}")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text("Seleccione un conjunto no terminado para descargar su PDF:", reply_markup=reply_markup)
    # Retornamos el estado VER_EQUIPOS para que el handler 'descargar_conjunto_handler'
    # (registrado para pattern "^descargar_conjunto_\\d+$") se active.
    return VER_EQUIPOS


async def cart_selection_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Manejador para la selección de un carrito o acción relacionada."""
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("select_cart_"):
        cart_id = int(data.split("_")[-1])
        product = context.user_data.get('selected_product')
        quantity = context.user_data.get('quantity')
        if not product or quantity is None:
            await query.edit_message_text("Error: Falta información del producto o cantidad.")
            return ASK_QUANTITY
        # Agregar el producto al carrito seleccionado
        total_anterior, subtotal, nuevo_total = add_product_to_cart(cart_id, product, quantity)
        if total_anterior is None:
            await query.edit_message_text("Error al agregar el producto al carrito.")
            return SELECT_CART
        # Guardar el carrito seleccionado para usarlo en el pago
        context.user_data['selected_cart_id'] = cart_id
        # Configurar el botón "Volver":
        # Si el proceso se inició desde un carrito específico (origin == "carrito"), se muestra "Volver al menú del carrito".
        # De lo contrario, se muestra "Volver al Menú Principal".
        if context.user_data.get("origin") == "carrito":
            back_button = InlineKeyboardButton("Volver al menú del carrito", callback_data=f"back_cart_{cart_id}")
        else:
            back_button = InlineKeyboardButton("Volver al Menú Principal", callback_data="back_main")
        keyboard = [
            [InlineKeyboardButton("Agregar más Productos", callback_data="add_more")],
            [InlineKeyboardButton("Pagar Carrito", callback_data="pay_cart")],
            [back_button]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        msg = (f"Se agregó al carrito.\n"
               f"Total anterior: {total_anterior:.2f}\n"
               f"Subtotal de la adhesión: {subtotal:.2f}\n"
               f"Nuevo total: {nuevo_total:.2f}\n\n"
               f"¿Qué desea hacer a continuación?\n\n"
               f"Tenga en cuenta que si realiza el pago fuera del horario de atencion, el mismo se entregar durante la siguiente jornada laboral")
        await query.edit_message_text(msg, reply_markup=reply_markup)
        return POST_ADHESION
    elif data == "back_quantity":
        # Volver a la pantalla para ingresar la cantidad
        product = context.user_data.get('selected_product')
        if not product:
            await query.edit_message_text("Error: Producto no seleccionado.")
            return ORDERING
        await query.edit_message_text(
            f"{product['name']}\n"
            f"{'Precio por unidad: ' + str(product['price']) if product['sale_type'] == 'unidad' else 'Precio por 100 gramos: ' + str(product['price'])}\n\n"
            "¿Cuánto desea agregar?"
        )
        return ASK_QUANTITY
    elif data == "new_cart":
        # Solicitar el nombre del nuevo carrito
        await query.edit_message_text("Ingrese el nombre del nuevo carrito:")
        return NEW_CART
    else:
        return SELECT_CART

def get_equipo_info(equipo_id):
    """
    Retorna un diccionario con los nombres de los integrantes del equipo,
    consultando la tabla "trabajadores" usando el telegram_id de cada integrante.
    Si no se encuentra la información, devuelve "N/D".
    """
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT trabajador1, trabajador2 FROM equipos WHERE id = %s", (equipo_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        release_db(conn)
        return None
    t1, t2 = row
    # Obtener nombres de los trabajadores
    cur.execute("SELECT nombre FROM trabajadores WHERE telegram_id = %s", (t1,))
    nombre1 = cur.fetchone()
    cur.execute("SELECT nombre FROM trabajadores WHERE telegram_id = %s", (t2,))
    nombre2 = cur.fetchone()
    cur.close()
    release_db(conn)
    return {
        "trabajador1": nombre1[0] if nombre1 else "N/D",
        "trabajador2": nombre2[0] if nombre2 else "N/D"
    }



# Función auxiliar para obtener los conjuntos asignados a un equipo
def get_conjuntos_by_equipo(equipo_id):
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT id, numero_conjunto FROM conjuntos WHERE equipo_id = %s", (equipo_id,))
    rows = cur.fetchall()
    cur.close()
    release_db(conn)
    conjuntos = []
    for row in rows:
        conjunto_id, numero_conjunto = row
        pendientes = count_pending_orders_in_conjunto(conjunto_id)
        conjuntos.append({
            "id": conjunto_id,
            "numero": numero_conjunto,
            "pendientes": pendientes
        })
    # Ordenar de menos a más pendientes
    conjuntos.sort(key=lambda c: c["pendientes"])
    return conjuntos

# Función auxiliar para obtener todos los equipos que tienen al menos un conjunto asignado
def get_all_equipos_revocar():
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT id, trabajador1, trabajador2 FROM equipos")
    equipos = cur.fetchall()
    cur.close()
    release_db(conn)
    equipos_list = []
    for row in equipos:
        equipo_id, t1, t2 = row
        conjuntos = get_conjuntos_by_equipo(equipo_id)
        if conjuntos:  # Solo se incluyen equipos que tienen conjuntos asignados
            equipos_list.append({
                "id": equipo_id,
                "trabajador1": t1,
                "trabajador2": t2,
                "conjuntos": conjuntos
            })
    return equipos_list

def get_next_available_conjunto_number():
    """
    Retorna el menor número entero positivo que NO está siendo usado en la tabla 'conjuntos'.
    Esto permite reutilizar números liberados cuando se elimina un conjunto.
    """
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT numero_conjunto FROM conjuntos ORDER BY numero_conjunto")
    rows = cur.fetchall()
    cur.close()
    release_db(conn)
    used_numbers = {row[0] for row in rows}
    n = 1
    while n in used_numbers:
        n += 1
    return n

# Handler inicial para revocar conjuntos: muestra, para cada equipo, un mensaje con sus conjuntos asignados.
async def revocar_conjuntos_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    equipos = get_all_equipos_revocar()
    if not equipos:
        await query.edit_message_text("No existen equipos con conjuntos asignados.")
        return GESTION_PEDIDOS
    message = "Equipos con conjuntos asignados:\n\n"
    buttons = []
    for equipo in equipos:
        # Obtenemos la información del equipo (por ejemplo, usando la función get_equipo_info ya existente)
        equipo_info = get_equipo_info(equipo["id"])
        equipo_text = f"Equipo {equipo_info['id']} ({equipo_info['trabajador1']} y {equipo_info['trabajador2']})"
        conjunto_texts = []
        for c in equipo["conjuntos"]:
            conjunto_texts.append(f"Conjunto {c['numero']} ({c['pendientes']} pendientes)")
        conjuntos_str = ", ".join(conjunto_texts)
        message += f"{equipo_text}: {conjuntos_str}\n"
        # Botón para seleccionar este equipo (callback: "revocar_equipo_<equipo_id>")
        buttons.append([InlineKeyboardButton(equipo_text, callback_data=f"revocar_equipo_{equipo_info['id']}")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text(message, reply_markup=reply_markup)
    return REVOCAR_CONJUNTOS

# Handler que se activa al pulsar un botón "revocar_equipo_<equipo_id>" y muestra los conjuntos asignados a ese equipo.
async def select_equipo_revocar_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    try:
        equipo_id = int(query.data.split("_")[2])
    except Exception as e:
        await query.edit_message_text("Error al procesar el equipo seleccionado.")
        return REVOCAR_CONJUNTOS
    conjuntos = get_conjuntos_by_equipo(equipo_id)
    if not conjuntos:
        await query.edit_message_text("El equipo seleccionado no tiene conjuntos asignados.")
        return REVOCAR_CONJUNTOS
    message = f"Conjuntos asignados al equipo {equipo_id}:\n\n"
    buttons = []
    for c in conjuntos:
        btn_text = f"Conjunto {c['numero']} ({c['pendientes']} pendientes)"
        message += f"{btn_text}\n"
        # Botón para revocar este conjunto (callback: "revocar_conjunto_<conjunto_id>")
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"revocar_conjunto_{c['id']}")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text(message, reply_markup=reply_markup)
    return REVOCAR_CONJUNTOS

# Handler que desasigna (revoca) un conjunto de un equipo.
async def revocar_conjunto_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    try:
        conjunto_id = int(query.data.split("_")[2])
    except Exception as e:
        await query.edit_message_text("Error al procesar el conjunto seleccionado.")
        return REVOCAR_CONJUNTOS
    try:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("UPDATE conjuntos SET equipo_id = NULL WHERE id = %s", (conjunto_id,))
        conn.commit()
        cur.close()
        release_db(conn)
    except Exception as e:
        logger.error(f"Error al desasignar el conjunto: {e}")
        await query.edit_message_text("Error al desasignar el conjunto.")
        return REVOCAR_CONJUNTOS
    await query.edit_message_text(f"Conjunto {conjunto_id} ha sido desasignado exitosamente.")
    return MAIN_MENU

async def post_adhesion_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "add_more":
        products = get_products()
        if not products:
            await query.edit_message_text("No hay productos disponibles.")
            return MAIN_MENU
        keyboard = []
        for product in products:
            keyboard.append([InlineKeyboardButton(product['name'], callback_data=f"product_{product['id']}")])
        # Según el origen, configurar el botón de "Volver"
        if context.user_data.get("origin") == "carrito" and 'selected_cart_id' in context.user_data:
            cart_id = context.user_data['selected_cart_id']
            keyboard.append([InlineKeyboardButton("Volver al menú del carrito", callback_data=f"back_cart_{cart_id}")])
        else:
            keyboard.append([InlineKeyboardButton("Volver al Menú Principal", callback_data="back_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Seleccione un producto:", reply_markup=reply_markup)
        return ORDERING
    elif data == "pay_cart":
        cart_id = context.user_data.get('selected_cart_id')
        if not cart_id:
            await query.edit_message_text("Error: Carrito no seleccionado.")
            return POST_ADHESION
        cart_name, init_point = create_payment_preference_for_cart(cart_id)
        if not init_point:
            await query.edit_message_text("Error al crear la preferencia de pago.")
            return POST_ADHESION
        keyboard = [
            [InlineKeyboardButton("Pagar", url=init_point)]
        ]
        if context.user_data.get("origin") == "carrito":
            keyboard.append([InlineKeyboardButton("Volver al menú del carrito", callback_data=f"back_cart_{cart_id}")])
        else:
            keyboard.append([InlineKeyboardButton("Volver al Menú Principal", callback_data="back_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        msg = (f"Para pagar el carrito '{cart_name}', haga clic en 'Pagar'.\n"
               "El mensaje de confirmación se enviará cuando se complete el pago.\n\n"
               "Cuando realize el pago, regrese al bot")
        await query.edit_message_text(msg, reply_markup=reply_markup)
        return POST_ADHESION
    elif data.startswith("back_main"):
        # Volver al menú principal
        keyboard = [
            [InlineKeyboardButton("Ordenar", callback_data="menu_ordenar")],
            [InlineKeyboardButton("Historial", callback_data="menu_historial")],
            [InlineKeyboardButton("Pedidos Pendientes", callback_data="menu_pedidos")],
            [InlineKeyboardButton("Carritos", callback_data="menu_carritos")],
            [InlineKeyboardButton("Cambiar Direccion", callback_data="menu_cambiar")],
            [InlineKeyboardButton("Contacto", callback_data="menu_contacto")],
        [InlineKeyboardButton("Ayuda", callback_data="menu_ayuda")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Menú Principal:", reply_markup=reply_markup)
        return MAIN_MENU
    elif data.startswith("back_cart_"):
        try:
            cart_id = int(data.split("_")[2])
        except Exception as e:
            await query.edit_message_text("Error al procesar el carrito.")
            return CART_MENU
        return await cart_menu_handler(update, context)
    else:
        return POST_ADHESION





def create_payment_preference_for_cart(cart_id):
    """Crea una preferencia de pago para el carrito en producción y retorna (cart_name, init_point)."""
    conn = None
    cur = None
    try:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("SELECT name, total FROM carts WHERE id = %s", (cart_id,))
        row = cur.fetchone()
        if not row:
            return None, None
        cart_name = row[0]
        cart_total = float(row[1])
        if cart_total <= 0:
            logger.error("El total del carrito es 0 o negativo.")
            return None, None
    except Exception as e:
        logger.error(f"Error al obtener datos del carrito: {e}")
        return None, None
    finally:
        if cur:
            cur.close()
        if conn:
            release_db(conn)
    
    # Usa tu token de producción
    sdk = mercadopago.SDK(MP_SDK)  # Reemplaza con tu token de producción
    preference_data = {
        "items": [
            {
                "title": cart_name,
                "quantity": 1,
                "unit_price": cart_total
            }
        ],
        "external_reference": f"{cart_id}",
        "back_urls": {
            "success": "https://your-production-domain.com/success",
            "failure": "https://your-production-domain.com/failure",
            "pending": "https://your-production-domain.com/pending"
        },
        "auto_return": "approved"
    }
    preference_response = sdk.preference().create(preference_data)
    logger.info(f"Respuesta de preferencia (producción): {preference_response}")
    preference = preference_response.get("response", {})
    init_point = preference.get("init_point")
    return cart_name, init_point

# Función que recupera todos los equipos y calcula la suma de pedidos pendientes de todos sus conjuntos asignados.
def get_all_equipos_for_view():
    """
    Retorna una lista de equipos con la información de los integrantes (nombres, no IDs)
    y la suma de pedidos pendientes de todos los conjuntos asignados a ese equipo.
    """
    # Primero, obtenemos todos los equipos (solo sus IDs)
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM equipos")
    equipos = cur.fetchall()
    cur.close()
    release_db(conn)
    
    equipos_list = []
    for row in equipos:
        equipo_id = row[0]
        # Obtenemos la información del equipo (nombres de los integrantes)
        info = get_equipo_info(equipo_id)
        nombre1 = info["trabajador1"] if info else "N/D"
        nombre2 = info["trabajador2"] if info else "N/D"
        
        # Recuperamos los conjuntos asignados a este equipo para calcular los pedidos pendientes
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM conjuntos WHERE equipo_id = %s", (equipo_id,))
        conjuntos = cur.fetchall()
        cur.close()
        release_db(conn)
        
        total_pendientes = 0
        for c in conjuntos:
            conjunto_id = c[0]
            total_pendientes += count_pending_orders_in_conjunto(conjunto_id)
        
        equipos_list.append({
            "id": equipo_id,
            "trabajador1": nombre1,
            "trabajador2": nombre2,
            "total_pendientes": total_pendientes
        })
    
    # Ordenamos la lista de equipos de menor a mayor por pedidos pendientes
    equipos_list.sort(key=lambda e: e["total_pendientes"])
    return equipos_list


async def ver_equipos_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    equipos = get_all_equipos_for_view()
    if not equipos:
        await query.edit_message_text("No existen equipos creados.")
        return GESTION_PEDIDOS
    message = "Equipos:\n\n"
    buttons = []
    for equipo in equipos:
        # Se muestran los nombres de los integrantes en lugar de sus IDs
        equipo_text = f"Equipo: {equipo['trabajador1']} y {equipo['trabajador2']} - {equipo['total_pendientes']} pedidos pendientes"
        message += f"{equipo_text}\n"
        # El callback data incluye el id del equipo para pasar al handler ver_equipo_handler.
        buttons.append([InlineKeyboardButton(equipo_text, callback_data=f"ver_equipo_{equipo['id']}")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text(message, reply_markup=reply_markup)
    return VER_EQUIPOS  # Asegúrate de tener el estado VER_EQUIPOS definido.


# Handler que muestra la información detallada de un equipo y sus conjuntos asignados.
async def ver_equipo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    try:
        equipo_id = int(query.data.split("_")[2])
    except Exception as e:
        await query.edit_message_text("Error al procesar el equipo seleccionado.")
        return VER_EQUIPOS
    equipo_info = get_equipo_info(equipo_id)
    if not equipo_info:
        await query.edit_message_text("Equipo no encontrado.")
        return VER_EQUIPOS
    # Recuperar los conjuntos asignados a este equipo.
    def get_conjuntos_by_equipo(equipo_id):
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("SELECT id, numero_conjunto FROM conjuntos WHERE equipo_id = %s", (equipo_id,))
        rows = cur.fetchall()
        cur.close()
        release_db(conn)
        conjuntos = []
        for row in rows:
            conjunto_id, numero_conjunto = row
            pendientes = count_pending_orders_in_conjunto(conjunto_id)
            conjuntos.append({
                "id": conjunto_id,
                "numero": numero_conjunto,
                "pendientes": pendientes
            })
        conjuntos.sort(key=lambda c: c["pendientes"])
        return conjuntos

    conjuntos = get_conjuntos_by_equipo(equipo_id)
    message = f"Equipo {equipo_info['id']} ({equipo_info['trabajador1']} y {equipo_info['trabajador2']})\n\n"
    if not conjuntos:
        message += "No tiene conjuntos asignados."
    else:
        message += "Conjuntos asignados:\n"
    buttons = []
    for c in conjuntos:
        btn_text = f"Conjunto {c['numero']} - {c['pendientes']} pendientes"
        # El callback data "descargar_conjunto_<conjunto_id>" pasará al handler para descargar el PDF.
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"descargar_conjunto_{c['id']}")])
    # Agregar botón para volver al menú de gestión
    buttons.append([InlineKeyboardButton("Volver a Gestión de Pedidos y Equipos", callback_data="gestion_pedidos")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text(message, reply_markup=reply_markup)
    return VER_EQUIPOS

# Handler que genera y envía el PDF de un conjunto seleccionado.
async def descargar_conjunto_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    try:
        conjunto_id = int(query.data.split("_")[2])
    except Exception as e:
        await query.edit_message_text("Error al procesar el conjunto seleccionado.")
        return VER_EQUIPOS
    # Generar el PDF del conjunto (usa tu función existente generate_conjunto_pdf)
    pdf_file = generate_conjunto_pdf(conjunto_id, query.from_user.id)
    if not pdf_file:
        await query.edit_message_text("Error al generar el PDF del conjunto.")
        return VER_EQUIPOS
    try:
        with open(pdf_file, "rb") as f:
            await context.bot.send_document(chat_id=query.message.chat_id,
                                            document=f,
                                            filename=pdf_file,
                                            caption=f"PDF del Conjunto {conjunto_id}")
    except Exception as e:
        logger.error(f"Error al enviar el PDF: {e}")
        await query.edit_message_text("Error al enviar el PDF.")
        return VER_EQUIPOS
    # Botón para volver al menú de gestión
    keyboard = [[InlineKeyboardButton("Volver a Gestión de Pedidos y Equipos", callback_data="gestion_pedidos")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("PDF enviado.", reply_markup=reply_markup)
    return VER_EQUIPOS


def get_pending_orders(telegram_id, limit=20):
    """Obtiene los últimos 'limit' pedidos pendientes para el usuario."""
    conn = None
    cur = None
    try:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, cart_id, confirmation_code, order_date FROM orders WHERE telegram_id = %s AND status = 'pendiente' ORDER BY order_date DESC LIMIT %s",
            (telegram_id, limit)
        )
        orders = cur.fetchall()
        return orders
    except Exception as e:
        logger.error(f"Error al obtener pedidos pendientes: {e}")
        return []
    finally:
        if cur:
            cur.close()
        if conn:
            release_db(conn)

async def pending_orders_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Muestra los últimos 20 pedidos pendientes del usuario con un botón para volver al menú principal."""
    query = update.callback_query
    await query.answer()
    telegram_id = query.from_user.id
    orders = get_pending_orders(telegram_id, limit=20)
    if not orders:
        keyboard = [[InlineKeyboardButton("Volver al Menú Principal", callback_data="back_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("No tienes pedidos pendientes.", reply_markup=reply_markup)
        return MAIN_MENU

    text = "Tus pedidos pendientes:\n\n"
    for order in orders:
        order_id, cart_id, confirmation_code, order_date = order
        if isinstance(order_date, datetime.datetime):
            order_date_str = order_date.strftime("%Y-%m-%d %H:%M:%S")
        else:
            order_date_str = str(order_date)
        text += f"Pedido #{order_id}: Código {confirmation_code} - Fecha {order_date_str}\n"
    keyboard = [[InlineKeyboardButton("Volver al Menú Principal", callback_data="back_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup)
    return MAIN_MENU

def crear_nuevo_equipo_db(trabajador1: int, trabajador2: int):
    """
    Crea un nuevo equipo en la tabla 'equipos' con los dos IDs de Telegram proporcionados.
    Retorna el id del equipo creado o None en caso de error.
    """
    conn = connect_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO equipos (trabajador1, trabajador2) VALUES (%s, %s) RETURNING id",
            (trabajador1, trabajador2)
        )
        equipo_id = cur.fetchone()[0]
        conn.commit()
        return equipo_id
    except Exception as e:
        logger.error(f"Error al crear nuevo equipo: {e}")
        conn.rollback()
        return None
    finally:
        cur.close()
        release_db(conn)


async def crear_nuevo_equipo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handler para la opción "Crear Nuevo Equipo".  
    Se solicita al usuario que ingrese dos IDs de Telegram (separados por un espacio o coma).  
    Si la entrada es válida, se crea el equipo en la base de datos y se notifica el éxito junto con un botón para volver al menú de gestión.
    """
    # Si el handler se activa mediante callback (por ejemplo, al presionar el botón "Crear Nuevo Equipo")
    # y no hay mensaje de texto aún, se solicita la entrada.
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Ingrese los dos IDs de Telegram separados por un espacio o coma:")
        return CREAR_NUEVO_EQUIPO

    # Si el usuario ya ingresó un mensaje (estado CREAR_NUEVO_EQUIPO)
    message_text = update.message.text
    # Reemplazamos comas por espacios y dividimos para obtener los dos IDs
    ids = message_text.replace(",", " ").split()
    if len(ids) != 2:
        error_text = "Debe ingresar exactamente dos IDs de Telegram separados por un espacio o coma. Inténtelo nuevamente."
        await update.message.reply_text(error_text)
        return CREAR_NUEVO_EQUIPO

    try:
        id1 = int(ids[0])
        id2 = int(ids[1])
    except ValueError:
        error_text = "Los IDs deben ser números. Inténtelo nuevamente."
        await update.message.reply_text(error_text)
        return CREAR_NUEVO_EQUIPO

    # Crear el equipo en la base de datos
    equipo_id = crear_nuevo_equipo_db(id1, id2)
    if equipo_id is None:
        error_text = "Error al crear el equipo. Por favor, intente nuevamente."
        await update.message.reply_text(error_text)
        return CREAR_NUEVO_EQUIPO

    # Notificar éxito y agregar un botón para volver al menú de gestión de pedidos y equipos.
    success_text = f"Equipo creado exitosamente: Equipo {equipo_id} - {id1} y {id2}."
    keyboard = [
        [InlineKeyboardButton("Volver a Gestión de Pedidos y Equipos", callback_data="gestion_pedidos")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(success_text, reply_markup=reply_markup)
    return GESTION_PEDIDOS

# Agrega un handler para el comando /webhookinfo
async def webhook_info_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        info = await context.bot.get_webhook_info()
        # Envía la información como mensaje o imprímela en los logs
        await update.message.reply_text(f"Webhook Info:\n{info}")
        logger.info(f"Webhook Info: {info}")
    except Exception as e:
        logger.error(f"Error al obtener webhook info: {e}")
        await update.message.reply_text("Error al obtener la información del webhook.")

def get_cart_owner(cart_id):
    """Retorna el telegram_id del dueño del carrito."""
    conn = None
    cur = None
    try:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("SELECT telegram_id FROM carts WHERE id = %s", (cart_id,))
        row = cur.fetchone()
        if row:
            return row[0]
        else:
            return None
    except Exception as e:
        logger.error(f"Error al obtener dueño del carrito: {e}")
        return None
    finally:
        release_db(conn)

async def new_cart_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Crea un nuevo carrito para el usuario. Si en context.user_data se encuentran datos de adhesión
    (producto y cantidad), se agrega el producto al carrito recién creado; de lo contrario, se crea un carrito vacío.
    Luego muestra la pantalla de "¿Qué desea hacer a continuación?" con opciones:
      - Agregar más productos
      - Pagar Carrito
      - Volver: “Volver al menú del carrito” si el proceso se inició desde un carrito específico (origin == "carrito")
        o “Volver al Menú Principal” en caso contrario.
    Retorna el estado POST_ADHESION.
    """
    cart_name = update.message.text.strip()
    telegram_id = update.effective_user.id
    cart_id = create_new_cart(telegram_id, cart_name)
    if not cart_id:
        await update.message.reply_text("Error al crear el carrito.")
        return SELECT_CART

    # **Asignamos el ID del carrito recién creado en el contexto**
    context.user_data['selected_cart_id'] = cart_id

    # Si existen datos de adhesión, se agrega el producto al carrito recién creado.
    product = context.user_data.get('selected_product')
    quantity = context.user_data.get('quantity')
    if product is not None and quantity is not None:
        total_anterior, subtotal, nuevo_total = add_product_to_cart(cart_id, product, quantity)
        if total_anterior is None:
            await update.message.reply_text("Error al agregar el producto al carrito.")
            return SELECT_CART
        msg = (f"Se creó el carrito *{cart_name}* y se agregó el producto.\n"
               f"Total anterior: {total_anterior:.2f}\n"
               f"Subtotal: {subtotal:.2f}\n"
               f"Nuevo total: {nuevo_total:.2f}")
        # Limpiar los datos de adhesión
        context.user_data.pop('selected_product', None)
        context.user_data.pop('quantity', None)
    else:
        msg = f"Carrito *{cart_name}* creado correctamente."

    # Configurar el botón "Volver":
    # Si el proceso se inició desde un carrito específico (origin == "carrito") se usa "back_cart_{cart_id}".
    # En caso contrario se usa "back_main".
    if context.user_data.get("origin") == "carrito":
        back_button = InlineKeyboardButton("Volver al menú del carrito", callback_data=f"back_cart_{cart_id}")
    else:
        back_button = InlineKeyboardButton("Volver al Menú Principal", callback_data="back_main")

    keyboard = [
        [InlineKeyboardButton("Agregar más productos", callback_data="add_more")],
        [InlineKeyboardButton("Pagar Carrito", callback_data="pay_cart")],
        [back_button]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=reply_markup)
    return POST_ADHESION

async def test_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Ejecutando /test")
    chat_id = update.effective_user.id
    try:
        await context.bot.send_message(chat_id=chat_id, text="Test OK")
        logger.info("Mensaje 'Test OK' enviado a %s", chat_id)
    except Exception as e:
        logger.exception("Error en /test: %s", e)


@app.route('/testupdate', methods=['POST'])
def test_update():
    data = request.get_json(force=True)
    logger.info("Test update received: %s", data)
    return jsonify({"status": "received", "data": data}), 200

@app.route('/env', methods=['GET'])
def env_info():
    return jsonify({
        "TELEGRAM_TOKEN": TOKEN[:10] + "..." if TOKEN else None,
        "MP_SDK": MP_SDK[:10] + "..." if MP_SDK else None
    })


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancela la conversación."""
    await update.message.reply_text("Operación cancelada.")
    return ConversationHandler.END

@app.route("/webhook", methods=["POST"])
def mp_webhook():
    data = request.json
    logger.info(f"Webhook recibido: {data}")
    
    if data.get("action") in ["payment.created", "payment.updated"]:
        payment_data = data.get("data", {})
        payment_id = payment_data.get("id")
        if not payment_id:
            logger.error("No se encontró el id del pago")
            return jsonify({"error": "No payment id"}), 400

        global processed_payment_ids
        if payment_id in processed_payment_ids:
            logger.info("Pago ya procesado, ignorando notificación")
            return jsonify({"status": "ignored"}), 200
        else:
            processed_payment_ids.add(payment_id)
        
        try:
            sdk = mercadopago.SDK(MP_SDK)
            payment_detail_response = sdk.payment().get(payment_id)
            payment_detail = payment_detail_response.get("response", {})
            logger.info(f"Detalles del pago: {payment_detail}")
            status = payment_detail.get("status")
            logger.info(f"Estado del pago: {status}")
        except Exception as e:
            logger.error(f"Error al obtener detalles del pago: {e}")
            return jsonify({"error": str(e)}), 500

        if status == "approved":
            external_ref = payment_detail.get("external_reference")
            if external_ref:
                try:
                    cart_id = int(external_ref)
                except ValueError:
                    logger.error("external_reference inválido")
                    return jsonify({"error": "external_reference inválido"}), 400
                confirmation_code = str(random.randint(100000, 999999))
                user_id = get_cart_owner(cart_id)
                if not user_id:
                    logger.error("No se encontró el dueño del carrito")
                    return jsonify({"error": "No se encontró el dueño del carrito"}), 404
                order_id, conjunto_id = insert_order_with_conjunto(cart_id, user_id, confirmation_code)
                if order_id is None:
                    logger.error("Error al insertar el pedido")
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    context_wrapper = SimpleContext(TELEGRAM_BOT)
                    loop.run_until_complete(send_order_notifications(cart_id, confirmation_code, context_wrapper, user_id))
                    loop.close()
                    logger.info("Notificaciones enviadas correctamente")
                    return jsonify({"status": "ok"}), 200
                except Exception as e:
                    logger.error(f"Error enviando notificaciones: {e}")
                    return jsonify({"error": str(e)}), 500
            else:
                logger.error("No se encontró external_reference en los detalles del pago")
                return jsonify({"error": "No external_reference"}), 400
        else:
            logger.info("Pago no aprobado, ignorando notificación")
            return jsonify({"status": "ignored"}), 200
    else:
        logger.info("Notificación no relevante")
    return jsonify({"status": "ignored"}), 200

@app.route('/ping', methods=['GET'])
def ping():
    return "Pong", 200

async def ping_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_user.id, text="Pong")
    logger.info("Comando /ping ejecutado correctamente")



def main() -> None:
    
    init_db()
    
    application.add_handler(CommandHandler("start", start), group=-1)
    application.add_handler(CommandHandler("test", test_handler), group=-1)
    application.add_handler(CommandHandler("crear_equipo", crear_equipo_command_handler))
    application.add_handler(CommandHandler("eliminar_equipo", eliminar_equipo_command_handler))
    application.add_handler(CommandHandler("asignar_conjunto", asignar_conjunto_command_handler))
    application.add_handler(CommandHandler("revocar_conjunto", revocar_conjunto_command_handler))
    application.add_handler(CommandHandler("ver_conjuntos", ver_conjuntos_no_terminados_handler))
    application.add_handler(CommandHandler("webhookinfo", webhook_info_handler))

    application.add_handler(CommandHandler("ping", ping_handler), group=0)

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name_handler)],
            ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, address_handler)],
            CAMBIAR_DIRECCION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, procesar_cambio_direccion_handler),
                CallbackQueryHandler(cancelar_cambio_direccion_handler, pattern="^cancelar_direccion$")
            ],
            MAIN_MENU: [
                CallbackQueryHandler(main_menu_handler, pattern="^(menu_.*|back_main|gestion_pedidos|gestion_pedidos_personal)$"),
                CallbackQueryHandler(cambiar_direccion_handler, pattern="^menu_cambiar$"),
                CallbackQueryHandler(cancelar_cambio_direccion_handler, pattern="^cancelar_direccion$")
            ],
            ORDERING: [
                CallbackQueryHandler(product_handler, pattern="^(product_.*|menu)$"),
                CallbackQueryHandler(back_cart_handler, pattern="^back_cart_.*"),
                CallbackQueryHandler(new_cart_query_handler, pattern="^new_cart$")
            ],
            ASK_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, quantity_handler)],
            SELECT_CART: [CallbackQueryHandler(cart_selection_handler, pattern="^(select_cart_.*|back_quantity|new_cart)$")],
            NEW_CART: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_cart_name_handler)],
            POST_ADHESION: [CallbackQueryHandler(post_adhesion_handler, pattern="^(add_more|pay_cart|back_main|back_cart_.*)$")],
            CARTS_LIST: [
                CallbackQueryHandler(cart_menu_handler, pattern="^cartmenu_\\d+$"),
                CallbackQueryHandler(main_menu_handler, pattern="^back_main$"),
                CallbackQueryHandler(show_carts_handler, pattern="^show_carts$"),
                CallbackQueryHandler(new_cart_query_handler, pattern="^new_cart$")
            ],
            CART_MENU: [
                CallbackQueryHandler(cart_menu_handler, pattern="^(cartmenu_.*|back_cart_.*)$"),
                CallbackQueryHandler(cart_details_handler, pattern="^cart_details_.*"),
                CallbackQueryHandler(cart_add_handler, pattern="^cart_add_.*"),
                CallbackQueryHandler(cart_remove_handler, pattern="^cart_remove_\\d+$"),
                CallbackQueryHandler(cart_removeitem_handler, pattern="^cart_removeitem_.*"),
                CallbackQueryHandler(cart_delete_handler, pattern="^cart_delete_.*"),
                CallbackQueryHandler(cart_pay_handler, pattern="^cart_pay_.*"),
                CallbackQueryHandler(show_carts_handler, pattern="^show_carts$"),
                CallbackQueryHandler(main_menu_handler, pattern="^back_main$")
            ],
            # Aquí se agrupan todas las opciones de gestión en un solo estado
            GESTION_PEDIDOS: [
                CallbackQueryHandler(gestion_pedidos_handler, pattern="^gestion_pedidos$"),
                CallbackQueryHandler(asignar_conjuntos_handler, pattern="^asignar_conjuntos$"),
                CallbackQueryHandler(revocar_conjuntos_handler, pattern="^revocar_conjuntos$"),
                CallbackQueryHandler(ver_equipos_handler, pattern="^ver_equipos$"),
                CallbackQueryHandler(crear_nuevo_equipo_handler, pattern="^crear_nuevo_equipo$"),
                CallbackQueryHandler(descargar_pdf_conjunto_handler, pattern="^descargarpdf_\\d+$"),
                CallbackQueryHandler(lambda u, c: eliminar_equipo_command_handler(u, c), pattern="^eliminar_equipos$"),
                CallbackQueryHandler(lambda u, c: ver_conjuntos_no_terminados_handler(u, c), pattern="^ver_conjuntos_no_terminados$")
            ],
            # Y si requieres un estado aparte para cuando se selecciona un conjunto y luego un equipo:
            SELECCIONAR_EQUIPO: [
                CallbackQueryHandler(select_conjunto_handler, pattern="^select_conjunto_\\d+$"),
                CallbackQueryHandler(asignar_equipo_handler, pattern="^asignar_\\d+_equipo_\\d+$"),
                CallbackQueryHandler(gestion_pedidos_personal_handler, pattern="^gestion_pedidos_personal$"),
                CallbackQueryHandler(descargar_pdf_conjunto_handler, pattern="^descargarpdf_\\d+$")
            ],
            CHANGE_STATUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_status_handler)],
            REVOCAR_CONJUNTOS: [
                CallbackQueryHandler(revocar_conjuntos_handler, pattern="^revocar_conjuntos$"),
                CallbackQueryHandler(select_equipo_revocar_handler, pattern="^revocar_equipo_\\d+$"),
                CallbackQueryHandler(revocar_conjunto_handler, pattern="^revocar_conjunto_\\d+$")
            ],
            VER_EQUIPOS: [
                CallbackQueryHandler(ver_equipos_handler, pattern="^ver_equipos$"),
                CallbackQueryHandler(ver_equipo_handler, pattern="^ver_equipo_\\d+$"),
                CallbackQueryHandler(descargar_conjunto_handler, pattern="^descargar_conjunto_\\d+$")
            ],
            CREAR_NUEVO_EQUIPO: [MessageHandler(filters.TEXT & ~filters.COMMAND, crear_nuevo_equipo_handler)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True
    )

    application.add_handler(conv_handler)


    from waitress import serve
    port = int(os.environ.get("PORT", 8000))
    serve(app, host="0.0.0.0", port=port)

#def run_bot():
#    print("Iniciando bot...")
#    application.runpolling()


@app.route("/webhook2", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    # Agrega logs y prints para confirmar que se recibió la actualización
    logger.info("Webhook triggered. Data received: %s", data)
    print("Webhook triggered. Data received:", data)
    sys.stdout.flush()  # Forzar que se escriba inmediatamente en los logs

    try:
        update = Update.de_json(data, TELEGRAM_BOT)
        logger.info("Update object creado correctamente")
        loop = ensure_bot_loop()  # Asegura que el event loop esté corriendo
        future = asyncio.run_coroutine_threadsafe(application.process_update(update), loop)
        future.result()  # Espera a que se procese la actualización (opcional)
        logger.info("Update procesado correctamente")
        return 'ok', 200
    except Exception as e:
        logger.exception("Error procesando update en /webhook2")
        return jsonify({"error": str(e)}), 500



# ... (resto de tu código en bot.py)
@app.before_first_request
def setup_webhook():
    webhook_url = "https://verduleria.onrender.com/webhook2"
    result = TELEGRAM_BOT.set_webhook(webhook_url)
    if result:
        logger.info("Webhook configurado correctamente")
        print("setup_webhook() se ha ejecutado: Webhook configurado correctamente")
    else:
        logger.error("Error configurando el webhook")
        print("setup_webhook() se ha ejecutado: Error configurando el webhook")



if __name__ == "__main__":
    #ensure_bot_loop()  # Esto crea y arranca BOT_LOOP
    #webhook_url = "https://verduleria.onrender.com/webhook2"
    #if TELEGRAM_BOT.set_webhook(webhook_url):
    #    logger.info("Webhook configurado correctamente")
    #else:
    #    logger.error("Error configurando el webhook")
    #main()n
    application.run_polling()


