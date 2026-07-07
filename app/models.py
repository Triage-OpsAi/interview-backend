import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from .security import utcnow


def gen_id() -> str:
    return str(uuid.uuid4())


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: str = Field(default_factory=gen_id, primary_key=True)
    full_name: str
    email: str = Field(index=True, unique=True)
    role: str = Field(default="recruiter")
    password_hash: str
    session_token_hash: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    last_login_at: Optional[datetime] = None


class JobDescription(SQLModel, table=True):
    __tablename__ = "job_descriptions"

    id: str = Field(default_factory=gen_id, primary_key=True)
    created_by: str = Field(foreign_key="users.id", index=True)
    job_title: str
    company_name: str
    department: str
    experience_required: str
    location: str
    employment_type: str
    skills_required: str = Field(sa_column=Column(Text))
    responsibilities: str = Field(sa_column=Column(Text))
    full_job_description: str = Field(sa_column=Column(Text))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Candidate(SQLModel, table=True):
    __tablename__ = "candidates"

    id: str = Field(default_factory=gen_id, primary_key=True)
    job_id: str = Field(foreign_key="job_descriptions.id", index=True)
    created_by: str = Field(foreign_key="users.id", index=True)
    full_name: str
    email: str = Field(index=True)
    mobile_number: str
    current_role: str
    current_company: Optional[str] = None
    status: str = Field(default="Pending Interview", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class InterviewLink(SQLModel, table=True):
    __tablename__ = "interview_links"

    id: str = Field(default_factory=gen_id, primary_key=True)
    candidate_id: str = Field(foreign_key="candidates.id", index=True)
    job_id: str = Field(foreign_key="job_descriptions.id", index=True)
    token_hash: str = Field(index=True, unique=True)
    magic_link: str = Field(sa_column=Column(Text))
    expires_at: datetime = Field(index=True)
    consumed_at: Optional[datetime] = Field(default=None, index=True)
    otp_verified_at: Optional[datetime] = None
    candidate_session_token_hash: Optional[str] = Field(default=None, index=True, unique=True)
    session_expires_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)


class OtpVerification(SQLModel, table=True):
    __tablename__ = "otp_verifications"

    id: str = Field(default_factory=gen_id, primary_key=True)
    candidate_id: str = Field(foreign_key="candidates.id", index=True)
    interview_link_id: str = Field(foreign_key="interview_links.id", index=True)
    otp_hash: str
    purpose: str = Field(default="interview_access")
    expires_at: datetime = Field(index=True)
    verified_at: Optional[datetime] = None
    attempts: int = Field(default=0)
    created_at: datetime = Field(default_factory=utcnow)


class CandidateProfile(SQLModel, table=True):
    __tablename__ = "candidate_profiles"

    id: str = Field(default_factory=gen_id, primary_key=True)
    candidate_id: str = Field(foreign_key="candidates.id", index=True, unique=True)
    current_ctc: str
    expected_ctc: str
    notice_period: str
    current_location: str
    linkedin_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Resume(SQLModel, table=True):
    __tablename__ = "resumes"

    id: str = Field(default_factory=gen_id, primary_key=True)
    candidate_id: str = Field(foreign_key="candidates.id", index=True)
    file_name: str
    content_type: str
    storage_bucket: str
    storage_path: str = Field(sa_column=Column(Text))
    public_url: Optional[str] = Field(default=None, sa_column=Column(Text))
    parsed_text: Optional[str] = Field(default=None, sa_column=Column(Text))
    uploaded_at: datetime = Field(default_factory=utcnow)


class Interview(SQLModel, table=True):
    __tablename__ = "interviews"

    id: str = Field(default_factory=gen_id, primary_key=True)
    candidate_id: str = Field(foreign_key="candidates.id", index=True)
    job_id: str = Field(foreign_key="job_descriptions.id", index=True)
    interview_link_id: Optional[str] = Field(default=None, foreign_key="interview_links.id", index=True)
    status: str = Field(default="not_started", index=True)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    max_questions: int = Field(default=10)
    current_question_index: int = Field(default=0)
    overall_score: Optional[int] = None
    created_at: datetime = Field(default_factory=utcnow)


class InterviewTranscript(SQLModel, table=True):
    __tablename__ = "interview_transcripts"
    __table_args__ = (UniqueConstraint("interview_id", "sequence_number", name="uq_interview_transcript_sequence"),)

    id: str = Field(default_factory=gen_id, primary_key=True)
    interview_id: str = Field(foreign_key="interviews.id", index=True)
    sequence_number: int
    question_text: str = Field(sa_column=Column(Text))
    answer_text: Optional[str] = Field(default=None, sa_column=Column(Text))
    category: Optional[str] = None
    difficulty: Optional[str] = None
    follow_up_of: Optional[str] = Field(default=None, foreign_key="interview_transcripts.id")
    asked_at: datetime = Field(default_factory=utcnow)
    answered_at: Optional[datetime] = None


class InterviewReport(SQLModel, table=True):
    __tablename__ = "interview_reports"

    id: str = Field(default_factory=gen_id, primary_key=True)
    interview_id: str = Field(foreign_key="interviews.id", index=True, unique=True)
    candidate_id: str = Field(foreign_key="candidates.id", index=True)
    summary: str = Field(sa_column=Column(Text))
    strengths: str = Field(sa_column=Column(Text))
    weaknesses: str = Field(sa_column=Column(Text))
    key_observations: str = Field(sa_column=Column(Text))
    technical_assessment: str = Field(sa_column=Column(Text))
    behavioral_assessment: str = Field(sa_column=Column(Text))
    recommendation: str
    recommendation_reason: str = Field(sa_column=Column(Text))
    raw_json: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(default_factory=utcnow)


class CandidateScore(SQLModel, table=True):
    __tablename__ = "candidate_scores"

    id: str = Field(default_factory=gen_id, primary_key=True)
    report_id: str = Field(foreign_key="interview_reports.id", index=True)
    interview_id: str = Field(foreign_key="interviews.id", index=True)
    candidate_id: str = Field(foreign_key="candidates.id", index=True)
    category: str
    score: int
    reasoning: Optional[str] = Field(default=None, sa_column=Column(Text))


class EmailLog(SQLModel, table=True):
    __tablename__ = "email_logs"

    id: str = Field(default_factory=gen_id, primary_key=True)
    candidate_id: Optional[str] = Field(default=None, foreign_key="candidates.id", index=True)
    job_id: Optional[str] = Field(default=None, foreign_key="job_descriptions.id", index=True)
    email_type: str
    recipient_email: str
    subject: str
    body: str = Field(sa_column=Column(Text))
    status: str
    error_message: Optional[str] = Field(default=None, sa_column=Column(Text))
    sent_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)


class ActivityLog(SQLModel, table=True):
    __tablename__ = "activity_logs"

    id: str = Field(default_factory=gen_id, primary_key=True)
    actor_user_id: Optional[str] = Field(default=None, foreign_key="users.id", index=True)
    candidate_id: Optional[str] = Field(default=None, foreign_key="candidates.id", index=True)
    job_id: Optional[str] = Field(default=None, foreign_key="job_descriptions.id", index=True)
    action: str
    details: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(default_factory=utcnow)
