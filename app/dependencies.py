from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlmodel import Session, select

from .database import get_session
from .models import InterviewLink, User
from .security import hash_secret, is_expired


def _bearer_token(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return authorization.split(" ", 1)[1].strip()


def get_current_user(
    authorization: Optional[str] = Header(None),
    session: Session = Depends(get_session),
) -> User:
    token = _bearer_token(authorization)
    token_hash = hash_secret(token)
    user = session.exec(select(User).where(User.session_token_hash == token_hash)).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid recruiter session")
    return user


def get_candidate_link(
    authorization: Optional[str] = Header(None),
    session: Session = Depends(get_session),
) -> InterviewLink:
    token = _bearer_token(authorization)
    token_hash = hash_secret(token)
    link = session.exec(select(InterviewLink).where(InterviewLink.candidate_session_token_hash == token_hash)).first()
    if not link or is_expired(link.session_expires_at):
        raise HTTPException(status_code=401, detail="Invalid or expired candidate session")
    if not link.otp_verified_at:
        raise HTTPException(status_code=401, detail="Candidate session is not verified")
    return link
