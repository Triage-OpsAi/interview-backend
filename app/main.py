from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import init_db
from .routers import auth, candidate, recruiter, reports


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
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

@app.get("/health")
def health():
    return {"status": "ok", "service": "ai-human-interview-platform"}
