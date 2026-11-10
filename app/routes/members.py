from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from app.models.ledger import AccountType, OwnerType
from app.models.user import User, UserRole
from app.schemas.members import MemberStatement, StatementLineOut
from app.services.db import get_session
from app.services.dependency import get_current_user
from app.services.ledger import Statement, account_statement, find_account

router = APIRouter(prefix="/members", tags=["Members"])

# Ajo's members are in Nigeria, so a "day" on a statement is a Lagos day
LAGOS = ZoneInfo("Africa/Lagos")


def lagos_period(
    from_date: date | None, to_date: date
) -> tuple[datetime | None, datetime]:
    """Turn inclusive Lagos dates into a half-open [start, end) UTC-aware range.

    to_date is inclusive, so the range ends at midnight at the start of the
    following day.
    """
    start = datetime.combine(from_date, time.min, LAGOS) if from_date else None
    end = datetime.combine(to_date + timedelta(days=1), time.min, LAGOS)
    return start, end


@router.get(
    "/{member_id}/statement",
    response_model=MemberStatement,
    status_code=status.HTTP_200_OK,
)
def member_statement(
    member_id: int,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    # Checked before the 404 so a member can't probe which user ids exist
    if current_user.id != member_id and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only see your own statement",
        )
    if session.get(User, member_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found",
        )

    to_date = to_date or datetime.now(LAGOS).date()
    if from_date is not None and from_date > to_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="'from' must be on or before 'to'",
        )
    start, end = lagos_period(from_date, to_date)

    # Read-only: a member with no wallet yet just has an empty statement
    wallet = find_account(session, OwnerType.USER, member_id, AccountType.MEMBER_WALLET)
    if wallet is None:
        statement = Statement(opening_balance_kobo=0, lines=[], closing_balance_kobo=0)
    else:
        statement = account_statement(session, wallet.id, start, end)

    # The wallet records money we owe the member, so it carries a credit
    # (negative) balance; flip every figure so the member reads money held
    # for them as positive
    return MemberStatement(
        member_id=member_id,
        from_date=from_date,
        to_date=to_date,
        opening_balance_kobo=-statement.opening_balance_kobo,
        lines=[
            StatementLineOut(
                entry_id=line.entry_id,
                reference=line.reference,
                description=line.description,
                posted_at=line.posted_at,
                amount_kobo=-line.amount_kobo,
                balance_kobo=-line.balance_kobo,
            )
            for line in statement.lines
        ],
        closing_balance_kobo=-statement.closing_balance_kobo,
    )
