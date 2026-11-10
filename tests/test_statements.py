from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func
from sqlmodel import select

from app.models.contribution import Contribution
from app.models.ledger import AccountType, LedgerAccount, OwnerType
from app.routes.members import LAGOS, lagos_period
from app.services.ledger import account_balance, account_statement, find_account
from tests.conftest import WEEKLY, advance, auth_headers, schedule

POT = 3 * WEEKLY  # three members' contributions


def get_statement(client, viewer, member_id, **params):
    return client.get(
        f"/members/{member_id}/statement", params=params, headers=auth_headers(viewer)
    )


def rows(body) -> list[tuple[str, int, int]]:
    return [(l["reference"], l["amount_kobo"], l["balance_kobo"]) for l in body["lines"]]


def contribution_id(session, member) -> int:
    return session.exec(
        select(Contribution.id).where(Contribution.user_id == member.id)
    ).one()


def today() -> date:
    return datetime.now(LAGOS).date()


@pytest.fixture
def amaka(members):
    return members[0]  # first in the turn order, so she collects week 1


@pytest.fixture
def initiated(client, admin, funded, amaka):
    """Amaka's payout is on its way: the pot has moved into her wallet."""
    payout_id = schedule(client, admin, funded, amaka.id).json()["id"]
    advance(client, admin, payout_id, "approve", "initiate")
    return payout_id


# --- what a statement shows -------------------------------------------------


def test_statement_shows_money_in_and_out(client, session, admin, initiated, amaka):
    advance(client, admin, initiated, "confirm")
    c = contribution_id(session, amaka)

    response = get_statement(client, amaka, amaka.id)
    assert response.status_code == 200
    body = response.json()
    assert rows(body) == [
        (f"CONTRIB-{c}", WEEKLY, WEEKLY),  # received from the bank
        (f"CONTRIB-{c}-POT", -WEEKLY, 0),  # paid into the pot
        (f"PAYOUT-{initiated}-INITIATE", POT, POT),  # the pot is hers
        (f"PAYOUT-{initiated}-CONFIRM", -POT, 0),  # sent to her bank
    ]
    assert body["opening_balance_kobo"] == 0
    assert body["closing_balance_kobo"] == 0
    assert body["from_date"] is None
    assert body["to_date"] == today().isoformat()


def test_a_member_still_waiting_sees_their_contribution(client, session, funded, members):
    chinedu = members[1]
    c = contribution_id(session, chinedu)

    body = get_statement(client, chinedu, chinedu.id).json()
    assert rows(body) == [(f"CONTRIB-{c}", WEEKLY, WEEKLY), (f"CONTRIB-{c}-POT", -WEEKLY, 0)]


def test_money_in_flight_shows_as_held_for_the_member(client, initiated, amaka):
    body = get_statement(client, amaka, amaka.id).json()
    assert body["closing_balance_kobo"] == POT


def test_a_reversed_payout_shows_the_money_going_back(client, admin, initiated, amaka):
    advance(client, admin, initiated, "fail", "reverse")

    body = get_statement(client, amaka, amaka.id).json()
    assert rows(body)[-2:] == [
        (f"PAYOUT-{initiated}-INITIATE", POT, POT),
        (f"PAYOUT-{initiated}-INITIATE-REV", -POT, 0),
    ]
    assert body["closing_balance_kobo"] == 0


def test_a_member_with_no_wallet_gets_an_empty_statement(client, session, admin):
    def account_count() -> int:
        return session.exec(select(func.count()).select_from(LedgerAccount)).one()

    before = account_count()
    body = get_statement(client, admin, admin.id).json()
    assert body["lines"] == []
    assert body["opening_balance_kobo"] == body["closing_balance_kobo"] == 0
    assert account_count() == before  # reading created nothing


# --- the period: opening and closing balances -------------------------------


def wallet_id(session, member) -> int:
    return find_account(session, OwnerType.USER, member.id, AccountType.MEMBER_WALLET).id


def test_opening_balance_carries_in_everything_before_start(
    client, session, admin, initiated, amaka
):
    cutoff = datetime.now(timezone.utc)
    advance(client, admin, initiated, "confirm")

    statement = account_statement(session, wallet_id(session, amaka), start=cutoff)
    # Raw ledger signs here: the wallet owes Amaka the pot, a credit
    assert statement.opening_balance_kobo == -POT
    assert [(l.reference, l.amount_kobo, l.balance_kobo) for l in statement.lines] == [
        (f"PAYOUT-{initiated}-CONFIRM", POT, 0)
    ]
    assert statement.closing_balance_kobo == 0


def test_closing_balance_matches_the_balance_at_end(
    client, session, admin, initiated, amaka
):
    cutoff = datetime.now(timezone.utc)
    advance(client, admin, initiated, "confirm")
    wallet = wallet_id(session, amaka)

    statement = account_statement(session, wallet, end=cutoff)
    assert statement.lines[-1].reference == f"PAYOUT-{initiated}-INITIATE"
    assert statement.closing_balance_kobo == account_balance(session, wallet, as_of=cutoff)
    assert statement.closing_balance_kobo == -POT


def test_a_period_after_the_activity_carries_the_balance_with_no_lines(
    client, initiated, amaka
):
    tomorrow = (today() + timedelta(days=1)).isoformat()
    body = get_statement(client, amaka, amaka.id, **{"from": tomorrow, "to": tomorrow}).json()
    assert body["lines"] == []
    assert body["opening_balance_kobo"] == body["closing_balance_kobo"] == POT


def test_a_period_before_the_activity_is_empty(client, initiated, amaka):
    yesterday = (today() - timedelta(days=1)).isoformat()
    body = get_statement(client, amaka, amaka.id, to=yesterday).json()
    assert body["lines"] == []
    assert body["opening_balance_kobo"] == body["closing_balance_kobo"] == 0


def test_today_includes_todays_lines(client, initiated, amaka):
    body = get_statement(
        client, amaka, amaka.id, **{"from": today().isoformat(), "to": today().isoformat()}
    ).json()
    assert len(body["lines"]) == 3
    assert body["opening_balance_kobo"] == 0


def test_from_after_to_is_rejected(client, amaka):
    response = get_statement(client, amaka, amaka.id, **{"from": "2026-11-30", "to": "2026-11-01"})
    assert response.status_code == 422


def test_dates_are_lagos_days():
    start, end = lagos_period(date(2026, 11, 1), date(2026, 11, 30))
    # Lagos is UTC+1, so its day starts at 23:00 UTC the evening before
    assert start == datetime(2026, 10, 31, 23, 0, tzinfo=timezone.utc)
    # `to` is inclusive: the range runs up to the start of 1 December
    assert end == datetime(2026, 11, 30, 23, 0, tzinfo=timezone.utc)


# --- who can see a statement ------------------------------------------------


def test_members_cannot_see_each_others_statements(client, funded, members):
    assert get_statement(client, members[1], members[0].id).status_code == 403


def test_admins_can_see_any_statement(client, admin, funded, amaka):
    response = get_statement(client, admin, amaka.id)
    assert response.status_code == 200
    assert len(response.json()["lines"]) == 2


def test_unknown_member_is_404_for_admins(client, admin):
    assert get_statement(client, admin, 999999).status_code == 404


def test_unknown_member_is_403_for_members(client, amaka):
    # A member can't use the statement endpoint to find out which ids exist
    assert get_statement(client, amaka, 999999).status_code == 403
