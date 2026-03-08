"""Unit tests for Phase 9 — FastAPI + SSE (Phase 9)."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from youtubesynth.main import app
from youtubesynth.pipeline import PipelineResult
from youtubesynth.services.token_tracker import CostEstimate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(job=None, jobs_list=None):
    db = AsyncMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    db.get_job = AsyncMock(return_value=job)
    db.create_job = AsyncMock()
    db.update_job_status = AsyncMock()
    db.upsert_video_progress = AsyncMock()
    db.get_job_videos = AsyncMock(return_value=[])
    return db


def _make_job(job_id="abc12345", status="done"):
    return {
        "job_id": job_id,
        "status": status,
        "style": "article",
        "title": None,
        "total_videos": 2,
        "done_videos": 2,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:01:00Z",
    }


async def _make_client(db=None):
    """Return an AsyncClient with a pre-connected mock DB on app.state."""
    if db is None:
        db = _make_db()
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    app.state.db = db
    return client


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health():
    async with await _make_client() as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /api/jobs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_submit_job_with_file():
    db = _make_db()
    txt_content = b"https://www.youtube.com/watch?v=dQw4w9WgXcQ\n"

    with patch("youtubesynth.api.routes.run_pipeline", new_callable=AsyncMock) as mock_pipeline, \
         patch("youtubesynth.config.settings.gemini_api_key", "fake-key"):
        mock_pipeline.return_value = PipelineResult(
            job_id="test0001", output_path="output/test0001/overall_summary.md",
            report_path="output/test0001/token_report.json", cost_usd=0.01, cancelled=False,
        )
        async with await _make_client(db) as client:
            resp = await client.post(
                "/api/jobs",
                files={"file": ("videos.txt", txt_content, "text/plain")},
                data={"style": "article"},
                headers={"X-Gemini-Api-Key": "fake-key"},
            )

    assert resp.status_code == 202
    body = resp.json()
    assert "job_id" in body
    assert body["status"] == "fetching"
    assert body["video_count"] == 1


@pytest.mark.asyncio
async def test_submit_job_with_playlist_url():
    db = _make_db()

    with patch("youtubesynth.api.routes.extract_urls") as mock_extract, \
         patch("youtubesynth.api.routes.run_pipeline", new_callable=AsyncMock):
        mock_extract.return_value = [MagicMock(video_id="vid001")]
        async with await _make_client(db) as client:
            resp = await client.post(
                "/api/jobs",
                data={"playlist_url": "https://www.youtube.com/playlist?list=PL123"},
                headers={"X-Gemini-Api-Key": "fake-key"},
            )

    assert resp.status_code == 202
    assert resp.json()["video_count"] == 1


@pytest.mark.asyncio
async def test_submit_job_both_inputs_422():
    async with await _make_client() as client:
        resp = await client.post(
            "/api/jobs",
            files={"file": ("f.txt", b"content", "text/plain")},
            data={"playlist_url": "https://www.youtube.com/playlist?list=PL123"},
            headers={"X-Gemini-Api-Key": "fake-key"},
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_submit_job_no_input_422():
    async with await _make_client() as client:
        resp = await client.post(
            "/api/jobs",
            data={},
            headers={"X-Gemini-Api-Key": "fake-key"},
        )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_job_status():
    job = _make_job(job_id="abc12345", status="running")
    db = _make_db(job=job)
    async with await _make_client(db) as client:
        resp = await client.get("/api/jobs/abc12345")
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == "abc12345"
    assert body["status"] == "running"
    assert body["total_videos"] == 2


@pytest.mark.asyncio
async def test_get_job_not_found_404():
    db = _make_db(job=None)
    async with await _make_client(db) as client:
        resp = await client.get("/api/jobs/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/jobs/{job_id}/confirm
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_confirm_returns_running():
    job = _make_job(job_id="job0001", status="pending_confirmation")
    db = _make_db(job=job)

    from youtubesynth.api.sse import sse_manager
    sse_manager.register("job0001")

    async with await _make_client(db) as client:
        resp = await client.post("/api/jobs/job0001/confirm")

    assert resp.status_code == 200
    assert resp.json() == {"job_id": "job0001", "status": "running"}
    sse_manager.unregister("job0001")


@pytest.mark.asyncio
async def test_confirm_on_wrong_status_409():
    job = _make_job(job_id="job0002", status="running")
    db = _make_db(job=job)
    async with await _make_client(db) as client:
        resp = await client.post("/api/jobs/job0002/confirm")
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# POST /api/jobs/{job_id}/cancel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_returns_cancelled():
    job = _make_job(job_id="job0003", status="pending_confirmation")
    db = _make_db(job=job)

    from youtubesynth.api.sse import sse_manager
    sse_manager.register("job0003")

    async with await _make_client(db) as client:
        resp = await client.post("/api/jobs/job0003/cancel")

    assert resp.status_code == 200
    assert resp.json() == {"job_id": "job0003", "status": "cancelled"}
    sse_manager.unregister("job0003")


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_result_not_done_404():
    job = _make_job(job_id="job0004", status="running")
    db = _make_db(job=job)
    async with await _make_client(db) as client:
        resp = await client.get("/api/jobs/job0004/result")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_result_returns_content(tmp_path):
    job = _make_job(job_id="job0005", status="done")
    db = _make_db(job=job)

    # Write fake output files
    out_dir = tmp_path / "job0005"
    out_dir.mkdir(parents=True)
    (out_dir / "overall_summary.md").write_text("# Summary")
    (out_dir / "token_report.json").write_text('{"total_cost_usd": 0.01}')

    with patch("youtubesynth.api.routes.settings") as mock_settings:
        mock_settings.output_dir = str(tmp_path)
        async with await _make_client(db) as client:
            resp = await client.get("/api/jobs/job0005/result")

    assert resp.status_code == 200
    body = resp.json()
    assert body["output"] == "# Summary"
    assert body["token_report"]["total_cost_usd"] == 0.01


# ---------------------------------------------------------------------------
# SSE — confirmation_required event emitted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sse_emits_confirmation_required():
    from youtubesynth.api.sse import SSEManager, APIConfirmationEmitter
    from youtubesynth.services.token_tracker import CostEstimate

    manager = SSEManager()
    manager.register("jobSSE1")

    db = AsyncMock()
    db.update_job_status = AsyncMock()

    emitter = APIConfirmationEmitter(db=db, manager=manager)

    estimate = CostEstimate(
        flash_model="gemini-2.5-flash-lite",
        pro_model="gemini-2.5-flash",
        available_count=2,
        unavailable_count=0,
        summarizer_input_tokens=1000,
        summarizer_output_tokens=250,
        chunk_summarizer_input_tokens=0,
        chunk_summarizer_output_tokens=0,
        synthesis_input_tokens=250,
        synthesis_output_tokens=3000,
        total_input_tokens=1250,
        total_output_tokens=3250,
        total_cost_usd=0.01,
        by_agent={},
    )

    # Run confirm() concurrently — it blocks waiting for set_confirmed
    async def _confirm():
        return await emitter.confirm("jobSSE1", estimate)

    task = asyncio.create_task(_confirm())
    await asyncio.sleep(0)  # let confirm() emit the event and block

    # Drain the queue to verify event was emitted
    q = manager._queues["jobSSE1"]
    event, data = await asyncio.wait_for(q.get(), timeout=1.0)
    assert event == "confirmation_required"
    assert data["job_id"] == "jobSSE1"
    assert "estimate" in data
    assert data["estimate"]["available_count"] == 2

    # Unblock confirm() by setting confirmed
    manager.set_confirmed("jobSSE1")
    result = await asyncio.wait_for(task, timeout=1.0)
    assert result is True
