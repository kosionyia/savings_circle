from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.models.circles import Circle
from app.models.contribution import Contribution
from app.models.membership import (
Membership, 
MembershipRequest, 
MembershipRequestOut, 
RequestStatus
)
from app.models.user import User
from app.schemas.circles import (
    CircleHealth,
    CircleOut,
    MemberHealth,
    TurnMember,
    GetCircle,
)
from app.services.db import get_session
from app.services.dependency import get_current_user, require_admin
from app.services.helpers import (
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
    return membership




@router.get(
    "",
    response_model=list[GetCircle],
    status_code=status.HTTP_200_OK,
)
def get_all_circles(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    circles = session.exec(
        select(Circle)
    ).all()

    return [_circle_out(session, circle) for circle in circles]



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
     response_model=MembershipRequestOut,
    status_code=status.HTTP_201_CREATED,
)
def join_circle(
    circle_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    request = MembershipRequest(
        user_id=current_user.id,
        circle_id=circle_id,
        status=RequestStatus.PENDING,
    )
    session.add(request)
    session.commit()
    session.refresh(request)
    
    return request




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
