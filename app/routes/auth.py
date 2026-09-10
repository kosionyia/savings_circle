from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from services.db import get_session
from models.user import User, UserRole
from schemas.auth import UserRegister, UserResponse
from services.security import hash_password


router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_user(
    user_data: UserRegister,
    session: Session = Depends(get_session),
):
    existing_user = session.exec(
        select(User).where(User.email == user_data.email)
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        )

    hashed_password = hash_password(user_data.password)

    user = User(
        name=user_data.name,
        email=user_data.email,
        hashed_password=hashed_password,
        role=UserRole.MEMBER,
    )

    session.add(user)
    session.commit()
    session.refresh(user)

    return user