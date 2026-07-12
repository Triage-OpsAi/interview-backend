from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..config import settings
from ..database import get_session
from ..dependencies import get_current_user
from ..models import RecruiterInvitation, User
from ..schemas import RecruiterInviteRequest, RecruiterOnboardRequest, RecruiterRoleRequest
from ..security import expires_in, generate_token, hash_password, hash_secret, is_expired, utcnow
from ..services.email_service import recruiter_invitation_template, send_email

router = APIRouter(prefix="/api/v1/team", tags=["team"])


def _membership(session: Session, user: User):
    return session.exec(select(RecruiterInvitation).where(RecruiterInvitation.invited_user_id == user.id)).first()


def _is_manager(session: Session, user: User) -> bool:
    membership = _membership(session, user)
    return user.role == "admin" or membership is None or membership.role == "manager"


def _workspace_manager(session: Session, user: User) -> str:
    membership = _membership(session, user)
    return membership.manager_id if membership else user.id


def _require_manager(session: Session, user: User) -> None:
    if not _is_manager(session, user):
        raise HTTPException(status_code=403, detail="Manager access required")


@router.get("")
def list_team(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _require_manager(session, user)
    invitations = session.exec(
        select(RecruiterInvitation).where(RecruiterInvitation.manager_id == _workspace_manager(session, user)).order_by(RecruiterInvitation.created_at.desc())
    ).all()
    return [{
        **item.model_dump(exclude={"token_hash"}),
        "is_manager": item.role == "manager",
    } for item in invitations]


@router.post("/invite")
def invite_recruiter(payload: RecruiterInviteRequest, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _require_manager(session, user)
    email = payload.email.strip().lower()
    existing = session.exec(select(User).where(User.email == email)).first()
    if existing:
        raise HTTPException(status_code=409, detail="A user already exists with this email")
    token = generate_token()
    invitation = RecruiterInvitation(
        manager_id=_workspace_manager(session, user), email=email, full_name=payload.full_name.strip(), role="recruiter",
        token_hash=hash_secret(token), expires_at=expires_in(hours=72),
    )
    session.add(invitation)
    session.commit()
    session.refresh(invitation)
    link = f"{settings.frontend_base_url.rstrip('/')}/recruiter?invite={token}"
    subject, body, html_body = recruiter_invitation_template(invitation.full_name, user.full_name, link)
    email_log = send_email(session, recipient_email=email, subject=subject, body=body, html_body=html_body, email_type="recruiter_onboarding")
    return {**invitation.model_dump(exclude={"token_hash"}), "email_status": email_log.status}


@router.get("/invitation/{token}")
def verify_invitation(token: str, session: Session = Depends(get_session)):
    invitation = session.exec(select(RecruiterInvitation).where(RecruiterInvitation.token_hash == hash_secret(token))).first()
    if not invitation or invitation.status != "pending" or is_expired(invitation.expires_at):
        raise HTTPException(status_code=404, detail="Invitation is invalid or expired")
    return {"email": invitation.email, "full_name": invitation.full_name, "role": invitation.role}


@router.post("/onboard")
def onboard_recruiter(payload: RecruiterOnboardRequest, session: Session = Depends(get_session)):
    invitation = session.exec(select(RecruiterInvitation).where(RecruiterInvitation.token_hash == hash_secret(payload.token))).first()
    if not invitation or invitation.status != "pending" or is_expired(invitation.expires_at):
        raise HTTPException(status_code=404, detail="Invitation is invalid or expired")
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    user = User(full_name=payload.full_name.strip(), email=invitation.email, password_hash=hash_password(payload.password), role="recruiter")
    session.add(user)
    session.flush()
    invitation.invited_user_id = user.id
    invitation.status = "accepted"
    invitation.accepted_at = utcnow()
    session.add(invitation)
    session.commit()
    return {"status": "onboarded", "email": user.email}


@router.patch("/{invitation_id}/role")
def update_role(invitation_id: str, payload: RecruiterRoleRequest, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _require_manager(session, user)
    if payload.role not in {"recruiter", "manager"}:
        raise HTTPException(status_code=400, detail="Role must be recruiter or manager")
    invitation = session.get(RecruiterInvitation, invitation_id)
    if not invitation or invitation.manager_id != _workspace_manager(session, user):
        raise HTTPException(status_code=404, detail="Team member not found")
    invitation.role = payload.role
    session.add(invitation)
    session.commit()
    return {"id": invitation.id, "role": invitation.role, "is_manager": invitation.role == "manager"}
