from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import BigInteger, cast, func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.models.ledger import (
    AccountType,
    JournalEntry,
    JournalLine,
    LedgerAccount,
    OwnerType,
)


class LedgerError(ValueError):
    """An entry broke a ledger rule; nothing was written."""


@dataclass(frozen=True)
class Line:
    account_id: int
    amount_kobo: int


def find_account(
    session: Session,
    owner_type: OwnerType,
    owner_id: int | None,
    account_type: AccountType,
    currency: str = "NGN",
) -> LedgerAccount | None:
    """Look an account up without creating it; safe to use on read-only paths."""
    return session.exec(
        select(LedgerAccount).where(
            LedgerAccount.owner_type == owner_type,
            # "= NULL" never matches in SQL, so system accounts need "IS NULL"
            col(LedgerAccount.owner_id).is_(None)
            if owner_id is None
            else LedgerAccount.owner_id == owner_id,
            LedgerAccount.account_type == account_type,
            LedgerAccount.currency == currency,
        )
    ).first()


def get_or_create_account(
    session: Session,
    owner_type: OwnerType,
    owner_id: int | None,
    account_type: AccountType,
    currency: str = "NGN",
) -> LedgerAccount:
    if owner_type == OwnerType.SYSTEM and owner_id is not None:
        raise LedgerError("System accounts cannot have an owner_id")
    if owner_type != OwnerType.SYSTEM and owner_id is None:
        raise LedgerError(f"{owner_type.value} accounts need an owner_id")

    account = find_account(session, owner_type, owner_id, account_type, currency)
    if account is not None:
        return account

    account = LedgerAccount(
        owner_type=owner_type,
        owner_id=owner_id,
        account_type=account_type,
        currency=currency,
    )
    try:
        # Savepoint: if another request created this account first, only
        # this insert is undone and the caller's transaction carries on
        with session.begin_nested():
            session.add(account)
    except IntegrityError:
        account = find_account(session, owner_type, owner_id, account_type, currency)
    return account


def _require_aware(as_of: datetime | None) -> None:
    # A naive time would be read in the DB session's timezone, which
    # silently shifts the cut-off
    if as_of is not None and as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")


def account_balance(
    session: Session,
    account_id: int,
    as_of: datetime | None = None,
) -> int:
    """Sum of the account's lines: positive = debit, negative = credit.

    With as_of, only entries posted strictly before that moment count, so
    account_balance(session, id, as_of=start) is the opening balance at start.
    """
    # SUM over BIGINT returns NUMERIC (a Decimal in Python); cast back to int
    total = func.coalesce(func.sum(JournalLine.amount_kobo), 0)
    query = (
        select(cast(total, BigInteger))
        .select_from(JournalLine)
        .where(JournalLine.account_id == account_id)
    )
    _require_aware(as_of)
    if as_of is not None:
        query = query.join(JournalEntry, JournalLine.entry_id == JournalEntry.id).where(
            JournalEntry.created_at < as_of
        )
    return session.exec(query).one()


def pot_balance(
    session: Session,
    circle_id: int,
    as_of: datetime | None = None,
) -> int:
    """Confirmed money held in a circle's pot, in kobo (zero or more).

    The pot records money owed to the circle, so it carries a credit
    (negative) balance; flipping it gives the amount held. Read-only: a
    circle whose pot account doesn't exist yet simply holds 0.
    """
    _require_aware(as_of)
    pot = find_account(session, OwnerType.CIRCLE, circle_id, AccountType.CIRCLE_POT)
    if pot is None:
        return 0
    return -account_balance(session, pot.id, as_of)


def post_entry(
    session: Session,
    reference: str,
    description: str,
    lines: list[Line],
    created_by: int | None,
    reverses_id: int | None = None,
) -> JournalEntry:
    """Validate and write one balanced journal entry.

    Flushes but never commits: the caller commits, so the entry and the
    business change it records succeed or fail together.
    """
    if len(lines) < 2:
        raise LedgerError("An entry needs at least 2 lines")

    for line in lines:
        # type() rather than isinstance(): rejects floats and also bools,
        # since isinstance(True, int) is True
        if type(line.amount_kobo) is not int:
            raise LedgerError(
                f"amount_kobo must be an int, got {type(line.amount_kobo).__name__}"
            )
        if line.amount_kobo == 0:
            raise LedgerError("Lines cannot have a zero amount")

    total = sum(line.amount_kobo for line in lines)
    if total != 0:
        raise LedgerError(f"Entry does not balance: lines sum to {total} kobo")

    account_ids = {line.account_id for line in lines}
    accounts = session.exec(
        select(LedgerAccount).where(col(LedgerAccount.id).in_(account_ids))
    ).all()
    missing = account_ids - {account.id for account in accounts}
    if missing:
        raise LedgerError(f"Unknown account ids: {sorted(missing)}")

    currencies = {account.currency for account in accounts}
    if len(currencies) > 1:
        raise LedgerError(f"Entry mixes currencies: {sorted(currencies)}")

    entry = JournalEntry(
        reference=reference,
        description=description,
        created_by=created_by,
        reverses_id=reverses_id,
    )
    session.add(entry)
    session.flush()

    for line in lines:
        session.add(
            JournalLine(
                entry_id=entry.id,
                account_id=line.account_id,
                amount_kobo=line.amount_kobo,
            )
        )
    session.flush()
    return entry


def reverse_entry(
    session: Session,
    entry_id: int,
    created_by: int | None,
    description: str | None = None,
) -> JournalEntry:
    """Cancel an entry by posting its mirror image; the original is untouched.

    Flushes but never commits, like post_entry.
    """
    original = session.get(JournalEntry, entry_id)
    if original is None:
        raise LedgerError(f"Journal entry {entry_id} not found")
    if original.reverses_id is not None:
        raise LedgerError(
            f"Entry {entry_id} is itself a reversal; post a new entry instead"
        )

    already_reversed = session.exec(
        select(JournalEntry).where(JournalEntry.reverses_id == entry_id)
    ).first()
    if already_reversed is not None:
        raise LedgerError(
            f"Entry {entry_id} was already reversed by entry {already_reversed.id}"
        )

    original_lines = session.exec(
        select(JournalLine).where(JournalLine.entry_id == entry_id)
    ).all()

    # Two simultaneous reversals can both pass the check above; the unique
    # reverses_id column then rejects the second one at flush
    return post_entry(
        session,
        reference=f"{original.reference}-REV",
        description=description or f"Reversal of {original.reference}",
        lines=[Line(line.account_id, -line.amount_kobo) for line in original_lines],
        created_by=created_by,
        reverses_id=original.id,
    )
