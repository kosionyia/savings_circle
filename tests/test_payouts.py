import itertools

import pytest
from sqlalchemy import func
from sqlmodel import select

from app.config import BANK_API_KEY
from app.models.circles import Circle
from app.models.ledger import AccountType, JournalEntry, JournalLine, OwnerType
from app.models.membership import Membership
from app.models.payout import Payout, PayoutStatus
from app.models.user import UserRole
from app.services.idempotency import REPLAY_HEADER
from app.services.ledger import account_balance, get_or_create_account
from tests.conftest import auth_headers

WEEKLY = 500000
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
        response = client.post(
            f"/circles/{circle.id}/contributions",
            json={"amount_kobo": WEEKLY},
            headers={**auth_headers(member), "Idempotency-Key": new_key()},
        )
        client.post(
            "/bank/confirm",
            json={"contribution_id": response.json()["id"]},
            headers={"X-API-Key": BANK_API_KEY},
        )
    return circle


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


def balances(session, circle, user_id):
    pot = get_or_create_account(session, OwnerType.CIRCLE, circle.id, AccountType.CIRCLE_POT)
    wallet = get_or_create_account(session, OwnerType.USER, user_id, AccountType.MEMBER_WALLET)
    bank = get_or_create_account(session, OwnerType.SYSTEM, None, AccountType.BANK_CLEARING)
    return {
        "pot": account_balance(session, pot.id),
        "wallet": account_balance(session, wallet.id),
        "bank": account_balance(session, bank.id),
    }


def trial_balance(session) -> int:
    return session.exec(
        select(func.coalesce(func.sum(JournalLine.amount_kobo), 0))
    ).one()


# --- scheduling -----------------------------------------------------------


def test_schedule_creates_a_scheduled_payout(client, session, admin, funded, members):
    response = schedule(client, admin, funded, members[0].id)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "scheduled"
    assert body["amount_kobo"] is None  # decided at initiate
    assert body["week"] == 1
    session.refresh(funded)
    assert funded.current_week == 1  # the week only moves on confirm


def test_schedule_must_follow_the_turn_order(client, admin, funded, members):
    response = schedule(client, admin, funded, members[1].id)

    assert response.status_code == 409
    assert "must go to Amaka" in response.json()["detail"]


def test_a_turn_can_only_have_one_live_payout(client, admin, funded, members):
    schedule(client, admin, funded, members[0].id)
    response = schedule(client, admin, funded, members[0].id)

    assert response.status_code == 409
    assert response.json()["detail"] == "This week already has a payout"


# --- the happy path -------------------------------------------------------


def test_full_payout_moves_the_pot_to_the_member(
    client, session, admin, funded, members
):
    amaka = members[0]
    assert balances(session, funded, amaka.id) == {
        "pot": -1500000, "wallet": 0, "bank": 1500000
    }
    payout_id = schedule(client, admin, funded, amaka.id).json()["id"]

    advance(client, admin, payout_id, "approve")
    assert balances(session, funded, amaka.id)["pot"] == -1500000  # nothing posted

    initiated = advance(client, admin, payout_id, "initiate").json()
    assert initiated["status"] == "initiated"
    assert initiated["amount_kobo"] == 1500000
    assert balances(session, funded, amaka.id) == {
        "pot": 0, "wallet": -1500000, "bank": 1500000
    }

    confirmed = advance(client, admin, payout_id, "confirm").json()
    assert confirmed["status"] == "confirmed"
    assert balances(session, funded, amaka.id) == {"pot": 0, "wallet": 0, "bank": 0}

    session.refresh(funded)
    assert funded.current_week == 2
    assert trial_balance(session) == 0


def test_next_week_goes_to_the_next_member(client, session, admin, funded, members):
    payout_id = schedule(client, admin, funded, members[0].id).json()["id"]
    advance(client, admin, payout_id, "approve", "initiate", "confirm")

    response = schedule(client, admin, funded, members[1].id)
    assert response.status_code == 201
    assert response.json()["week"] == 2


# --- failure and reversal -------------------------------------------------


def test_reversed_payout_restores_the_pot(client, session, admin, funded, members):
    amaka = members[0]
    payout_id = schedule(client, admin, funded, amaka.id).json()["id"]
    advance(client, admin, payout_id, "approve", "initiate", "fail")
    assert balances(session, funded, amaka.id)["pot"] == 0  # fail posts nothing

    reversed_ = advance(client, admin, payout_id, "reverse").json()

    assert reversed_["status"] == "reversed"
    assert balances(session, funded, amaka.id) == {
        "pot": -1500000, "wallet": 0, "bank": 1500000
    }
    session.refresh(funded)
    assert funded.current_week == 1
    assert trial_balance(session) == 0


def test_reversal_leaves_the_initiate_entry_untouched(
    client, session, admin, funded, members
):
    payout_id = schedule(client, admin, funded, members[0].id).json()["id"]
    advance(client, admin, payout_id, "approve", "initiate", "fail", "reverse")

    initiate = session.exec(
        select(JournalEntry).where(JournalEntry.reference == f"PAYOUT-{payout_id}-INITIATE")
    ).one()
    reversal = session.exec(
        select(JournalEntry).where(JournalEntry.reverses_id == initiate.id)
    ).one()
    amounts = lambda entry_id: session.exec(
        select(JournalLine.amount_kobo)
        .where(JournalLine.entry_id == entry_id)
        .order_by(JournalLine.id)
    ).all()

    assert amounts(initiate.id) == [1500000, -1500000]
    assert amounts(reversal.id) == [-1500000, 1500000]


def test_a_reversed_turn_can_be_scheduled_again(client, session, admin, funded, members):
    first = schedule(client, admin, funded, members[0].id).json()["id"]
    advance(client, admin, first, "approve", "initiate", "fail", "reverse")

    retry = schedule(client, admin, funded, members[0].id)
    assert retry.status_code == 201
    second = retry.json()["id"]
    advance(client, admin, second, "approve", "initiate", "confirm")

    assert session.get(Payout, first).status == PayoutStatus.REVERSED
    assert balances(session, funded, members[0].id) == {"pot": 0, "wallet": 0, "bank": 0}
    assert trial_balance(session) == 0


# --- illegal moves --------------------------------------------------------


@pytest.mark.parametrize(
    "done, action",
    [
        ([], "initiate"),  # skip approval
        ([], "confirm"),
        ([], "fail"),
        ([], "reverse"),
        (["approve"], "approve"),  # twice
        (["approve"], "confirm"),  # skip initiate
        (["approve", "initiate"], "reverse"),  # only failed payouts reverse
        (["approve", "initiate", "confirm"], "fail"),  # too late
        (["approve", "initiate", "fail"], "confirm"),
        (["approve", "initiate", "fail", "reverse"], "reverse"),
    ],
)
def test_illegal_transitions_are_rejected(
    client, session, admin, funded, members, done, action
):
    payout_id = schedule(client, admin, funded, members[0].id).json()["id"]
    advance(client, admin, payout_id, *done)
    before = session.exec(select(func.count()).select_from(JournalEntry)).one()

    response = act(client, admin, payout_id, action)

    assert response.status_code == 409
    assert f"Cannot {action}" in response.json()["detail"]
    assert session.exec(select(func.count()).select_from(JournalEntry)).one() == before


def test_initiate_with_an_empty_pot_is_rejected(client, session, admin, circle, members):
    payout_id = schedule(client, admin, circle, members[0].id).json()["id"]
    advance(client, admin, payout_id, "approve")

    response = act(client, admin, payout_id, "initiate")

    assert response.status_code == 409
    assert "no confirmed contributions" in response.json()["detail"]
    assert session.get(Payout, payout_id).status == PayoutStatus.APPROVED


# --- idempotency and access -----------------------------------------------


def test_retried_action_is_replayed_not_rejected(client, session, admin, funded, members):
    payout_id = schedule(client, admin, funded, members[0].id).json()["id"]
    advance(client, admin, payout_id, "approve")

    first = act(client, admin, payout_id, "initiate", key="initiate-1")
    retry = act(client, admin, payout_id, "initiate", key="initiate-1")

    assert retry.status_code == 200  # not 409 "Cannot initiate"
    assert retry.headers[REPLAY_HEADER] == "true"
    assert retry.json() == first.json()
    initiates = session.exec(
        select(func.count()).select_from(JournalEntry).where(
            JournalEntry.reference == f"PAYOUT-{payout_id}-INITIATE"
        )
    ).one()
    assert initiates == 1


def test_actions_require_an_idempotency_key(client, admin, funded, members):
    payout_id = schedule(client, admin, funded, members[0].id).json()["id"]

    response = client.post(f"/payouts/{payout_id}/approve", headers=auth_headers(admin))
    assert response.status_code == 422


def test_members_cannot_move_payouts(client, admin, funded, members):
    payout_id = schedule(client, admin, funded, members[0].id).json()["id"]

    response = act(client, members[0], payout_id, "approve")
    assert response.status_code == 403


def test_another_circles_admin_cannot_move_payouts(
    client, make_user, admin, funded, members
):
    payout_id = schedule(client, admin, funded, members[0].id).json()["id"]
    other_admin = make_user(name="Tunde", role=UserRole.ADMIN)

    response = act(client, other_admin, payout_id, "approve")
    assert response.status_code == 403


def test_unknown_payout_is_404(client, admin):
    response = act(client, admin, 999999, "approve")
    assert response.status_code == 404
