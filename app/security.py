import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from .config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def expires_in(**kwargs) -> datetime:
    return utcnow() + timedelta(**kwargs)


def utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def is_expired(value: Optional[datetime], *, now: Optional[datetime] = None) -> bool:
    if value is None:
        return True
    return utc_naive(value) <= utc_naive(now or utcnow())


def elapsed_seconds(start: datetime, end: datetime) -> int:
    return int((utc_naive(end) - utc_naive(start)).total_seconds())


def generate_token(bytes_len: int = 32) -> str:
    return secrets.token_urlsafe(bytes_len)


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_secret(value: str) -> str:
    return hmac.new(settings.app_secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, stored_hash: Optional[str]) -> bool:
    if not stored_hash:
        return False
    try:
        method, salt, expected = stored_hash.split("$", 2)
    except ValueError:
        return False
    if method != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return hmac.compare_digest(digest.hex(), expected)


def mask_email(email: str) -> str:
    if "@" not in email:
        return email
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        return f"{local[0]}***@{domain}"
    return f"{local[0]}***{local[-1]}@{domain}"
