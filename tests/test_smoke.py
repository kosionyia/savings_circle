from sqlmodel import select

from app.models.user import User, UserRole
from tests.conftest import auth_headers


def test_register_then_login(client):
    response = client.post(
        "/auth/register",
        json={"name": "Amaka", "email": "amaka@ajo.com", "password": "secret123"},
    )
    assert response.status_code == 201

    response = client.post(
        "/auth/login",
        data={"username": "amaka@ajo.com", "password": "secret123"},
    )
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"


def test_duplicate_email_is_rejected(client, make_user):
    make_user(name="Amaka")

    response = client.post(
        "/auth/register",
        json={"name": "Amaka", "email": "amaka@ajo.com", "password": "secret123"},
    )
    assert response.status_code == 409


def test_admin_can_create_circle(client, make_user):
    admin = make_user(name="Ade", role=UserRole.ADMIN)

    response = client.post(
        "/admin/circles",
        json={"name": "Surulere", "weekly_amount": 5000, "member_limit": 5},
        headers=auth_headers(admin),
    )
    assert response.status_code == 201
    assert response.json()["admin_id"] == admin.id


def test_each_test_starts_with_an_empty_database(session):
    # The tests above created users; the rollback means none of them survive
    assert session.exec(select(User)).all() == []
