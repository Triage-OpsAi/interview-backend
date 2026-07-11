from typing import List, Optional

from pydantic import BaseModel


class AuthRegisterRequest(BaseModel):
    full_name: str
    email: str
    password: str


class AuthLoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class JobCreateRequest(BaseModel):
    job_title: str
    company_name: str
    department: str
    experience_required: str
    location: str
    employment_type: str
    skills_required: str
    responsibilities: str
    full_job_description: str


class JobUpdateRequest(BaseModel):
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    department: Optional[str] = None
    experience_required: Optional[str] = None
    location: Optional[str] = None
    employment_type: Optional[str] = None
    skills_required: Optional[str] = None
    responsibilities: Optional[str] = None
    full_job_description: Optional[str] = None


class CandidateCreateRequest(BaseModel):
    full_name: str
    email: str
    mobile_number: str
    current_role: str
    current_company: Optional[str] = None
    status: str = "Pending Interview"


class CandidateUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    mobile_number: Optional[str] = None
    current_role: Optional[str] = None
    current_company: Optional[str] = None
    status: Optional[str] = None


class ConductInterviewRequest(BaseModel):
    candidate_ids: List[str]


class MagicLinkResponse(BaseModel):
    candidate_id: str
    email: str
    magic_link: str
    email_status: str
    expires_at: str


class OtpVerifyRequest(BaseModel):
    otp: str


class CandidateSessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    candidate: dict
    job: dict
    expires_at: str


class InterviewAnswerRequest(BaseModel):
    answer_text: str


class CandidateActionResponse(BaseModel):
    candidate_id: str
    status: str
    email_status: str


class ReportAskRequest(BaseModel):
    question: str


class ReportAskResponse(BaseModel):
    answer: str
