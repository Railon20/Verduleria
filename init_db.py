# init_db.py

from sqlalchemy import create_engine
from database.models import Base
from config import DATABASE_URI

def init_db():
    engine = create_engine(DATABASE_URI)
    Base.metadata.create_all(engine)
    print("Base de datos inicializada correctamente.")

if __name__ == '__main__':
    init_db()
