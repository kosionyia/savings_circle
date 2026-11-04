from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models.contribution import Contribution
from app.models.user import User
from app.schemas.contributions import ContributeIn, ContributionOut
from app.services.db import get_session
from app.services.dependency import get_current_user
from app.services.helpers import get_circle_or_404, require_membership
from app.services.idempotency import Idempotency, claim, request_hash, store_response

router = APIRouter(tags=["Contributions"])


CONTRIBUTE_ENDPOINT = "POST /circles/{circle_id}/contributions"


@router.post(
    "/circles/{circle_id}/contributions",
    response_model=ContributionOut,
    status_code=status.HTTP_201_CREATED,
)
def record_contribution(
    circle_id: int,
    body: ContributeIn,
    request: Request,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=255,
        description="A unique ID (e.g. a UUID) per contribution; reuse it on retries",
    ),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    idem = Idempotency(
        key=idempotency_key,
        user_id=current_user.id,
        endpoint=CONTRIBUTE_ENDPOINT,
        fingerprint=request_hash(
            request.method, request.url.path, body.model_dump(mode="json")
        ),
    )
    replay = claim(session, idem)
    if replay is not None:
        return replay

    try:
        contribution = _create_contribution(session, circle_id, body, current_user)
    except HTTPException:
        # Errors are not stored: release the key so a corrected retry can run
        session.rollback()
        raise

    response_body = ContributionOut.model_validate(contribution).model_dump(mode="json")
    response = store_response(session, idem, status.HTTP_201_CREATED, response_body)
    # The contribution and the stored response commit together
    session.commit()
    return response


def _create_contribution(
    session: Session,
    circle_id: int,
    body: ContributeIn,
    current_user: User,
) -> Contribution:
    circle = get_circle_or_404(session, circle_id)
    require_membership(session, current_user.id, circle_id)

    if body.amount_kobo != circle.weekly_amount_kobo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Contribution must be the weekly amount of {circle.weekly_amount_kobo} kobo",
        )

    contribution = Contribution(
        user_id=current_user.id,
        circle_id=circle.id,
        amount_kobo=body.amount_kobo,
        week=circle.current_week,
        confirmed=False,
    )
    session.add(contribution)
    try:
        session.flush()
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Already contributed this week",
        )
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
