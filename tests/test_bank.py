import pytest
from sqlalchemy import func
from sqlmodel import select

from app.config import BANK_API_KEY
from app.models.circles import Circle
from app.models.contribution import Contribution
from app.models.ledger import (
    AccountType,
    JournalEntry,
    JournalLine,
    LedgerAccount,
    OwnerType,
)
from app.models.membership import Membership
from app.models.user import UserRole
from app.services.ledger import account_balance, find_account

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


def posted_lines(session, entry_id: int) -> list[tuple[str, int | None, int]]:
    """(account_type, owner_id, amount_kobo) for each line of an entry."""
    rows = session.exec(
        select(LedgerAccount.account_type, LedgerAccount.owner_id, JournalLine.amount_kobo)
        .join(LedgerAccount, JournalLine.account_id == LedgerAccount.id)
        .where(JournalLine.entry_id == entry_id)
        .order_by(JournalLine.id)
    ).all()
    return [(account_type.value, owner_id, amount) for account_type, owner_id, amount in rows]


def test_confirm_passes_the_money_through_the_members_wallet(
    client, session, contribution
):
    response = client.post(
        "/bank/confirm",
        json={"contribution_id": contribution.id},
        headers=BANK_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["confirmed"] is True

    received, paid_in = session.exec(select(JournalEntry).order_by(JournalEntry.id)).all()
    assert received.reference == f"CONTRIB-{contribution.id}"
    assert paid_in.reference == f"CONTRIB-{contribution.id}-POT"
    # Posted by the bank, not a user
    assert received.created_by is None and paid_in.created_by is None

    member, circle = contribution.user_id, contribution.circle_id
    assert posted_lines(session, received.id) == [
        ("bank_clearing", None, 500000),
        ("member_wallet", member, -500000),
    ]
    assert posted_lines(session, paid_in.id) == [
        ("member_wallet", member, 500000),
        ("circle_pot", circle, -500000),
    ]


def test_confirm_leaves_the_wallet_at_zero(client, session, contribution):
    client.post(
        "/bank/confirm",
        json={"contribution_id": contribution.id},
        headers=BANK_HEADERS,
    )

    wallet = find_account(
        session, OwnerType.USER, contribution.user_id, AccountType.MEMBER_WALLET
    )
    pot = find_account(
        session, OwnerType.CIRCLE, contribution.circle_id, AccountType.CIRCLE_POT
    )
    bank = find_account(session, OwnerType.SYSTEM, None, AccountType.BANK_CLEARING)
    assert account_balance(session, wallet.id) == 0
    assert account_balance(session, pot.id) == -500000
    assert account_balance(session, bank.id) == 500000


def test_confirming_twice_posts_the_entries_once(client, session, contribution):
    body = {"contribution_id": contribution.id}
    client.post("/bank/confirm", json=body, headers=BANK_HEADERS)

    response = client.post("/bank/confirm", json=body, headers=BANK_HEADERS)
    assert response.status_code == 409
    assert entry_count(session) == 2


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
    received, paid_in = response.json()
    assert received["reference"] == f"CONTRIB-{contribution.id}"
    assert [
        (line["account_type"], line["amount_kobo"]) for line in received["lines"]
    ] == [("bank_clearing", 500000), ("member_wallet", -500000)]
    assert paid_in["reference"] == f"CONTRIB-{contribution.id}-POT"
    assert [
        (line["account_type"], line["amount_kobo"]) for line in paid_in["lines"]
    ] == [("member_wallet", 500000), ("circle_pot", -500000)]
