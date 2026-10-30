"""Seed demo users. Run after migrations: `uv run python -m app.seed`."""

from sqlmodel import Session, select

from app.models.user import User, UserRole
from app.services.db import engine
from app.services.security import hash_password


def seed_demo_users(session: Session) -> None:
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


if __name__ == "__main__":
    with Session(engine) as session:
        seed_demo_users(session)
    print("Seeded demo users")
