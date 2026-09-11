from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models.contribution import Contribution
from app.models.payout import Payout
from app.models.user import User
from app.schemas.payouts import PayoutIn, PayoutOut
from app.services.db import get_session
from app.services.dependency import require_admin
from app.services.helpers import (
    assert_circle_admin,
    get_circle_or_404,
    next_recipient,
)

router = APIRouter(prefix="/circles/{circle_id}", tags=["Payouts"])


@router.post(
    "/payouts",
    response_model=PayoutOut,
    status_code=status.HTTP_201_CREATED,
)
def declare_payout(
    circle_id: int,
    body: PayoutIn,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    circle = get_circle_or_404(session, circle_id)
    assert_circle_admin(current_user, circle)

    expected = next_recipient(session, circle)
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This circle has no members to pay",
        )

    if body.user_id != expected.user_id:
        person = session.get(User, expected.user_id)
        name = person.name if person else f"user {expected.user_id}"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This week's payout must go to {name} "
                f"(user {expected.user_id}), not user {body.user_id}"
            ),
        )

    pot = sum(
        row.amount
        for row in session.exec(
            select(Contribution).where(
                Contribution.circle_id == circle.id,
                Contribution.week == circle.current_week,
            )
        ).all()
    )

    payout = Payout(
        circle_id=circle.id,
        user_id=body.user_id,
        amount=pot,
        week=circle.current_week,
    )
    session.add(payout)
    circle.current_week += 1
    session.add(circle)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This week has already been paid out",
        )
    session.refresh(payout)
    return payout
