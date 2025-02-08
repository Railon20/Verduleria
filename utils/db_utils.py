# utils/db_utils.py

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from config import DATABASE_URI

# Crea el engine utilizando la URI definida en config.py
engine = create_engine(DATABASE_URI, echo=False)

# Crea una fábrica de sesiones
SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

def get_session():
    """
    Retorna una nueva sesión de base de datos.
    """
    return SessionLocal()
