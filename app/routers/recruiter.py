from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..config import settings
from ..database import get_session
from ..dependencies import get_current_user
from ..models import Candidate, Interview, InterviewLink, JobDescription, User
from ..schemas import (
    CandidateCreateRequest,
    CandidateUpdateRequest,
    ConductInterviewRequest,
    JobCreateRequest,
    JobUpdateRequest,
    MagicLinkResponse,
)
from ..security import expires_in, generate_token, hash_secret, utcnow
from ..services.activity import log_activity
from ..services.email_service import invitation_template, send_email

router = APIRouter(prefix="/api/v1/recruiter", tags=["recruiter"])

VALID_CANDIDATE_STATUSES = {
    "Pending Interview",
    "Interview Scheduled",
    "Interview Completed",
    "Shortlisted",
    "Rejected",
    "Moved To Next Round",
}


def _frontend_base_url() -> str:
    base_url = settings.frontend_base_url.strip().strip("'\"").rstrip("/")
    if not base_url:
        return "http://127.0.0.1:3000"
    if base_url.startswith(("http://", "https://")):
        return base_url
    return f"https://{base_url}"


def _job_or_404(session: Session, job_id: str, user: User) -> JobDescription:
    job = session.get(JobDescription, job_id)
    if not job or job.created_by != user.id:
        raise HTTPException(status_code=404, detail="Job description not found")
    return job


def _candidate_or_404(session: Session, candidate_id: str, job_id: str, user: User) -> Candidate:
    candidate = session.get(Candidate, candidate_id)
    if not candidate or candidate.job_id != job_id or candidate.created_by != user.id:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


def _job_payload(job: JobDescription) -> dict:
    return job.model_dump()


def _candidate_payload(candidate: Candidate) -> dict:
    return candidate.model_dump()


@router.get("/statuses")
def candidate_statuses():
    return {"statuses": sorted(VALID_CANDIDATE_STATUSES)}


@router.post("/jobs")
def create_job(payload: JobCreateRequest, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    job = JobDescription(created_by=user.id, **payload.model_dump())
    session.add(job)
    session.flush()
    log_activity(session, action="job_created", actor_user_id=user.id, job_id=job.id, details=payload.job_title)
    session.commit()
    session.refresh(job)
    return _job_payload(job)


@router.get("/jobs")
def list_jobs(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    jobs = session.exec(
        select(JobDescription).where(JobDescription.created_by == user.id).order_by(JobDescription.created_at.desc())
    ).all()
    output = []
    for job in jobs:
        candidate_count = session.exec(select(Candidate).where(Candidate.job_id == job.id)).all()
        item = _job_payload(job)
        item["candidate_count"] = len(candidate_count)
        output.append(item)
    return output


@router.get("/jobs/{job_id}")
def get_job(job_id: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    return _job_payload(_job_or_404(session, job_id, user))


@router.patch("/jobs/{job_id}")
def update_job(
    job_id: str,
    payload: JobUpdateRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    job = _job_or_404(session, job_id, user)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(job, key, value)
    job.updated_at = utcnow()
    session.add(job)
    log_activity(session, action="job_updated", actor_user_id=user.id, job_id=job.id)
    session.commit()
    session.refresh(job)
    return _job_payload(job)


@router.post("/jobs/{job_id}/candidates")
def add_candidate(
    job_id: str,
    payload: CandidateCreateRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _job_or_404(session, job_id, user)
    candidate = Candidate(
        job_id=job_id,
        created_by=user.id,
        full_name=payload.full_name.strip(),
        email=payload.email.strip().lower(),
        mobile_number=payload.mobile_number.strip(),
        current_role=payload.current_role.strip(),
        current_company=payload.current_company.strip() if payload.current_company else None,
        status="Pending Interview",
    )
    session.add(candidate)
    session.flush()
    log_activity(session, action="candidate_added", actor_user_id=user.id, candidate_id=candidate.id, job_id=job_id)
    session.commit()
    session.refresh(candidate)
    return _candidate_payload(candidate)


@router.get("/jobs/{job_id}/candidates")
def list_candidates(job_id: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _job_or_404(session, job_id, user)
    candidates = session.exec(
        select(Candidate).where(Candidate.job_id == job_id).order_by(Candidate.created_at.desc())
    ).all()
    changed = False
    workflow_statuses = {"Pending Interview", "Interview Scheduled", "Interview Completed"}
    for candidate in candidates:
        if candidate.status not in workflow_statuses:
            continue
        interview = session.exec(
            select(Interview)
            .where(Interview.candidate_id == candidate.id)
            .order_by(Interview.created_at.desc())
        ).first()
        has_link = session.exec(
            select(InterviewLink.id).where(InterviewLink.candidate_id == candidate.id)
        ).first() is not None
        expected = (
            "Interview Completed" if interview and interview.status == "completed"
            else "Interview Scheduled" if has_link
            else "Pending Interview"
        )
        if candidate.status != expected:
            candidate.status = expected
            candidate.updated_at = utcnow()
            session.add(candidate)
            changed = True
    if changed:
        session.commit()
    return [_candidate_payload(candidate) for candidate in candidates]


@router.patch("/jobs/{job_id}/candidates/{candidate_id}")
def update_candidate(
    job_id: str,
    candidate_id: str,
    payload: CandidateUpdateRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    candidate = _candidate_or_404(session, candidate_id, job_id, user)
    data = payload.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in VALID_CANDIDATE_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid candidate status")
    for key, value in data.items():
        setattr(candidate, key, value.strip().lower() if key == "email" and value else value)
    candidate.updated_at = utcnow()
    session.add(candidate)
    log_activity(session, action="candidate_updated", actor_user_id=user.id, candidate_id=candidate.id, job_id=job_id)
    session.commit()
    session.refresh(candidate)
    return _candidate_payload(candidate)


@router.post("/jobs/{job_id}/conduct-interviews", response_model=List[MagicLinkResponse])
def conduct_interviews(
    job_id: str,
    payload: ConductInterviewRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    job = _job_or_404(session, job_id, user)
    results = []

    for candidate_id in payload.candidate_ids:
        candidate = _candidate_or_404(session, candidate_id, job_id, user)
        token = generate_token()
        expires_at = expires_in(hours=settings.magic_link_expiry_hours)
        magic_link = f"{_frontend_base_url()}/candidate?token={token}"
        link = InterviewLink(
            candidate_id=candidate.id,
            job_id=job.id,
            token_hash=hash_secret(token),
            magic_link=magic_link,
            expires_at=expires_at,
        )
        session.add(link)

        candidate.status = "Interview Scheduled"
        candidate.updated_at = utcnow()
        session.add(candidate)
        session.commit()
        session.refresh(link)

        subject, body, html_body = invitation_template(candidate, job, magic_link)
        email_log = send_email(
            session,
            recipient_email=candidate.email,
            subject=subject,
            body=body,
            html_body=html_body,
            email_type="interview_invitation",
            candidate_id=candidate.id,
            job_id=job.id,
        )
        log_activity(
            session,
            action="interview_invitation_sent",
            actor_user_id=user.id,
            candidate_id=candidate.id,
            job_id=job.id,
            details=email_log.status,
        )
        session.commit()
        results.append(
            MagicLinkResponse(
                candidate_id=candidate.id,
                email=candidate.email,
                magic_link=magic_link,
                email_status=email_log.status,
                expires_at=expires_at.isoformat(),
            )
        )

    return results
