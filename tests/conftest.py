import os

from dotenv import load_dotenv

# Point the app at the test database *before* anything imports app.config
load_dotenv()
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.models.user import User, UserRole
from app.services.db import engine, get_session
from app.services.security import create_access_token, hash_password


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    """Rebuild the test schema once per test run, using the real migrations."""
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", os.environ["TEST_DATABASE_URL"])
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


@pytest.fixture
def session():
    """A session inside a transaction that is rolled back after each test.

    Routes still call session.commit(); with create_savepoint those commits
    become savepoints inside our outer transaction, so nothing is ever
    really committed and every test starts from an empty database.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def make_user(session):
    def _make_user(
        name: str = "Amaka",
        email: str | None = None,
        role: UserRole = UserRole.MEMBER,
        password: str = "secret123",
    ) -> User:
        user = User(
            name=name,
            email=email or f"{name.lower()}@ajo.com",
            hashed_password=hash_password(password),
            role=role,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user

    return _make_user


def auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}
