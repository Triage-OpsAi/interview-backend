from contextlib import asynccontextmanager
import re

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import init_db
from .routers import auth, candidate, recruiter, reports


def _safe_error_message(exc: Exception) -> str:
    message = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
    message = re.sub(r"([A-Za-z][A-Za-z0-9+.-]*://)([^@\s]+)@", r"\1***@", message)
    return f"{exc.__class__.__name__}: {message[:300]}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.database_ready = False
    app.state.database_error = None
    try:
        init_db()
        app.state.database_ready = True
    except Exception as exc:
        app.state.database_error = _safe_error_message(exc)
        print(f"Database initialization failed: {app.state.database_error}", flush=True)
    yield


app = FastAPI(
    title="AI Human Interview Platform",
    version="2.0.0",
    description="Recruiter JD platform with secure candidate magic links, OTP, AI human interviewer flow, and hiring reports.",
    lifespan=lifespan,
)

origins = [origin.strip() for origin in settings.cors_origins.split(",")] if settings.cors_origins != "*" else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(recruiter.router)
app.include_router(candidate.router)
app.include_router(reports.router)


@app.get("/")
def root():
    return {"status": "ok", "service": "ai-human-interview-platform"}


@app.get("/health")
def health(request: Request):
    database_ready = getattr(request.app.state, "database_ready", False)
    payload = {
        "status": "ok" if database_ready else "degraded",
        "service": "ai-human-interview-platform",
        "database": "ok" if database_ready else "unavailable",
    }
    if not database_ready:
        payload["database_error"] = getattr(request.app.state, "database_error", None)
    return payload
