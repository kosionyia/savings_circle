from sqlmodel import Session, SQLModel, create_engine, select

from app.models.user import User, UserRole
from app.services.security import hash_password

DATABASE_URL = "sqlite:///ajo.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


def seed_demo_users():
    with Session(engine) as session:
        existing = session.exec(
            select(User).where(User.email == "ade@ajo.com")
        ).first()
        if existing:
            return

        session.add(
            User(
                name="Chairman Ade",
                email="ade@ajo.com",
                hashed_password=hash_password("secret123"),
                role=UserRole.ADMIN,
            )
        )
        session.add(
            User(
                name="Amaka",
                email="amaka@ajo.com",
                hashed_password=hash_password("secret123"),
                role=UserRole.MEMBER,
            )
        )
        session.add(
            User(
                name="Chinedu",
                email="chinedu@ajo.com",
                hashed_password=hash_password("secret123"),
                role=UserRole.MEMBER,
            )
        )
        session.commit()
