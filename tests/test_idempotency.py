import pytest
from sqlalchemy import func
from sqlmodel import select

from app.models.circles import Circle
from app.models.contribution import Contribution
from app.models.membership import Membership
from app.models.user import UserRole
from app.services.idempotency import REPLAY_HEADER, request_hash
from tests.conftest import auth_headers


@pytest.fixture
def circle(session, make_user):
    admin = make_user(name="Ade", role=UserRole.ADMIN)
    circle = Circle(
        name="Surulere",
        weekly_amount_kobo=500000,
        member_limit=5,
        admin_id=admin.id,
    )
    session.add(circle)
    session.commit()
    session.refresh(circle)
    return circle


@pytest.fixture
def amaka(session, make_user, circle):
    member = make_user(name="Amaka")
    session.add(Membership(user_id=member.id, circle_id=circle.id, turn_position=1))
    session.commit()
    return member


def contribute(client, circle, member, key, amount_kobo=500000):
    headers = auth_headers(member)
    if key is not None:
        headers["Idempotency-Key"] = key
    return client.post(
        f"/circles/{circle.id}/contributions",
        json={"amount_kobo": amount_kobo},
        headers=headers,
    )


def contribution_count(session) -> int:
    return session.exec(select(func.count()).select_from(Contribution)).one()


# --- request_hash ---------------------------------------------------------


def test_hash_ignores_key_order():
    a = request_hash("POST", "/circles/1/contributions", {"a": 1, "b": 2})
    b = request_hash("post", "/circles/1/contributions", {"b": 2, "a": 1})
    assert a == b
    assert len(a) == 64


@pytest.mark.parametrize(
    "path, body",
    [
        ("/circles/1/contributions", {"a": 1, "b": 3}),  # different body
        ("/circles/2/contributions", {"a": 1, "b": 2}),  # different circle
    ],
)
def test_hash_changes_with_the_request(path, body):
    original = request_hash("POST", "/circles/1/contributions", {"a": 1, "b": 2})
    assert request_hash("POST", path, body) != original


# --- contributions endpoint -----------------------------------------------


def test_first_request_is_processed(client, session, circle, amaka):
    response = contribute(client, circle, amaka, key="key-1")

    assert response.status_code == 201
    assert REPLAY_HEADER not in response.headers
    assert contribution_count(session) == 1


def test_retry_with_same_key_replays_the_original_response(
    client, session, circle, amaka
):
    first = contribute(client, circle, amaka, key="key-1")
    retry = contribute(client, circle, amaka, key="key-1")

    assert retry.status_code == 201  # not 409 "already contributed"
    assert retry.json() == first.json()
    assert retry.headers[REPLAY_HEADER] == "true"
    assert contribution_count(session) == 1


def test_same_key_with_different_body_is_rejected(client, session, circle, amaka):
    contribute(client, circle, amaka, key="key-1")
    response = contribute(client, circle, amaka, key="key-1", amount_kobo=300000)

    assert response.status_code == 422
    assert "different request" in response.json()["detail"]
    assert contribution_count(session) == 1


def test_new_key_for_the_same_week_still_hits_the_business_rule(
    client, session, circle, amaka
):
    contribute(client, circle, amaka, key="key-1")
    response = contribute(client, circle, amaka, key="key-2")

    assert response.status_code == 409
    assert response.json()["detail"] == "Already contributed this week"
    assert contribution_count(session) == 1


def test_failed_request_does_not_burn_the_key(client, session, circle, amaka):
    wrong_amount = contribute(client, circle, amaka, key="key-1", amount_kobo=300000)
    assert wrong_amount.status_code == 409

    # The error wasn't stored, so the corrected retry with the same key runs
    corrected = contribute(client, circle, amaka, key="key-1")
    assert corrected.status_code == 201
    assert contribution_count(session) == 1


def test_keys_are_scoped_per_user(client, session, make_user, circle, amaka):
    chinedu = make_user(name="Chinedu")
    session.add(Membership(user_id=chinedu.id, circle_id=circle.id, turn_position=2))
    session.commit()

    contribute(client, circle, amaka, key="shared-key")
    response = contribute(client, circle, chinedu, key="shared-key")

    assert response.status_code == 201
    assert REPLAY_HEADER not in response.headers
    assert contribution_count(session) == 2


def test_missing_key_is_rejected(client, session, circle, amaka):
    response = contribute(client, circle, amaka, key=None)

    assert response.status_code == 422
    assert contribution_count(session) == 0
