from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models.contribution import Contribution
from app.models.ledger import (
    AccountType,
    JournalEntry,
    JournalLine,
    LedgerAccount,
    OwnerType,
)
from app.schemas.bank import BankConfirmIn, JournalEntryOut, JournalLineOut
from app.schemas.contributions import ContributionOut
from app.services.db import get_session
from app.services.dependency import require_bank_robot
from app.services.ledger import Line, get_or_create_account, post_entry

router = APIRouter(prefix="/bank", tags=["Bank"])


def _post_contribution(session: Session, contribution: Contribution) -> None:
    """Pass the member's money through their wallet on its way to the pot.

    Two entries rather than one straight bank -> pot entry, so every naira
    the member puts in appears on their wallet statement. The wallet nets
    to 0; bank_clearing and the pot end up exactly as a direct posting would
    leave them.
    """
    bank = get_or_create_account(
        session, OwnerType.SYSTEM, None, AccountType.BANK_CLEARING
    )
    wallet = get_or_create_account(
        session, OwnerType.USER, contribution.user_id, AccountType.MEMBER_WALLET
    )
    pot = get_or_create_account(
        session, OwnerType.CIRCLE, contribution.circle_id, AccountType.CIRCLE_POT
    )
    amount = contribution.amount_kobo

    # Posted first: a simultaneous confirmation of the same contribution
    # collides here, on the unique reference, before anything else is written
    post_entry(
        session,
        reference=f"CONTRIB-{contribution.id}",
        description=(
            f"Contribution {contribution.id}: received from the bank for "
            f"circle {contribution.circle_id}, week {contribution.week}"
        ),
        lines=[Line(bank.id, amount), Line(wallet.id, -amount)],
        created_by=None,
    )
    post_entry(
        session,
        reference=f"CONTRIB-{contribution.id}-POT",
        description=(
            f"Contribution {contribution.id}: paid into circle "
            f"{contribution.circle_id}'s pot for week {contribution.week}"
        ),
        lines=[Line(wallet.id, amount), Line(pot.id, -amount)],
        created_by=None,
    )


@router.post(
    "/confirm",
    response_model=ContributionOut,
    status_code=status.HTTP_200_OK,
)
def confirm_transfer(
    body: BankConfirmIn,
    session: Session = Depends(get_session),
    _: str = Depends(require_bank_robot),
):
    contribution = session.get(Contribution, body.contribution_id)
    if contribution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contribution not found",
        )

    already_confirmed = HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="This contribution is already confirmed",
    )
    if contribution.confirmed:
        raise already_confirmed

    contribution.confirmed = True
    session.add(contribution)
    try:
        _post_contribution(session, contribution)
        # The confirmed flag and both journal entries commit together, or not at all
        session.commit()
    except IntegrityError:
        # A simultaneous confirmation posted CONTRIB-{id} first
        session.rollback()
        raise already_confirmed

    session.refresh(contribution)
    return contribution


@router.get(
    "/ledger",
    response_model=list[JournalEntryOut],
    status_code=status.HTTP_200_OK,
)
def read_ledger(
    session: Session = Depends(get_session),
    _: str = Depends(require_bank_robot),
):
    entries = session.exec(select(JournalEntry).order_by(JournalEntry.id)).all()

    lines_by_entry: dict[int, list[JournalLineOut]] = defaultdict(list)
    rows = session.exec(
        select(JournalLine, LedgerAccount)
        .join(LedgerAccount, JournalLine.account_id == LedgerAccount.id)
        .order_by(JournalLine.id)
    ).all()
    for line, account in rows:
        lines_by_entry[line.entry_id].append(
            JournalLineOut(
                account_id=account.id,
                owner_type=account.owner_type,
                owner_id=account.owner_id,
                account_type=account.account_type,
                amount_kobo=line.amount_kobo,
            )
        )

    return [
        JournalEntryOut(
            id=entry.id,
            reference=entry.reference,
            description=entry.description,
            created_by=entry.created_by,
            created_at=entry.created_at,
            reverses_id=entry.reverses_id,
            lines=lines_by_entry[entry.id],
        )
        for entry in entries
    ]
