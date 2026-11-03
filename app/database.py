import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Red de seguridad: ninguna sesión espera un candado de fila más de este tiempo (0 = sin límite). Evita que una
# espera bloqueante congele el servicio indefinidamente. Se fija por conexión (funciona también detrás de un pooler).
DB_LOCK_TIMEOUT_MS = int(os.getenv("DB_LOCK_TIMEOUT_MS", "15000"))

if DB_LOCK_TIMEOUT_MS > 0 and engine.dialect.name == "postgresql":
    @event.listens_for(engine, "connect")
    def _fijar_lock_timeout(dbapi_conn, _registro):
        cur = dbapi_conn.cursor()
        cur.execute(f"SET lock_timeout = {DB_LOCK_TIMEOUT_MS}")
        cur.close()
        dbapi_conn.commit()



def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()