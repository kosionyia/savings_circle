from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models.contribution import Contribution
from app.models.user import User
from app.schemas.contributions import ContributeIn, ContributionOut
from app.services.db import get_session
from app.services.dependency import get_current_user
from app.services.helpers import get_circle_or_404, require_membership

router = APIRouter( tags=["Contributions"])


@router.post(
    "/circles/{circle_id}/contributions",
    response_model=ContributionOut,
    status_code=status.HTTP_201_CREATED,
)
def record_contribution(
    circle_id: int,
    body: ContributeIn,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    circle = get_circle_or_404(session, circle_id)
    require_membership(session, current_user.id, circle_id)

    if body.amount != circle.weekly_amount:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Contribution must be the weekly amount of {circle.weekly_amount}",
        )

    contribution = Contribution(
        user_id=current_user.id,
        circle_id=circle.id,
        amount=body.amount,
        week=circle.current_week,
        confirmed=False,
    )
    session.add(contribution)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Already contributed this week",
        )
    session.refresh(contribution)
    return contribution


@router.get(
    "/circles/my_contributions",
    response_model=list[ContributionOut],
    status_code=status.HTTP_200_OK,
)
def my_contributions(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):

    return session.exec(
        select(Contribution)
        .where(
            Contribution.user_id == current_user.id,
        )
        .order_by(Contribution.week)
    ).all()
