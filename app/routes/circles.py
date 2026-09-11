from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models.circles import Circle
from app.models.contribution import Contribution
from app.models.membership import Membership
from app.models.user import User
from app.schemas.circles import (
    AdmitMember,
    CircleCreate,
    CircleHealth,
    CircleOut,
    MemberHealth,
    MembershipOut,
    TurnMember,
    TurnOrderIn,
)
from app.services.db import get_session
from app.services.dependency import get_current_user, require_admin
from app.services.helpers import (
    assert_circle_admin,
    circle_members,
    get_circle_or_404,
    get_membership,
    next_recipient,
    next_turn_position,
    require_membership,
)

router = APIRouter(prefix="/circles", tags=["Circles"])


def _circle_out(session: Session, circle: Circle) -> CircleOut:
    members = circle_members(session, circle.id)
    turn_order: list[TurnMember] = []
    for member in members:
        person = session.get(User, member.user_id)
        turn_order.append(
            TurnMember(
                user_id=member.user_id,
                name=person.name if person else "Unknown",
                turn_position=member.turn_position,
            )
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

    upcoming = next_recipient(session, circle)
    next_name = None
    if upcoming:
        person = session.get(User, upcoming.user_id)
        next_name = person.name if person else None

    return CircleOut(
        id=circle.id,
        name=circle.name,
        weekly_amount=circle.weekly_amount,
        member_limit=circle.member_limit,
        current_week=circle.current_week,
        admin_id=circle.admin_id,
        pot=pot,
        member_count=len(members),
        turn_order=turn_order,
        next_user_id=upcoming.user_id if upcoming else None,
        next_user_name=next_name,
    )


def _add_member(session: Session, circle: Circle, user: User) -> Membership:
    if get_membership(session, user.id, circle.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Already a member of this circle",
        )

    members = circle_members(session, circle.id)
    if len(members) >= circle.member_limit:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This circle is full",
        )

    membership = Membership(
        user_id=user.id,
        circle_id=circle.id,
        turn_position=next_turn_position(session, circle.id),
    )
    session.add(membership)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Already a member of this circle",
        )
    session.refresh(membership)
    return membership


@router.post(
    "",
    response_model=CircleOut,
    status_code=status.HTTP_201_CREATED,
)
def create_circle(
    body: CircleCreate,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    circle = Circle(
        name=body.name,
        weekly_amount=body.weekly_amount,
        member_limit=body.member_limit,
        admin_id=current_user.id,
    )
    session.add(circle)
    session.commit()
    session.refresh(circle)
    return _circle_out(session, circle)


@router.get(
    "/{circle_id}",
    response_model=CircleOut,
    status_code=status.HTTP_200_OK,
)
def get_circle(
    circle_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    circle = get_circle_or_404(session, circle_id)
    if current_user.id != circle.admin_id:
        require_membership(session, current_user.id, circle_id)
    return _circle_out(session, circle)


@router.post(
    "/{circle_id}/join",
    response_model=MembershipOut,
    status_code=status.HTTP_201_CREATED,
)
def join_circle(
    circle_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    circle = get_circle_or_404(session, circle_id)
    return _add_member(session, circle, current_user)


@router.post(
    "/{circle_id}/members",
    response_model=MembershipOut,
    status_code=status.HTTP_201_CREATED,
)
def admit_member(
    circle_id: int,
    body: AdmitMember,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    circle = get_circle_or_404(session, circle_id)
    assert_circle_admin(current_user, circle)

    user = session.get(User, body.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return _add_member(session, circle, user)


@router.put(
    "/{circle_id}/turn-order",
    response_model=CircleOut,
    status_code=status.HTTP_200_OK,
)
def set_turn_order(
    circle_id: int,
    body: TurnOrderIn,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    circle = get_circle_or_404(session, circle_id)
    assert_circle_admin(current_user, circle)

    members = circle_members(session, circle_id)
    member_ids = {member.user_id for member in members}

    if set(body.user_ids) != member_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Turn order must include each member exactly once",
        )

    if len(body.user_ids) != len(set(body.user_ids)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Turn order must include each member exactly once",
        )

    by_user = {member.user_id: member for member in members}

    # SQLite unique on (circle_id, turn_position) will fight us if we
    # rewrite in place, so park them high first, then set the real order.
    for offset, member in enumerate(members, start=1000):
        member.turn_position = offset
        session.add(member)
    session.commit()

    for position, user_id in enumerate(body.user_ids, start=1):
        member = by_user[user_id]
        member.turn_position = position
        session.add(member)
    session.commit()

    session.refresh(circle)
    return _circle_out(session, circle)


@router.get(
    "/{circle_id}/health",
    response_model=CircleHealth,
    status_code=status.HTTP_200_OK,
)
def circle_health(
    circle_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    circle = get_circle_or_404(session, circle_id)
    if current_user.id != circle.admin_id:
        require_membership(session, current_user.id, circle_id)

    paid_ids = {
        row.user_id
        for row in session.exec(
            select(Contribution).where(
                Contribution.circle_id == circle.id,
                Contribution.week == circle.current_week,
            )
        ).all()
    }

    paid: list[MemberHealth] = []
    behind: list[MemberHealth] = []
    for member in circle_members(session, circle.id):
        person = session.get(User, member.user_id)
        item = MemberHealth(
            user_id=member.user_id,
            name=person.name if person else "Unknown",
        )
        if member.user_id in paid_ids:
            paid.append(item)
        else:
            behind.append(item)

    return CircleHealth(week=circle.current_week, paid=paid, behind=behind)
