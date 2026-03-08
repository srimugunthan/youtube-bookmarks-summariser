"""FastAPI route definitions for the YouTubeSynth API."""

import json
import os
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse

from youtubesynth.api.schemas import (
    CancelResponse,
    ConfirmResponse,
    JobResultResponse,
    JobStatusResponse,
    JobSubmitResponse,
)
from youtubesynth.api.sse import APIConfirmationEmitter, sse_manager
from youtubesynth.config import settings
from youtubesynth.exceptions import ExtractionError
from youtubesynth.extractors import extract_urls
from youtubesynth.pipeline import run_pipeline
from youtubesynth.services.db import Database
from youtubesynth.services.gemini_client import GeminiClient

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# GET /api/config
# ---------------------------------------------------------------------------

@router.get("/config")
async def get_config() -> dict:
    return {"has_server_key": bool(settings.gemini_api_key)}


# ---------------------------------------------------------------------------
# Background pipeline runner
# ---------------------------------------------------------------------------

async def _run_pipeline_bg(
    job_id: str,
    videos: list,
    style: str,
    title: Optional[str],
    concurrency: int,
    no_cache: bool,
    api_key: Optional[str],
    db: Database,
) -> None:
    """Background task: run pipeline and emit job_done/job_failed via SSE."""
    try:
        gemini_client = GeminiClient(api_key=api_key) if api_key else GeminiClient()
        confirmation_emitter = APIConfirmationEmitter(db=db)

        await run_pipeline(
            job_id=job_id,
            videos=videos,
            style=style,
            title=title,
            output_dir=settings.output_dir,
            concurrency=concurrency,
            no_cache=no_cache,
            db=db,
            gemini_client=gemini_client,
            progress_callback=_SSEProgressEmitter(),
            confirmation_callback=confirmation_emitter,
        )
    except Exception as exc:
        await sse_manager.emit(job_id, "job_failed", {
            "job_id": job_id,
            "error": str(exc),
        })
        await db.update_job_status(job_id, "failed")
    finally:
        import asyncio
        await asyncio.sleep(1)
        sse_manager.unregister(job_id)


class _SSEProgressEmitter:
    """Bridges pipeline ProgressEmitter protocol to SSEManager."""

    async def emit(self, job_id: str, event: str, data: dict) -> None:
        await sse_manager.emit(job_id, event, data)


# ---------------------------------------------------------------------------
# POST /api/jobs
# ---------------------------------------------------------------------------

@router.post("/jobs", response_model=JobSubmitResponse, status_code=202)
async def submit_job(
    request: Request,
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(default=None),
    playlist_url: Optional[str] = Form(default=None),
    style: str = Form(default="article"),
    title: Optional[str] = Form(default=None),
    max_videos: Optional[int] = Form(default=None),
    concurrency: Optional[int] = Form(default=None),
    no_cache: bool = Form(default=False),
    x_gemini_api_key: Optional[str] = Header(default=None),
) -> JobSubmitResponse:
    if file is None and playlist_url is None:
        raise HTTPException(status_code=422, detail="Provide either 'file' or 'playlist_url'.")
    if file is not None and playlist_url is not None:
        raise HTTPException(status_code=422, detail="Provide 'file' OR 'playlist_url', not both.")

    api_key = x_gemini_api_key or settings.gemini_api_key
    if not api_key:
        raise HTTPException(status_code=422, detail="GEMINI_API_KEY is not configured.")

    _max_videos = max_videos if max_videos is not None else settings.max_videos_per_job
    _concurrency = concurrency if concurrency is not None else settings.default_concurrency

    if file is not None:
        import tempfile
        suffix = os.path.splitext(file.filename or "")[1] or ".txt"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        try:
            videos = extract_urls(tmp_path, max_videos=_max_videos)
        except ExtractionError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        finally:
            os.unlink(tmp_path)
    else:
        try:
            videos = extract_urls(playlist_url, max_videos=_max_videos)
        except ExtractionError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    job_id = uuid.uuid4().hex[:8]
    db: Database = request.app.state.db

    sse_manager.register(job_id)

    background_tasks.add_task(
        _run_pipeline_bg,
        job_id=job_id,
        videos=videos,
        style=style,
        title=title,
        concurrency=_concurrency,
        no_cache=no_cache,
        api_key=x_gemini_api_key,
        db=db,
    )

    return JobSubmitResponse(job_id=job_id, status="fetching", video_count=len(videos))


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/stream  — SSE
# ---------------------------------------------------------------------------

@router.get("/jobs/{job_id}/stream")
async def stream_job(job_id: str, request: Request) -> StreamingResponse:
    db: Database = request.app.state.db
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")

    return StreamingResponse(
        sse_manager.stream_events(job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}
# ---------------------------------------------------------------------------

@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str, request: Request) -> JobStatusResponse:
    db: Database = request.app.state.db
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")
    return JobStatusResponse(
        job_id=job["job_id"],
        status=job["status"],
        style=job.get("style"),
        title=job.get("title"),
        total_videos=job["total_videos"],
        done_videos=job["done_videos"],
        created_at=job.get("created_at"),
        updated_at=job.get("updated_at"),
    )


# ---------------------------------------------------------------------------
# POST /api/jobs/{job_id}/confirm
# ---------------------------------------------------------------------------

@router.post("/jobs/{job_id}/confirm", response_model=ConfirmResponse)
async def confirm_job(job_id: str, request: Request) -> ConfirmResponse:
    db: Database = request.app.state.db
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")
    if job["status"] != "pending_confirmation":
        raise HTTPException(
            status_code=409,
            detail=f"Job {job_id!r} is in status {job['status']!r}, not 'pending_confirmation'.",
        )
    sse_manager.set_confirmed(job_id)
    return ConfirmResponse(job_id=job_id, status="running")


# ---------------------------------------------------------------------------
# POST /api/jobs/{job_id}/cancel
# ---------------------------------------------------------------------------

@router.post("/jobs/{job_id}/cancel", response_model=CancelResponse)
async def cancel_job(job_id: str, request: Request) -> CancelResponse:
    db: Database = request.app.state.db
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")
    sse_manager.set_cancelled(job_id)
    await sse_manager.emit(job_id, "job_cancelled", {"job_id": job_id})
    return CancelResponse(job_id=job_id, status="cancelled")


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/result
# ---------------------------------------------------------------------------

@router.get("/jobs/{job_id}/result", response_model=JobResultResponse)
async def get_result(job_id: str, request: Request) -> JobResultResponse:
    db: Database = request.app.state.db
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")
    if job["status"] != "done":
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} is not done yet.")

    result_path = os.path.join(settings.output_dir, job_id, "overall_summary.md")
    report_path = os.path.join(settings.output_dir, job_id, "token_report.json")

    if not os.path.exists(result_path):
        raise HTTPException(status_code=404, detail="Result file not found.")

    with open(result_path, encoding="utf-8") as f:
        output = f.read()

    token_report: dict = {}
    if os.path.exists(report_path):
        with open(report_path, encoding="utf-8") as f:
            token_report = json.load(f)

    return JobResultResponse(job_id=job_id, status="done", output=output, token_report=token_report)


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/download
# ---------------------------------------------------------------------------

@router.get("/jobs/{job_id}/download")
async def download_result(job_id: str, request: Request) -> FileResponse:
    db: Database = request.app.state.db
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")
    if job["status"] != "done":
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} is not done yet.")

    result_path = os.path.join(settings.output_dir, job_id, "overall_summary.md")
    if not os.path.exists(result_path):
        raise HTTPException(status_code=404, detail="Result file not found.")

    return FileResponse(
        result_path,
        media_type="text/markdown",
        filename=f"youtubesynth_{job_id}.md",
    )


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/transcripts
# ---------------------------------------------------------------------------

@router.get("/jobs/{job_id}/transcripts")
async def download_transcripts(job_id: str, request: Request) -> FileResponse:
    db: Database = request.app.state.db
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")
    if job["status"] != "done":
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} is not done yet.")

    transcripts_path = os.path.join(settings.output_dir, job_id, "transcripts.md")
    if not os.path.exists(transcripts_path):
        raise HTTPException(status_code=404, detail="Transcripts file not found.")

    return FileResponse(
        transcripts_path,
        media_type="text/markdown",
        filename=f"transcripts_{job_id}.md",
    )


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/token-report
# ---------------------------------------------------------------------------

@router.get("/jobs/{job_id}/token-report")
async def download_token_report(job_id: str, request: Request) -> FileResponse:
    db: Database = request.app.state.db
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")

    report_path = os.path.join(settings.output_dir, job_id, "token_report.json")
    if not os.path.exists(report_path):
        raise HTTPException(status_code=404, detail="Token report not found.")

    return FileResponse(
        report_path,
        media_type="application/json",
        filename=f"token_report_{job_id}.json",
    )
