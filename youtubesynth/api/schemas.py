"""Pydantic v2 request/response models for the YouTubeSynth API."""

from typing import Any, Optional
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class ConfirmRequest(BaseModel):
    pass  # POST /confirm has no body — action is implicit


class CancelRequest(BaseModel):
    pass  # POST /cancel has no body — action is implicit


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class JobSubmitResponse(BaseModel):
    job_id: str
    status: str
    video_count: int


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    style: Optional[str] = None
    title: Optional[str] = None
    total_videos: int
    done_videos: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ConfirmResponse(BaseModel):
    job_id: str
    status: str


class CancelResponse(BaseModel):
    job_id: str
    status: str


class JobResultResponse(BaseModel):
    job_id: str
    status: str
    output: str                    # contents of overall_summary.md
    token_report: dict[str, Any]  # contents of token_report.json
