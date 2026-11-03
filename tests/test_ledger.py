import pytest
from sqlalchemy import func, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlmodel import select

from app.models.ledger import (
    AccountType,
    JournalEntry,
    JournalLine,
    LedgerAccount,
    OwnerType,
)
from app.services.ledger import (
    LedgerError,
    Line,
    get_or_create_account,
    post_entry,
    reverse_entry,
)


@pytest.fixture
def user(make_user):
    return make_user(name="Ade")


@pytest.fixture
def bank(session):
    return get_or_create_account(
        session, OwnerType.SYSTEM, None, AccountType.BANK_CLEARING
    )


@pytest.fixture
def pot(session):
    return get_or_create_account(session, OwnerType.CIRCLE, 1, AccountType.CIRCLE_POT)


@pytest.fixture
def contribution(session, user, bank, pot):
    """A posted ₦5,000 contribution: bank +500000, pot −500000."""
    return post_entry(
        session,
        reference="CONTRIB-1",
        description="Amaka week 1",
        lines=[Line(bank.id, 500000), Line(pot.id, -500000)],
        created_by=user.id,
    )


def balance(session, account_id: int) -> int:
    return session.exec(
        select(func.coalesce(func.sum(JournalLine.amount_kobo), 0)).where(
            JournalLine.account_id == account_id
        )
    ).one()


def entry_count(session) -> int:
    return session.exec(select(func.count()).select_from(JournalEntry)).one()


# --- accounts -------------------------------------------------------------


def test_get_or_create_returns_the_same_account(session, bank):
    again = get_or_create_account(
        session, OwnerType.SYSTEM, None, AccountType.BANK_CLEARING
    )
    assert again.id == bank.id


def test_different_owners_get_different_accounts(session):
    pot_1 = get_or_create_account(session, OwnerType.CIRCLE, 1, AccountType.CIRCLE_POT)
    pot_2 = get_or_create_account(session, OwnerType.CIRCLE, 2, AccountType.CIRCLE_POT)
    assert pot_1.id != pot_2.id


@pytest.mark.parametrize(
    "owner_type, owner_id",
    [
        (OwnerType.SYSTEM, 1),  # system accounts have no owner
        (OwnerType.CIRCLE, None),  # circle and user accounts must have one
        (OwnerType.USER, None),
    ],
)
def test_owner_rules(session, owner_type, owner_id):
    with pytest.raises(LedgerError):
        get_or_create_account(session, owner_type, owner_id, AccountType.FEES)


def test_database_rejects_duplicate_system_account(session, bank):
    # NULLS NOT DISTINCT: two (system, NULL, bank_clearing) rows are duplicates
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                LedgerAccount(
                    owner_type=OwnerType.SYSTEM,
                    owner_id=None,
                    account_type=AccountType.BANK_CLEARING,
                )
            )


# --- post_entry -----------------------------------------------------------


def test_balanced_entry_is_posted(session, contribution, bank, pot):
    assert contribution.id is not None
    assert balance(session, bank.id) == 500000
    assert balance(session, pot.id) == -500000


def test_entry_with_more_than_two_lines(session, user, bank, pot):
    fees = get_or_create_account(session, OwnerType.SYSTEM, None, AccountType.FEES)
    post_entry(
        session,
        reference="SPLIT-1",
        description="contribution with a fee",
        lines=[Line(bank.id, 500000), Line(pot.id, -480000), Line(fees.id, -20000)],
        created_by=user.id,
    )
    assert balance(session, fees.id) == -20000


@pytest.mark.parametrize(
    "amounts, message",
    [
        ([500000], "at least 2 lines"),
        ([], "at least 2 lines"),
        ([5000.0, -5000.0], "must be an int, got float"),
        ([True, -1], "must be an int, got bool"),
        ([0, 0], "zero amount"),
        ([500000, -400000], "does not balance"),
    ],
)
def test_invalid_entries_are_rejected(session, user, bank, pot, amounts, message):
    accounts = [bank.id, pot.id]
    lines = [Line(accounts[i % 2], amount) for i, amount in enumerate(amounts)]

    with pytest.raises(LedgerError, match=message):
        post_entry(session, "BAD", "bad", lines, created_by=user.id)
    assert entry_count(session) == 0


def test_unknown_account_is_rejected(session, user, bank):
    with pytest.raises(LedgerError, match="Unknown account ids: \\[999999\\]"):
        post_entry(
            session,
            "BAD",
            "bad",
            [Line(bank.id, 500000), Line(999999, -500000)],
            created_by=user.id,
        )
    assert entry_count(session) == 0


def test_mixed_currencies_are_rejected(session, user, bank):
    usd_pot = get_or_create_account(
        session, OwnerType.CIRCLE, 1, AccountType.CIRCLE_POT, currency="USD"
    )
    with pytest.raises(LedgerError, match="mixes currencies"):
        post_entry(
            session,
            "BAD",
            "bad",
            [Line(bank.id, 500000), Line(usd_pot.id, -500000)],
            created_by=user.id,
        )


def test_duplicate_reference_is_rejected(session, contribution, user, bank, pot):
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            post_entry(
                session,
                reference="CONTRIB-1",
                description="same event posted twice",
                lines=[Line(bank.id, 500000), Line(pot.id, -500000)],
                created_by=user.id,
            )
    assert entry_count(session) == 1


def test_all_lines_sum_to_zero_after_many_entries(session, user, bank, pot):
    wallet = get_or_create_account(
        session, OwnerType.USER, user.id, AccountType.MEMBER_WALLET
    )
    for week in range(1, 4):
        post_entry(
            session,
            f"CONTRIB-{week}",
            "contribution",
            [Line(bank.id, 500000), Line(pot.id, -500000)],
            created_by=user.id,
        )
    post_entry(
        session,
        "PAYOUT-1-INIT",
        "payout initiated",
        [Line(pot.id, 1500000), Line(wallet.id, -1500000)],
        created_by=user.id,
    )
    post_entry(
        session,
        "PAYOUT-1-CONFIRM",
        "payout confirmed",
        [Line(wallet.id, 1500000), Line(bank.id, -1500000)],
        created_by=user.id,
    )

    total = session.exec(select(func.sum(JournalLine.amount_kobo))).one()
    assert total == 0
    assert balance(session, pot.id) == 0
    assert balance(session, wallet.id) == 0


# --- reverse_entry --------------------------------------------------------


def test_reversal_restores_balances(session, contribution, user, bank, pot):
    reversal = reverse_entry(session, contribution.id, created_by=user.id)

    assert reversal.reverses_id == contribution.id
    assert reversal.reference == "CONTRIB-1-REV"
    assert balance(session, bank.id) == 0
    assert balance(session, pot.id) == 0


def test_reversal_leaves_original_untouched(session, contribution, user):
    reverse_entry(session, contribution.id, created_by=user.id)

    original_lines = session.exec(
        select(JournalLine.amount_kobo)
        .where(JournalLine.entry_id == contribution.id)
        .order_by(JournalLine.id)
    ).all()
    assert original_lines == [500000, -500000]
    assert entry_count(session) == 2


def test_entry_cannot_be_reversed_twice(session, contribution, user):
    reverse_entry(session, contribution.id, created_by=user.id)

    with pytest.raises(LedgerError, match="already reversed"):
        reverse_entry(session, contribution.id, created_by=user.id)


def test_reversal_cannot_be_reversed(session, contribution, user):
    reversal = reverse_entry(session, contribution.id, created_by=user.id)

    with pytest.raises(LedgerError, match="itself a reversal"):
        reverse_entry(session, reversal.id, created_by=user.id)


def test_reversing_missing_entry_is_rejected(session, user):
    with pytest.raises(LedgerError, match="not found"):
        reverse_entry(session, 999999, created_by=user.id)


# --- immutability trigger -------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE journal_line SET amount_kobo = 300000",
        "DELETE FROM journal_line",
        "TRUNCATE journal_line",
        "UPDATE journal_entry SET description = 'edited'",
        "DELETE FROM journal_entry",
        "TRUNCATE journal_entry CASCADE",
    ],
)
def test_database_blocks_changes_to_history(session, contribution, sql):
    # The savepoint keeps the outer test transaction usable after the error
    with pytest.raises(DBAPIError, match="append-only"):
        with session.begin_nested():
            session.execute(text(sql))
