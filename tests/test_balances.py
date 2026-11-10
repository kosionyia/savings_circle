from datetime import datetime, timezone

import pytest
from sqlalchemy import func
from sqlmodel import select

from app.models.ledger import LedgerAccount
from app.services.ledger import pot_balance
from tests.conftest import (
    WEEKLY,
    advance,
    auth_headers,
    bank_confirm,
    contribute,
    schedule,
)


def read_balance(client, user, circle):
    return client.get(f"/circles/{circle.id}/balance", headers=auth_headers(user))


def pot_on_circle(client, user, circle) -> int:
    return client.get(f"/circles/{circle.id}", headers=auth_headers(user)).json()["pot_kobo"]


def test_unconfirmed_contributions_are_not_in_the_pot(client, admin, circle, members):
    contribute(client, circle, members[0])

    response = read_balance(client, admin, circle)
    assert response.status_code == 200
    assert response.json() == {"circle_id": circle.id, "pot_kobo": 0}
    assert pot_on_circle(client, admin, circle) == 0


def test_confirmed_contributions_fill_the_pot(client, admin, funded):
    assert read_balance(client, admin, funded).json()["pot_kobo"] == 3 * WEEKLY
    # The circle view reads the same ledger balance
    assert pot_on_circle(client, admin, funded) == 3 * WEEKLY


def test_pot_carries_over_until_it_is_paid_out(client, admin, funded, members):
    payout_id = schedule(client, admin, funded, members[0].id).json()["id"]
    advance(client, admin, payout_id, "approve")
    # Still scheduled/approved: nothing has left the pot yet
    assert read_balance(client, admin, funded).json()["pot_kobo"] == 3 * WEEKLY

    advance(client, admin, payout_id, "initiate")
    assert read_balance(client, admin, funded).json()["pot_kobo"] == 0


def test_reading_the_balance_creates_no_accounts(client, session, admin, circle):
    def account_count() -> int:
        return session.exec(select(func.count()).select_from(LedgerAccount)).one()

    before = account_count()
    assert read_balance(client, admin, circle).json()["pot_kobo"] == 0
    assert pot_on_circle(client, admin, circle) == 0
    assert account_count() == before


def test_members_can_read_the_balance(client, funded, members):
    response = read_balance(client, members[1], funded)
    assert response.status_code == 200
    assert response.json()["pot_kobo"] == 3 * WEEKLY


def test_outsiders_cannot_read_the_balance(client, make_user, funded):
    outsider = make_user(name="Tunde")
    assert read_balance(client, outsider, funded).status_code == 403


def test_unknown_circle_balance_is_404(client, admin):
    response = client.get("/circles/999999/balance", headers=auth_headers(admin))
    assert response.status_code == 404


def test_as_of_only_counts_entries_posted_before_it(client, session, circle, members):
    before_anything = datetime.now(timezone.utc)
    bank_confirm(client, contribute(client, circle, members[0]).json()["id"])
    cutoff = datetime.now(timezone.utc)
    bank_confirm(client, contribute(client, circle, members[1]).json()["id"])

    assert pot_balance(session, circle.id, as_of=before_anything) == 0
    assert pot_balance(session, circle.id, as_of=cutoff) == WEEKLY
    assert pot_balance(session, circle.id) == 2 * WEEKLY


def test_as_of_must_be_timezone_aware(session, circle):
    with pytest.raises(ValueError, match="timezone-aware"):
        pot_balance(session, circle.id, as_of=datetime(2026, 11, 1))
