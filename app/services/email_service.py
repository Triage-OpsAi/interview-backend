import html
import re
import smtplib
from email.message import EmailMessage
from typing import Optional

from sqlmodel import Session

from ..config import settings
from ..models import Candidate, EmailLog, JobDescription
from ..security import utcnow

URL_PATTERN = re.compile(r"https?://[^\s<]+")


def _linkify_html(text: str) -> str:
    parts = []
    last_index = 0
    for match in URL_PATTERN.finditer(text):
        url = match.group(0)
        parts.append(html.escape(text[last_index : match.start()]))
        escaped_url = html.escape(url, quote=True)
        parts.append(f'<a href="{escaped_url}">{escaped_url}</a>')
        last_index = match.end()
    parts.append(html.escape(text[last_index:]))
    return "".join(parts)


def _html_email_body(body: str) -> str:
    content = _linkify_html(body).replace("\n", "<br>\n")
    return f"""<!doctype html>
<html>
<body style="font-family: Arial, sans-serif; line-height: 1.5; color: #111827;">
{content}
</body>
</html>"""


def invitation_template(candidate: Candidate, job: JobDescription, magic_link: str) -> tuple[str, str, str]:
    subject = f"Interview invitation for {job.job_title} at {job.company_name}"
    body = f"""Hi {candidate.full_name},

You have been invited to complete an AI human interviewer screening for the {job.job_title} role at {job.company_name}.

Open your secure magic link to begin:
{magic_link}

For security, you will receive a one-time password after opening the link.

Best,
Hiring Team
"""
    escaped_name = html.escape(candidate.full_name)
    escaped_role = html.escape(job.job_title)
    escaped_company = html.escape(job.company_name)
    escaped_link = html.escape(magic_link, quote=True)
    html_body = f"""<!doctype html>
<html>
<body style="margin:0; padding:24px; font-family:Arial, sans-serif; line-height:1.5; color:#111827; background:#ffffff;">
  <p>Hi {escaped_name},</p>
  <p>You have been invited to complete an AI human interviewer screening for the {escaped_role} role at {escaped_company}.</p>
  <p style="margin:24px 0;">
    <a href="{escaped_link}" style="display:inline-block; padding:12px 18px; border-radius:6px; background:#0f766e; color:#ffffff; font-weight:700; text-decoration:none;">
      Open interview link
    </a>
  </p>
  <p style="font-size:13px; color:#4b5563;">If the button does not open, use this link:</p>
  <p><a href="{escaped_link}" style="color:#0f766e; word-break:break-all;">{escaped_link}</a></p>
  <p>For security, you will receive a one-time password after opening the link.</p>
  <p>Best,<br>Hiring Team</p>
</body>
</html>"""
    return subject, body, html_body


def otp_template(candidate: Candidate, otp: str) -> tuple[str, str]:
    subject = "Your interview verification OTP"
    body = f"""Hi {candidate.full_name},

Your one-time password for the interview is:

{otp}

This OTP expires shortly. If you did not request this, ignore this email.

Best,
Hiring Team
"""
    return subject, body


def next_round_template(candidate: Candidate, job: JobDescription) -> tuple[str, str]:
    subject = f"Next round for {job.job_title}"
    body = f"""Hi {candidate.full_name},

Congratulations. Based on your interview for the {job.job_title} role at {job.company_name}, we would like to move you to the next round.

Our hiring team will contact you with the next steps.

Best,
Hiring Team
"""
    return subject, body


def rejection_template(candidate: Candidate, job: JobDescription) -> tuple[str, str]:
    subject = f"Update on your {job.job_title} application"
    body = f"""Hi {candidate.full_name},

Thank you for taking the time to interview for the {job.job_title} role at {job.company_name}.

After careful review, we will not be moving forward at this stage. We appreciate your interest and wish you the best in your search.

Best,
Hiring Team
"""
    return subject, body


def recruiter_invitation_template(full_name: str, manager_name: str, onboarding_link: str) -> tuple[str, str, str]:
    subject = "Complete your InterviewOS recruiter onboarding"
    body = f"""Hi {full_name},

{manager_name} invited you to join their InterviewOS hiring workspace as a Recruiter.

Complete your secure onboarding here:
{onboarding_link}

This invitation expires in 72 hours.

Best,
InterviewOS
"""
    safe_name = html.escape(full_name)
    safe_manager = html.escape(manager_name)
    safe_link = html.escape(onboarding_link, quote=True)
    html_body = f"""<!doctype html><html><body style="margin:0;padding:32px;background:#f6f7fc;font-family:Arial,sans-serif;color:#101427">
<div style="max-width:560px;margin:auto;background:white;border:1px solid #e2e7f0;border-radius:18px;padding:32px">
<h2 style="margin:0 0 16px">Welcome to InterviewOS</h2><p>Hi {safe_name},</p><p>{safe_manager} invited you to join their hiring workspace as a Recruiter.</p>
<p style="margin:28px 0"><a href="{safe_link}" style="display:inline-block;padding:13px 20px;border-radius:10px;background:#5546e8;color:white;font-weight:700;text-decoration:none">Complete onboarding</a></p>
<p style="font-size:13px;color:#64748b">This secure invitation expires in 72 hours.</p></div></body></html>"""
    return subject, body, html_body


def round_two_template(candidate: Candidate, job: JobDescription, link: str) -> tuple[str, str, str]:
    subject = f"Round 2 technical interview for {job.job_title}"
    body = f"""Hi {candidate.full_name},

You have been invited to Round 2 for the {job.job_title} role at {job.company_name}.

This is a proctored 20-minute technical interview with up to 12 questions and in-screen coding tasks. Camera, tab changes, focus changes, and unusual movement are recorded as proctoring events and shown to you during the session.

Open your secure link:
{link}

Best,
Hiring Team
"""
    safe_link = html.escape(link, quote=True)
    html_body = _html_email_body(body).replace(html.escape(link), f'<a href="{safe_link}">{safe_link}</a>')
    return subject, body, html_body


def send_email(
    session: Session,
    *,
    recipient_email: str,
    subject: str,
    body: str,
    html_body: Optional[str] = None,
    email_type: str,
    candidate_id: Optional[str] = None,
    job_id: Optional[str] = None,
) -> EmailLog:
    status = "logged"
    error_message = None
    sent_at = None

    if settings.smtp_host:
        try:
            message = EmailMessage()
            message["From"] = settings.smtp_from_email
            message["To"] = recipient_email
            message["Subject"] = subject
            message.set_content(body)
            message.add_alternative(html_body or _html_email_body(body), subtype="html")

            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
                if settings.smtp_use_tls:
                    smtp.starttls()
                if settings.smtp_username:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)

            status = "sent"
            sent_at = utcnow()
        except Exception as exc:
            status = "failed"
            error_message = str(exc)

    log = EmailLog(
        candidate_id=candidate_id,
        job_id=job_id,
        email_type=email_type,
        recipient_email=recipient_email,
        subject=subject,
        body=body,
        status=status,
        error_message=error_message,
        sent_at=sent_at,
    )
    session.add(log)
    session.commit()
    session.refresh(log)
    return log
