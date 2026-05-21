from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def rollback_session(db: Session) -> None:
    """Clear a failed transaction so the same Session can run further SQL."""
    try:
        db.rollback()
    except SQLAlchemyError:
        pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        rollback_session(db)
        raise
    finally:
        db.close()
