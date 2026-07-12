from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session, select

from ..config import settings
from ..database import get_session
from ..dependencies import get_current_user
from ..models import (
    Candidate,
    CandidateProfile,
    CandidateScore,
    Interview,
    InterviewLink,
    InterviewReport,
    InterviewTranscript,
    JobDescription,
    Resume,
    RecruiterInvitation,
    ProctorEvent,
    User,
)
from ..schemas import CandidateActionResponse, ReportAskRequest, ReportAskResponse
from ..security import expires_in, generate_token, hash_secret, utcnow
from ..services import ai_interviewer
from ..services.activity import log_activity
from ..services.email_service import next_round_template, rejection_template, round_two_template, send_email
from ..services.pdf_service import build_curated_report_pdf

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


def _workspace_owner(session: Session, user: User) -> str:
    membership = session.exec(select(RecruiterInvitation).where(RecruiterInvitation.invited_user_id == user.id)).first()
    return membership.manager_id if membership else user.id


def _interview_context(session: Session, interview_id: str, user: User):
    interview = session.get(Interview, interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    candidate = session.get(Candidate, interview.candidate_id)
    job = session.get(JobDescription, interview.job_id)
    if not candidate or not job or job.created_by != _workspace_owner(session, user):
        raise HTTPException(status_code=404, detail="Interview report not found")
    return interview, candidate, job


def _candidate_context(session: Session, candidate_id: str, user: User):
    candidate = session.get(Candidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    job = session.get(JobDescription, candidate.job_id)
    if not job or job.created_by != _workspace_owner(session, user):
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate, job


def _report_payload(session: Session, interview: Interview, candidate: Candidate, job: JobDescription) -> dict:
    report = session.exec(select(InterviewReport).where(InterviewReport.interview_id == interview.id)).first()
    scores = session.exec(select(CandidateScore).where(CandidateScore.interview_id == interview.id)).all()
    transcripts = session.exec(
        select(InterviewTranscript)
        .where(InterviewTranscript.interview_id == interview.id)
        .order_by(InterviewTranscript.sequence_number)
    ).all()
    profile = session.exec(select(CandidateProfile).where(CandidateProfile.candidate_id == candidate.id)).first()
    resume = session.exec(
        select(Resume).where(Resume.candidate_id == candidate.id).order_by(Resume.uploaded_at.desc())
    ).first()
    proctor_events = session.exec(
        select(ProctorEvent).where(ProctorEvent.interview_id == interview.id).order_by(ProctorEvent.occurred_at)
    ).all()
    return {
        "candidate": candidate.model_dump(),
        "job": job.model_dump(),
        "profile": profile.model_dump() if profile else None,
        "resume": resume.model_dump() if resume else None,
        "interview": interview.model_dump(),
        "transcript": [item.model_dump() for item in transcripts],
        "report": report.model_dump() if report else None,
        "scores": [score.model_dump() for score in scores],
        "proctor_events": [event.model_dump() for event in proctor_events],
        "proctor_summary": {"total": len(proctor_events), "critical": len([event for event in proctor_events if event.severity == "critical"])},
    }


@router.get("/interviews/{interview_id}")
def get_report(interview_id: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    interview, candidate, job = _interview_context(session, interview_id, user)
    return _report_payload(session, interview, candidate, job)


@router.get("/candidates/{candidate_id}")
def get_candidate_report(
    candidate_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    candidate, job = _candidate_context(session, candidate_id, user)
    interview = session.exec(
        select(Interview).where(Interview.candidate_id == candidate.id).order_by(Interview.created_at.desc())
    ).first()
    if not interview:
        raise HTTPException(status_code=404, detail="No interview found for candidate")
    return _report_payload(session, interview, candidate, job)


@router.post("/candidates/{candidate_id}/move-next-round", response_model=CandidateActionResponse)
def move_next_round(
    candidate_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    candidate, job = _candidate_context(session, candidate_id, user)
    candidate.status = "Moved To Next Round"
    candidate.updated_at = utcnow()
    session.add(candidate)
    session.commit()

    subject, body = next_round_template(candidate, job)
    email_log = send_email(
        session,
        recipient_email=candidate.email,
        subject=subject,
        body=body,
        email_type="next_round",
        candidate_id=candidate.id,
        job_id=job.id,
    )
    log_activity(
        session,
        action="candidate_moved_next_round",
        actor_user_id=user.id,
        candidate_id=candidate.id,
        job_id=job.id,
        details=email_log.status,
    )
    session.commit()
    return CandidateActionResponse(candidate_id=candidate.id, status=candidate.status, email_status=email_log.status)


@router.post("/candidates/{candidate_id}/round-2")
def schedule_round_two(candidate_id: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    candidate, job = _candidate_context(session, candidate_id, user)
    token = generate_token()
    link_url = f"{settings.frontend_base_url.rstrip('/')}/candidate?token={token}"
    link = InterviewLink(candidate_id=candidate.id, job_id=job.id, round_number=2, token_hash=hash_secret(token), magic_link=link_url, expires_at=expires_in(hours=settings.magic_link_expiry_hours))
    session.add(link)
    candidate.status = "Interview Scheduled"
    candidate.updated_at = utcnow()
    session.add(candidate)
    session.commit()
    subject, body, html_body = round_two_template(candidate, job, link_url)
    email_log = send_email(session, recipient_email=candidate.email, subject=subject, body=body, html_body=html_body, email_type="round_two_invitation", candidate_id=candidate.id, job_id=job.id)
    return {"candidate_id": candidate.id, "round_number": 2, "magic_link": link_url, "email_status": email_log.status, "expires_at": link.expires_at.isoformat()}


@router.post("/candidates/{candidate_id}/reject", response_model=CandidateActionResponse)
def reject_candidate(
    candidate_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    candidate, job = _candidate_context(session, candidate_id, user)
    candidate.status = "Rejected"
    candidate.updated_at = utcnow()
    session.add(candidate)
    session.commit()

    subject, body = rejection_template(candidate, job)
    email_log = send_email(
        session,
        recipient_email=candidate.email,
        subject=subject,
        body=body,
        email_type="rejection",
        candidate_id=candidate.id,
        job_id=job.id,
    )
    log_activity(
        session,
        action="candidate_rejected",
        actor_user_id=user.id,
        candidate_id=candidate.id,
        job_id=job.id,
        details=email_log.status,
    )
    session.commit()
    return CandidateActionResponse(candidate_id=candidate.id, status=candidate.status, email_status=email_log.status)


@router.get("/interviews/{interview_id}/pdf")
def download_report_pdf(
    interview_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    interview, candidate, job = _interview_context(session, interview_id, user)
    payload = _report_payload(session, interview, candidate, job)
    pdf = build_curated_report_pdf(payload)
    filename = f"interview-report-{candidate.full_name.replace(' ', '-').lower()}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/interviews/{interview_id}/ask", response_model=ReportAskResponse)
def ask_maya_about_report(
    interview_id: str,
    payload: ReportAskRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    interview, candidate, job = _interview_context(session, interview_id, user)
    report = session.exec(select(InterviewReport).where(InterviewReport.interview_id == interview.id)).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report has not been generated yet")
    scores = session.exec(select(CandidateScore).where(CandidateScore.interview_id == interview.id)).all()
    transcripts = session.exec(
        select(InterviewTranscript)
        .where(InterviewTranscript.interview_id == interview.id)
        .order_by(InterviewTranscript.sequence_number)
    ).all()
    profile = session.exec(select(CandidateProfile).where(CandidateProfile.candidate_id == candidate.id)).first()
    resume = session.exec(
        select(Resume).where(Resume.candidate_id == candidate.id).order_by(Resume.uploaded_at.desc())
    ).first()
    answer = ai_interviewer.answer_report_question(
        candidate=candidate,
        job=job,
        profile=profile,
        resume=resume,
        transcripts=transcripts,
        report=report,
        scores=scores,
        question=payload.question,
    )
    return ReportAskResponse(answer=answer)
