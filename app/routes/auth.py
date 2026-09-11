from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select

from app.models.user import User, UserRole
from app.schemas.auth import TokenResponse, UserRegister, UserResponse
from app.services.db import get_session
from app.services.security import create_access_token, hash_password, verify_password

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

    user = User(
        name=user_data.name,
        email=user_data.email,
        hashed_password=hash_password(user_data.password),
        role=UserRole.MEMBER,
    )

    session.add(user)
    session.commit()
    session.refresh(user)

    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
)
def login_user(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session),
):
    user = session.exec(
        select(User).where(User.email == form_data.username)
    ).first()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(user.id)

    return {
        "access_token": token,
        "token_type": "bearer",
    }
