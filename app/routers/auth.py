from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..database import get_session
from ..dependencies import get_current_user
from ..models import User
from ..schemas import AuthLoginRequest, AuthRegisterRequest, AuthResponse
from ..security import generate_token, hash_password, hash_secret, utcnow, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _user_payload(user: User) -> dict:
    return {"id": user.id, "full_name": user.full_name, "email": user.email, "role": user.role}


@router.post("/register", response_model=AuthResponse)
def register(payload: AuthRegisterRequest, session: Session = Depends(get_session)):
    email = payload.email.strip().lower()
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    existing = session.exec(select(User).where(User.email == email)).first()
    if existing:
        raise HTTPException(status_code=409, detail="A recruiter already exists with this email")

    token = generate_token()
    user = User(
        full_name=payload.full_name.strip(),
        email=email,
        password_hash=hash_password(payload.password),
        session_token_hash=hash_secret(token),
        last_login_at=utcnow(),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return AuthResponse(access_token=token, user=_user_payload(user))


@router.post("/login", response_model=AuthResponse)
def login(payload: AuthLoginRequest, session: Session = Depends(get_session)):
    email = payload.email.strip().lower()
    user = session.exec(select(User).where(User.email == email)).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = generate_token()
    user.session_token_hash = hash_secret(token)
    user.last_login_at = utcnow()
    session.add(user)
    session.commit()
    session.refresh(user)
    return AuthResponse(access_token=token, user=_user_payload(user))


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return _user_payload(user)
