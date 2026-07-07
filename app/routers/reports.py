from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session, select

from ..database import get_session
from ..dependencies import get_current_user
from ..models import (
    Candidate,
    CandidateProfile,
    CandidateScore,
    Interview,
    InterviewReport,
    InterviewTranscript,
    JobDescription,
    Resume,
    User,
)
from ..schemas import CandidateActionResponse
from ..security import utcnow
from ..services.activity import log_activity
from ..services.email_service import next_round_template, rejection_template, send_email
from ..services.pdf_service import build_report_pdf

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


def _interview_context(session: Session, interview_id: str, user: User):
    interview = session.get(Interview, interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    candidate = session.get(Candidate, interview.candidate_id)
    job = session.get(JobDescription, interview.job_id)
    if not candidate or not job or job.created_by != user.id:
        raise HTTPException(status_code=404, detail="Interview report not found")
    return interview, candidate, job


def _candidate_context(session: Session, candidate_id: str, user: User):
    candidate = session.get(Candidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    job = session.get(JobDescription, candidate.job_id)
    if not job or job.created_by != user.id:
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
    return {
        "candidate": candidate.model_dump(),
        "job": job.model_dump(),
        "profile": profile.model_dump() if profile else None,
        "resume": resume.model_dump() if resume else None,
        "interview": interview.model_dump(),
        "transcript": [item.model_dump() for item in transcripts],
        "report": report.model_dump() if report else None,
        "scores": [score.model_dump() for score in scores],
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
    report = payload["report"] or {}
    lines = [
        "AI Human Interview Report",
        "",
        f"Candidate: {candidate.full_name}",
        f"Email: {candidate.email}",
        f"Mobile: {candidate.mobile_number}",
        f"Current Role: {candidate.current_role}",
        f"Job: {job.job_title} at {job.company_name}",
        f"Interview Status: {interview.status}",
        f"Overall Score: {interview.overall_score or 'N/A'}",
        "",
        "Scores",
    ]
    for score in payload["scores"]:
        lines.append(f"- {score['category']}: {score['score']}/10 - {score.get('reasoning') or ''}")
    lines.extend(
        [
            "",
            "Summary",
            report.get("summary", "Report has not been generated."),
            "",
            "Strengths",
            report.get("strengths", ""),
            "",
            "Weaknesses",
            report.get("weaknesses", ""),
            "",
            "Key Observations",
            report.get("key_observations", ""),
            "",
            "Technical Assessment",
            report.get("technical_assessment", ""),
            "",
            "Behavioral Assessment",
            report.get("behavioral_assessment", ""),
            "",
            "Recommendation",
            f"{report.get('recommendation', 'N/A')} - {report.get('recommendation_reason', '')}",
            "",
            "Transcript",
        ]
    )
    for item in payload["transcript"]:
        lines.append(f"Q{item['sequence_number']}: {item['question_text']}")
        lines.append(f"A{item['sequence_number']}: {item.get('answer_text') or '[no answer]'}")
        lines.append("")

    pdf = build_report_pdf(lines)
    filename = f"interview-report-{candidate.full_name.replace(' ', '-').lower()}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
