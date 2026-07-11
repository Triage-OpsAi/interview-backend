from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session, select

from ..config import settings
from ..database import get_session
from ..dependencies import get_candidate_link
from ..models import (
    Candidate,
    CandidateProfile,
    CandidateScore,
    Interview,
    InterviewLink,
    InterviewReport,
    InterviewTranscript,
    JobDescription,
    OtpVerification,
    Resume,
)
from ..schemas import CandidateSessionResponse, InterviewAnswerRequest, OtpVerifyRequest
from ..security import elapsed_seconds, expires_in, generate_otp, generate_token, hash_secret, is_expired, mask_email, utcnow
from ..services import ai_interviewer
from ..services.activity import log_activity
from ..services.email_service import otp_template, send_email
from ..services.resume_parser import SUPPORTED_RESUME_EXTENSIONS, parse_resume
from ..services.storage_service import upload_resume

router = APIRouter(prefix="/api/v1/candidate", tags=["candidate"])


def _magic_link_or_404(session: Session, token: str) -> InterviewLink:
    link = session.exec(select(InterviewLink).where(InterviewLink.token_hash == hash_secret(token))).first()
    if not link:
        raise HTTPException(status_code=404, detail="Invalid magic link")
    if is_expired(link.expires_at):
        raise HTTPException(status_code=410, detail="Magic link expired")
    return link


def _candidate_and_job(session: Session, link: InterviewLink) -> tuple[Candidate, JobDescription]:
    candidate = session.get(Candidate, link.candidate_id)
    job = session.get(JobDescription, link.job_id)
    if not candidate or not job:
        raise HTTPException(status_code=404, detail="Interview context not found")
    return candidate, job


def _latest_resume(session: Session, candidate_id: str) -> Optional[Resume]:
    return session.exec(
        select(Resume).where(Resume.candidate_id == candidate_id).order_by(Resume.uploaded_at.desc())
    ).first()


def _profile(session: Session, candidate_id: str) -> Optional[CandidateProfile]:
    return session.exec(select(CandidateProfile).where(CandidateProfile.candidate_id == candidate_id)).first()


def _interview(session: Session, link: InterviewLink) -> Optional[Interview]:
    return session.exec(
        select(Interview).where(
            Interview.candidate_id == link.candidate_id,
            Interview.interview_link_id == link.id,
        )
    ).first()


def _transcripts(session: Session, interview_id: str):
    return session.exec(
        select(InterviewTranscript)
        .where(InterviewTranscript.interview_id == interview_id)
        .order_by(InterviewTranscript.sequence_number)
    ).all()


def _candidate_payload(candidate: Candidate) -> dict:
    return {
        "id": candidate.id,
        "full_name": candidate.full_name,
        "email": candidate.email,
        "mobile_number": candidate.mobile_number,
        "current_role": candidate.current_role,
        "current_company": candidate.current_company,
        "status": candidate.status,
    }


def _job_payload(job: JobDescription) -> dict:
    return {
        "id": job.id,
        "job_title": job.job_title,
        "company_name": job.company_name,
        "department": job.department,
        "experience_required": job.experience_required,
        "location": job.location,
        "employment_type": job.employment_type,
        "skills_required": job.skills_required,
        "responsibilities": job.responsibilities,
        "full_job_description": job.full_job_description,
    }


def _get_or_create_interview(session: Session, link: InterviewLink) -> Interview:
    interview = _interview(session, link)
    if interview:
        if interview.status == "not_started" and interview.max_questions != settings.max_interview_questions:
            interview.max_questions = settings.max_interview_questions
            session.add(interview)
            session.commit()
            session.refresh(interview)
        return interview
    interview = Interview(
        candidate_id=link.candidate_id,
        job_id=link.job_id,
        interview_link_id=link.id,
        status="not_started",
        max_questions=settings.max_interview_questions,
    )
    session.add(interview)
    session.commit()
    session.refresh(interview)
    return interview


def _score_rows_from_report_data(
    session: Session,
    *,
    report: InterviewReport,
    interview: Interview,
    candidate: Candidate,
    report_data: dict,
) -> tuple[list[int], float, float]:
    score_values = []
    weighted_total = 0.0
    weight_total = 0.0
    existing_scores = session.exec(select(CandidateScore).where(CandidateScore.report_id == report.id)).all()
    existing_by_category = {item.category: item for item in existing_scores}
    for item in report_data.get("scores", []) or []:
        try:
            score = max(1, min(10, int(item.get("score", 1))))
        except (TypeError, ValueError):
            score = 1
        try:
            weight = float(item.get("weight", 0) or 0)
        except (TypeError, ValueError):
            weight = 0
        score_values.append(score)
        if weight > 0:
            weighted_total += score * weight
            weight_total += weight
        category = item.get("category", "Uncategorized")
        reasoning = f"Weight {int(weight * 100)}%. {item.get('reasoning')}" if weight else item.get("reasoning")
        existing = existing_by_category.get(category)
        if existing:
            existing.score = score
            existing.reasoning = reasoning
            session.add(existing)
        else:
            session.add(
                CandidateScore(
                    report_id=report.id,
                    interview_id=interview.id,
                    candidate_id=candidate.id,
                    category=category,
                    score=score,
                    reasoning=reasoning,
                )
            )
    return score_values, weighted_total, weight_total


def _complete_interview_state(
    session: Session,
    *,
    interview: Interview,
    candidate: Candidate,
    job: JobDescription,
    report: InterviewReport,
    report_data: Optional[dict] = None,
) -> InterviewReport:
    if report_data:
        score_values, weighted_total, weight_total = _score_rows_from_report_data(
            session,
            report=report,
            interview=interview,
            candidate=candidate,
            report_data=report_data,
        )
    else:
        existing_scores = session.exec(select(CandidateScore).where(CandidateScore.report_id == report.id)).all()
        score_values = [score.score for score in existing_scores]
        weighted_total = 0.0
        weight_total = 0.0

    interview.status = "completed"
    interview.completed_at = interview.completed_at or utcnow()
    if interview.started_at:
        interview.duration_seconds = elapsed_seconds(interview.started_at, interview.completed_at)
    if report_data and report_data.get("overall_score") is not None:
        try:
            interview.overall_score = max(0, min(100, int(report_data["overall_score"])))
        except (TypeError, ValueError):
            pass
    if interview.overall_score is None and weight_total:
        interview.overall_score = int(round((weighted_total / weight_total) * 10))
    elif interview.overall_score is None and score_values:
        interview.overall_score = int(round((sum(score_values) / len(score_values)) * 10))

    candidate.status = "Interview Completed"
    candidate.updated_at = utcnow()
    session.add(interview)
    session.add(candidate)
    log_activity(session, action="interview_completed", candidate_id=candidate.id, job_id=job.id, details=interview.id)
    session.commit()
    session.refresh(report)
    return report


def _finalize_interview(session: Session, interview: Interview) -> InterviewReport:
    candidate = session.get(Candidate, interview.candidate_id)
    job = session.get(JobDescription, interview.job_id)
    if not candidate or not job:
        raise HTTPException(status_code=404, detail="Interview context not found")

    profile = _profile(session, candidate.id)
    resume = _latest_resume(session, candidate.id)
    transcripts = _transcripts(session, interview.id)
    existing = session.exec(select(InterviewReport).where(InterviewReport.interview_id == interview.id)).first()

    if existing:
        scores = session.exec(select(CandidateScore).where(CandidateScore.report_id == existing.id)).all()
        report_data = None
        if not scores or interview.overall_score is None:
            report_data = ai_interviewer.generate_report(
                candidate=candidate,
                job=job,
                profile=profile,
                resume=resume,
                transcripts=transcripts,
            )
            existing.summary = existing.summary or report_data.get("summary", "")
            existing.strengths = existing.strengths or report_data.get("strengths", "")
            existing.weaknesses = existing.weaknesses or report_data.get("weaknesses", "")
            existing.key_observations = existing.key_observations or report_data.get("key_observations", "")
            existing.technical_assessment = existing.technical_assessment or report_data.get("technical_assessment", "")
            existing.behavioral_assessment = existing.behavioral_assessment or report_data.get("behavioral_assessment", "")
            existing.recommendation = existing.recommendation or report_data.get("recommendation", "Borderline")
            existing.recommendation_reason = existing.recommendation_reason or report_data.get("recommendation_reason", "")
            session.add(existing)
        return _complete_interview_state(
            session,
            interview=interview,
            candidate=candidate,
            job=job,
            report=existing,
            report_data=report_data,
        )

    report_data = ai_interviewer.generate_report(
        candidate=candidate,
        job=job,
        profile=profile,
        resume=resume,
        transcripts=transcripts,
    )

    report = InterviewReport(
        interview_id=interview.id,
        candidate_id=candidate.id,
        summary=report_data.get("summary", ""),
        strengths=report_data.get("strengths", ""),
        weaknesses=report_data.get("weaknesses", ""),
        key_observations=report_data.get("key_observations", ""),
        technical_assessment=report_data.get("technical_assessment", ""),
        behavioral_assessment=report_data.get("behavioral_assessment", ""),
        recommendation=report_data.get("recommendation", "Borderline"),
        recommendation_reason=report_data.get("recommendation_reason", ""),
        raw_json=report_data.get("raw_json"),
    )
    session.add(report)
    session.commit()
    session.refresh(report)

    return _complete_interview_state(
        session,
        interview=interview,
        candidate=candidate,
        job=job,
        report=report,
        report_data=report_data,
    )


@router.get("/magic-links/{token}/verify")
def verify_magic_link(token: str, session: Session = Depends(get_session)):
    link = _magic_link_or_404(session, token)
    candidate, job = _candidate_and_job(session, link)
    return {
        "status": "valid",
        "candidate": {
            "full_name": candidate.full_name,
            "email": mask_email(candidate.email),
            "current_role": candidate.current_role,
        },
        "job": {"job_title": job.job_title, "company_name": job.company_name},
        "expires_at": link.expires_at.isoformat(),
    }


@router.post("/magic-links/{token}/send-otp")
def send_otp(token: str, session: Session = Depends(get_session)):
    link = _magic_link_or_404(session, token)
    candidate, job = _candidate_and_job(session, link)
    otp = generate_otp()
    otp_record = OtpVerification(
        candidate_id=candidate.id,
        interview_link_id=link.id,
        otp_hash=hash_secret(otp),
        expires_at=expires_in(minutes=settings.otp_expiry_minutes),
    )
    session.add(otp_record)
    session.commit()

    subject, body = otp_template(candidate, otp)
    email_log = send_email(
        session,
        recipient_email=candidate.email,
        subject=subject,
        body=body,
        email_type="otp_verification",
        candidate_id=candidate.id,
        job_id=job.id,
    )
    payload = {
        "status": "otp_sent",
        "email": mask_email(candidate.email),
        "email_status": email_log.status,
        "expires_at": otp_record.expires_at.isoformat(),
    }
    return payload


@router.post("/magic-links/{token}/verify-otp", response_model=CandidateSessionResponse)
def verify_otp(token: str, payload: OtpVerifyRequest, session: Session = Depends(get_session)):
    link = _magic_link_or_404(session, token)
    candidate, job = _candidate_and_job(session, link)
    otp = session.exec(
        select(OtpVerification)
        .where(OtpVerification.interview_link_id == link.id)
        .order_by(OtpVerification.created_at.desc())
    ).first()
    if not otp or otp.verified_at or is_expired(otp.expires_at):
        raise HTTPException(status_code=400, detail="OTP is missing or expired")
    if otp.attempts >= 5:
        raise HTTPException(status_code=429, detail="Too many OTP attempts")

    otp.attempts += 1
    if hash_secret(payload.otp.strip()) != otp.otp_hash:
        session.add(otp)
        session.commit()
        raise HTTPException(status_code=400, detail="Invalid OTP")

    session_token = generate_token()
    verified_at = utcnow()
    otp.verified_at = verified_at
    session.add(otp)
    link.otp_verified_at = verified_at
    link.consumed_at = verified_at
    link.candidate_session_token_hash = hash_secret(session_token)
    link.session_expires_at = expires_in(hours=settings.candidate_session_expiry_hours)
    session.add(link)
    session.commit()
    return CandidateSessionResponse(
        access_token=session_token,
        candidate=_candidate_payload(candidate),
        job=_job_payload(job),
        expires_at=link.session_expires_at.isoformat(),
    )


@router.get("/session/me")
def session_me(link: InterviewLink = Depends(get_candidate_link), session: Session = Depends(get_session)):
    candidate, job = _candidate_and_job(session, link)
    profile = _profile(session, candidate.id)
    resume = _latest_resume(session, candidate.id)
    return {
        "candidate": _candidate_payload(candidate),
        "job": _job_payload(job),
        "profile": profile.model_dump() if profile else None,
        "resume": resume.model_dump() if resume else None,
    }


@router.post("/session/profile")
async def submit_profile(
    current_ctc: str = Form(...),
    expected_ctc: str = Form(...),
    notice_period: str = Form(...),
    current_location: str = Form(...),
    linkedin_url: Optional[str] = Form(None),
    portfolio_url: Optional[str] = Form(None),
    resume: UploadFile = File(...),
    link: InterviewLink = Depends(get_candidate_link),
    session: Session = Depends(get_session),
):
    candidate, job = _candidate_and_job(session, link)
    extension = Path(resume.filename or "").suffix.lower()
    if extension not in SUPPORTED_RESUME_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Resume must be PDF, DOC, or DOCX")

    file_bytes = await resume.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Resume upload is required")

    parsed_text = parse_resume(file_bytes, resume.filename or "resume")
    storage = upload_resume(
        file_bytes,
        candidate_id=candidate.id,
        filename=resume.filename or "resume",
        content_type=resume.content_type or "application/octet-stream",
    )
    resume_record = Resume(
        candidate_id=candidate.id,
        file_name=resume.filename or "resume",
        content_type=resume.content_type or "application/octet-stream",
        storage_bucket=storage["bucket"] or settings.supabase_storage_resumes_bucket,
        storage_path=storage["path"] or "",
        public_url=storage["public_url"],
        parsed_text=parsed_text,
    )
    session.add(resume_record)

    profile = _profile(session, candidate.id)
    if not profile:
        profile = CandidateProfile(
            candidate_id=candidate.id,
            current_ctc=current_ctc,
            expected_ctc=expected_ctc,
            notice_period=notice_period,
            current_location=current_location,
            linkedin_url=linkedin_url,
            portfolio_url=portfolio_url,
        )
    else:
        profile.current_ctc = current_ctc
        profile.expected_ctc = expected_ctc
        profile.notice_period = notice_period
        profile.current_location = current_location
        profile.linkedin_url = linkedin_url
        profile.portfolio_url = portfolio_url
        profile.updated_at = utcnow()
    session.add(profile)

    _get_or_create_interview(session, link)
    log_activity(session, action="candidate_profile_submitted", candidate_id=candidate.id, job_id=job.id)
    session.commit()
    session.refresh(profile)
    session.refresh(resume_record)
    return {"profile": profile.model_dump(), "resume": resume_record.model_dump()}


@router.post("/session/interview/start")
def start_interview(link: InterviewLink = Depends(get_candidate_link), session: Session = Depends(get_session)):
    candidate, job = _candidate_and_job(session, link)
    profile = _profile(session, candidate.id)
    resume = _latest_resume(session, candidate.id)
    if not profile or not resume:
        raise HTTPException(status_code=400, detail="Candidate profile and resume are required before interview")

    interview = _get_or_create_interview(session, link)
    transcripts = _transcripts(session, interview.id)
    if not transcripts:
        next_question = ai_interviewer.generate_next_question(
            candidate=candidate,
            job=job,
            profile=profile,
            resume=resume,
            transcripts=[],
            max_questions=interview.max_questions,
        )
        transcript = InterviewTranscript(
            interview_id=interview.id,
            sequence_number=1,
            question_text=next_question["question"],
            category=next_question["category"],
            difficulty=next_question["difficulty"],
        )
        interview.status = "in_progress"
        interview.started_at = interview.started_at or utcnow()
        interview.current_question_index = 1
        session.add(transcript)
        session.add(interview)
        session.commit()
        session.refresh(transcript)
        transcripts = [transcript]

    return {
        "interview": interview.model_dump(),
        "current_question": transcripts[-1].model_dump(),
        "avatar_url": "/platform/assets/ai-human-interviewer.png",
    }


@router.post("/session/interview/answer")
def submit_answer(
    payload: InterviewAnswerRequest,
    link: InterviewLink = Depends(get_candidate_link),
    session: Session = Depends(get_session),
):
    candidate, job = _candidate_and_job(session, link)
    profile = _profile(session, candidate.id)
    resume = _latest_resume(session, candidate.id)
    interview = _interview(session, link)
    if not interview or interview.status not in {"in_progress", "not_started"}:
        raise HTTPException(status_code=400, detail="Interview is not active")

    transcripts = _transcripts(session, interview.id)
    if not transcripts:
        raise HTTPException(status_code=400, detail="Start the interview before answering")

    current = next((item for item in reversed(transcripts) if not item.answer_text), None)
    if not current:
        raise HTTPException(status_code=400, detail="No pending question to answer")

    current.answer_text = payload.answer_text.strip()
    current.answered_at = utcnow()
    session.add(current)
    session.commit()
    transcripts = _transcripts(session, interview.id)

    if len(transcripts) >= interview.max_questions:
        report = _finalize_interview(session, interview)
        return {"is_complete": True, "report_id": report.id, "current_question": None}

    next_question = ai_interviewer.generate_next_question(
        candidate=candidate,
        job=job,
        profile=profile,
        resume=resume,
        transcripts=transcripts,
        max_questions=interview.max_questions,
    )
    next_transcript = InterviewTranscript(
        interview_id=interview.id,
        sequence_number=len(transcripts) + 1,
        question_text=next_question["question"],
        category=next_question["category"],
        difficulty=next_question["difficulty"],
        follow_up_of=current.id if next_question["category"] == "follow_up" else None,
    )
    interview.current_question_index = next_transcript.sequence_number
    session.add(next_transcript)
    session.add(interview)
    session.commit()
    session.refresh(next_transcript)
    return {"is_complete": False, "current_question": next_transcript.model_dump()}


@router.post("/session/interview/complete")
def complete_interview(link: InterviewLink = Depends(get_candidate_link), session: Session = Depends(get_session)):
    interview = _interview(session, link)
    if not interview:
        raise HTTPException(status_code=400, detail="Interview has not started")
    report = _finalize_interview(session, interview)
    return {"is_complete": True, "report_id": report.id}


@router.get("/session/report")
def candidate_report(link: InterviewLink = Depends(get_candidate_link), session: Session = Depends(get_session)):
    interview = _interview(session, link)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    report = session.exec(select(InterviewReport).where(InterviewReport.interview_id == interview.id)).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not generated yet")
    return {
        "interview": {
            "id": interview.id,
            "status": "completed" if interview.status == "completed" else interview.status,
            "completed_at": interview.completed_at.isoformat() if interview.completed_at else None,
        },
        "message": "Your interview has been submitted to the recruiter.",
    }
