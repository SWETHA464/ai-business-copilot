from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.security.auth import create_access_token, get_current_user, hash_password, verify_password
from app.security.rate_limit import login_limit
from app.utils.logging import get_logger

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = get_logger("auth")


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(login_limit)])
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> User:
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    # Public registration can only ever create employees. Admins come from scripts/create_admin.py.
    user = User(email=email, full_name=body.full_name, hashed_password=hash_password(body.password),
                role="employee")
    db.add(user)
    db.commit()
    log.info("user registered id=%s", user.id)
    return user


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(login_limit)])
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    ok = verify_password(body.password, user.hashed_password if user else None)
    if not ok or user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    return TokenResponse(access_token=create_access_token(user), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user
