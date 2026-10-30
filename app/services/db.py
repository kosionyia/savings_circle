from sqlmodel import Session, create_engine

from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL)


def get_session():
    with Session(engine) as session:
        yield session
