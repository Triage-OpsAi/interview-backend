import re
from pathlib import Path
from typing import Dict, Optional

import requests

from ..config import LOCAL_STORAGE_DIR, settings


def _safe_filename(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-")
    return cleaned or "resume"


def upload_resume(file_bytes: bytes, *, candidate_id: str, filename: str, content_type: str) -> Dict[str, Optional[str]]:
    safe_name = _safe_filename(filename)
    object_path = f"{candidate_id}/{safe_name}"
    bucket = settings.supabase_storage_resumes_bucket

    if settings.supabase_url and settings.supabase_service_role_key:
        base = settings.supabase_url.rstrip("/")
        url = f"{base}/storage/v1/object/{bucket}/{object_path}"
        headers = {
            "Authorization": f"Bearer {settings.supabase_service_role_key}",
            "apikey": settings.supabase_service_role_key,
            "Content-Type": content_type or "application/octet-stream",
            "x-upsert": "true",
        }
        response = requests.post(url, headers=headers, data=file_bytes, timeout=60)
        response.raise_for_status()
        return {
            "bucket": bucket,
            "path": object_path,
            "public_url": f"{base}/storage/v1/object/{bucket}/{object_path}",
        }

    local_dir = LOCAL_STORAGE_DIR / "resumes" / candidate_id
    local_dir.mkdir(parents=True, exist_ok=True)
    destination = local_dir / safe_name
    destination.write_bytes(file_bytes)
    return {"bucket": "local-resumes", "path": str(destination), "public_url": None}
