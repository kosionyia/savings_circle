import pytest
from sqlalchemy import func
from sqlmodel import select

from app.config import BANK_API_KEY
from app.models.circles import Circle
from app.models.contribution import Contribution
from app.models.ledger import JournalEntry, JournalLine
from app.models.membership import Membership
from app.models.user import UserRole

BANK_HEADERS = {"X-API-Key": BANK_API_KEY}


@pytest.fixture
def contribution(session, make_user):
    admin = make_user(name="Ade", role=UserRole.ADMIN)
    member = make_user(name="Amaka")
    circle = Circle(
        name="Surulere",
        weekly_amount_kobo=500000,
        member_limit=5,
        admin_id=admin.id,
    )
    session.add(circle)
    session.flush()
    session.add(Membership(user_id=member.id, circle_id=circle.id, turn_position=1))
    contribution = Contribution(
        user_id=member.id,
        circle_id=circle.id,
        amount_kobo=500000,
        week=1,
    )
    session.add(contribution)
    session.commit()
    session.refresh(contribution)
    return contribution


def entry_count(session) -> int:
    return session.exec(select(func.count()).select_from(JournalEntry)).one()


def test_confirm_posts_a_balanced_journal_entry(client, session, contribution):
    response = client.post(
        "/bank/confirm",
        json={"contribution_id": contribution.id},
        headers=BANK_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["confirmed"] is True

    entry = session.exec(select(JournalEntry)).one()
    assert entry.reference == f"CONTRIB-{contribution.id}"
    assert entry.created_by is None  # posted by the bank, not a user

    amounts = session.exec(
        select(JournalLine.amount_kobo)
        .where(JournalLine.entry_id == entry.id)
        .order_by(JournalLine.id)
    ).all()
    assert amounts == [500000, -500000]


def test_confirming_twice_posts_one_entry(client, session, contribution):
    body = {"contribution_id": contribution.id}
    client.post("/bank/confirm", json=body, headers=BANK_HEADERS)

    response = client.post("/bank/confirm", json=body, headers=BANK_HEADERS)
    assert response.status_code == 409
    assert entry_count(session) == 1


def test_unknown_contribution_is_404(client, session):
    response = client.post(
        "/bank/confirm", json={"contribution_id": 999999}, headers=BANK_HEADERS
    )
    assert response.status_code == 404
    assert entry_count(session) == 0


def test_confirm_requires_the_bank_api_key(client, session, contribution):
    response = client.post(
        "/bank/confirm",
        json={"contribution_id": contribution.id},
        headers={"X-API-Key": "wrong"},
    )
    assert response.status_code == 401
    assert entry_count(session) == 0


def test_ledger_lists_entries_with_their_lines(client, contribution):
    client.post(
        "/bank/confirm",
        json={"contribution_id": contribution.id},
        headers=BANK_HEADERS,
    )

    response = client.get("/bank/ledger", headers=BANK_HEADERS)
    assert response.status_code == 200
    [entry] = response.json()
    assert entry["reference"] == f"CONTRIB-{contribution.id}"
    assert [
        (line["account_type"], line["amount_kobo"]) for line in entry["lines"]
    ] == [("bank_clearing", 500000), ("circle_pot", -500000)]
