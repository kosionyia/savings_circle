from sqlalchemy.exc import IntegrityError

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.models.circles import Circle
from app.models.membership import MembershipRequest, MembershipRequestOut, RequestStatus
from app.models.user import User
from app.routes.circles import _add_member, _circle_out
from app.schemas.auth import  UserResponse
from app.schemas.circles import CircleCreate, CircleOut, MembershipOut, TurnOrderIn
from app.services.db import get_session
from app.services.dependency import require_admin
from app.services.helpers import assert_circle_admin, circle_members, get_circle_or_404, get_membership


router = APIRouter(prefix="/admin", tags=["Admin"])


@router.post(
    "/circles",
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



@router.get("/users", response_model=list[UserResponse])
def get_all_users(session: Session = Depends(get_session), 
                  user: User = Depends(require_admin)):
    return session.exec(select(User)).all()


@router.get(
    "/requests",
    response_model=list[MembershipRequestOut],
)
def get_all_membership_requests(
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    return session.exec(
        select(MembershipRequest)
    ).all()


@router.get(
    "/circles/{circle_id}/requests",
    response_model=list[MembershipRequestOut],
)
def get_circle_membership_requests(
    circle_id: int,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    circle = get_circle_or_404(session, circle_id)

    assert_circle_admin(current_user, circle)

    requests = session.exec(
        select(MembershipRequest).where(
            MembershipRequest.circle_id == circle_id,
            MembershipRequest.status == RequestStatus.PENDING,
        )
    ).all()

    return requests

@router.post(
    "/circles/{circle_id}/requests/{request_id}/approve",
    response_model=MembershipOut,
    status_code=status.HTTP_201_CREATED,
)
def admit_member(
    circle_id: int,
    request_id: int,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    circle = get_circle_or_404(session, circle_id)
    assert_circle_admin(current_user, circle)

    request = session.get(MembershipRequest, request_id)
    if request is None or request.circle_id != circle_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Membership request not found",
        )
    if request.status != RequestStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Membership request has already been processed",
            )

    user = session.get(User, request.user_id)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    existing_membership = get_membership(
        session,
        user.id,
        circle.id,
    )

    print("USER:", user.id)
    print("CIRCLE:", circle.id)
    print("MEMBERSHIP:", existing_membership)

    membership = _add_member(session, circle, user)
    request.status = RequestStatus.APPROVED
    try:
        session.commit()
    except IntegrityError as e:
        session.rollback()
        print("intedrity error:", e)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Already a member of this circle",
        )    
    session.refresh(membership)

    return membership


@router.put(
    "/circles/{circle_id}/turn-order",
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

    if len(body.user_ids) != len(member_ids) or set(body.user_ids) != member_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Turn order must include each member exactly once",
        )
    by_user = {member.user_id: member for member in members}

    # SQLite unique on (circle_id, turn_position) will fight us if we
    # rewrite in place, so park them high first, then set the real order.
    for position, member in enumerate(members, start=1):
            member.turn_position = position + len(members)
        
    session.commit()
    
    for position, user_id in enumerate(body.user_ids, start=1):
        by_user[user_id].turn_position = position

    session.commit()

    return _circle_out(session, circle)
