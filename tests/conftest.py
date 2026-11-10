import os

from dotenv import load_dotenv

# Point the app at the test database *before* anything imports app.config
load_dotenv()
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

import itertools

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.config import BANK_API_KEY
from app.main import app
from app.models.circles import Circle
from app.models.membership import Membership
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


# --- a funded circle and the API calls that move its money ------------------
# Shared by the payout, balance, statement and trial-balance tests

WEEKLY = 500000
BANK_HEADERS = {"X-API-Key": BANK_API_KEY}
_keys = itertools.count()


def new_key() -> str:
    return f"key-{next(_keys)}"


@pytest.fixture
def admin(make_user):
    return make_user(name="Ade", role=UserRole.ADMIN)


@pytest.fixture
def members(make_user):
    return [make_user(name="Amaka"), make_user(name="Chinedu"), make_user(name="Bola")]


@pytest.fixture
def circle(session, admin, members):
    circle = Circle(
        name="Surulere", weekly_amount_kobo=WEEKLY, member_limit=5, admin_id=admin.id
    )
    session.add(circle)
    session.flush()
    for position, member in enumerate(members, start=1):
        session.add(
            Membership(user_id=member.id, circle_id=circle.id, turn_position=position)
        )
    session.commit()
    session.refresh(circle)
    return circle


@pytest.fixture
def funded(client, circle, members):
    """Every member contributes and the bank confirms: the pot holds ₦15,000."""
    for member in members:
        bank_confirm(client, contribute(client, circle, member).json()["id"])
    return circle


def contribute(client, circle, member, key=None):
    return client.post(
        f"/circles/{circle.id}/contributions",
        json={"amount_kobo": circle.weekly_amount_kobo},
        headers={**auth_headers(member), "Idempotency-Key": key or new_key()},
    )


def bank_confirm(client, contribution_id):
    return client.post(
        "/bank/confirm",
        json={"contribution_id": contribution_id},
        headers=BANK_HEADERS,
    )


def schedule(client, admin, circle, user_id, key=None):
    return client.post(
        f"/circles/{circle.id}/payouts",
        json={"user_id": user_id},
        headers={**auth_headers(admin), "Idempotency-Key": key or new_key()},
    )


def act(client, user, payout_id, action, key=None):
    return client.post(
        f"/payouts/{payout_id}/{action}",
        headers={**auth_headers(user), "Idempotency-Key": key or new_key()},
    )


def advance(client, admin, payout_id, *actions):
    response = None
    for action in actions:
        response = act(client, admin, payout_id, action)
        assert response.status_code == 200, response.json()
    return response
