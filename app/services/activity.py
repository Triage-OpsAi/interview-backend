from typing import Optional

from sqlmodel import Session

from ..models import ActivityLog


def log_activity(
    session: Session,
    *,
    action: str,
    actor_user_id: Optional[str] = None,
    candidate_id: Optional[str] = None,
    job_id: Optional[str] = None,
    details: Optional[str] = None,
) -> None:
    # Ensure newly created parent rows exist before the activity row checks FKs.
    session.flush()
    session.add(
        ActivityLog(
            actor_user_id=actor_user_id,
            candidate_id=candidate_id,
            job_id=job_id,
            action=action,
            details=details,
        )
    )
