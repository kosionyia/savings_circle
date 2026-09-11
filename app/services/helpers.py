from fastapi import HTTPException, status
from sqlmodel import Session, select

from app.models.circles import Circle
from app.models.membership import Membership
from app.models.user import User


def get_circle_or_404(session: Session, circle_id: int) -> Circle:
    circle = session.get(Circle, circle_id)
    if circle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Circle not found",
        )
    return circle


def get_membership(
    session: Session,
    user_id: int,
    circle_id: int,
) -> Membership | None:
    return session.exec(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.circle_id == circle_id,
        )
    ).first()


def require_membership(
    session: Session,
    user_id: int,
    circle_id: int,
) -> Membership:
    membership = get_membership(session, user_id, circle_id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this circle",
        )
    return membership


def assert_circle_admin(user: User, circle: Circle) -> None:
    if circle.admin_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only this circle's admin can do that",
        )


def circle_members(session: Session, circle_id: int) -> list[Membership]:
    return session.exec(
        select(Membership)
        .where(Membership.circle_id == circle_id)
        .order_by(Membership.turn_position)
    ).all()


def next_recipient(session: Session, circle: Circle) -> Membership | None:
    members = circle_members(session, circle.id)
    if not members:
        return None

    position = ((circle.current_week - 1) % len(members)) + 1
    for member in members:
        if member.turn_position == position:
            return member
    return members[0]


def next_turn_position(session: Session, circle_id: int) -> int:
    members = circle_members(session, circle_id)
    if not members:
        return 1
    return max(member.turn_position for member in members) + 1
