# database/models.py

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Boolean,
    Enum,
    ForeignKey
)
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, unique=True, nullable=False)
    username = Column(String, nullable=True)
    password_hash = Column(String, nullable=True)
    address = Column(String, nullable=True)  # <-- Nuevo campo
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Relaciones, etc.


    # Relaciones: cada usuario puede tener múltiples carritos y pedidos.
    carts = relationship("Cart", back_populates="user", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, telegram_id='{self.telegram_id}', username='{self.username}')>"


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    # Definimos el tipo de venta: 'gramos' o 'unidades'
    sale_unit = Column(Enum("gramos", "unidades", name="sale_unit_enum"), default="unidades")
    price = Column(Float, nullable=False)
    # Para productos vendidos en gramos, se interpretará que 'price' es el precio por 100 gramos.
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Product(id={self.id}, name='{self.name}', sale_unit='{self.sale_unit}', price={self.price})>"


class Cart(Base):
    __tablename__ = "carts"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    # Relaciones: cada carrito pertenece a un usuario y puede tener múltiples ítems.
    user = relationship("User", back_populates="carts")
    items = relationship("CartItem", back_populates="cart", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Cart(id={self.id}, name='{self.name}', user_id={self.user_id}, is_active={self.is_active})>"


class CartItem(Base):
    __tablename__ = "cart_items"

    id = Column(Integer, primary_key=True)
    cart_id = Column(Integer, ForeignKey('carts.id'), nullable=False)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)
    # La cantidad puede representar gramos o unidades, según el producto.
    quantity = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relaciones: cada ítem está asociado a un carrito y a un producto.
    cart = relationship("Cart", back_populates="items")
    product = relationship("Product")

    def __repr__(self):
        return f"<CartItem(id={self.id}, cart_id={self.cart_id}, product_id={self.product_id}, quantity={self.quantity})>"


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    cart_id = Column(Integer, ForeignKey('carts.id'), nullable=False)
    # Código único que se asigna al finalizar el pago del carrito
    order_code = Column(String, unique=True, nullable=False)
    total_price = Column(Float, nullable=False)
    # Estado del pedido: 'pending' (pendiente) o 'completed' (completado)
    status = Column(Enum("pending", "completed", name="order_status_enum"), default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="orders")

    def __repr__(self):
        return f"<Order(id={self.id}, order_code='{self.order_code}', user_id={self.user_id}, status='{self.status}', total_price={self.total_price})>"
