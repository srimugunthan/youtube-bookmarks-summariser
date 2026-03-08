"""Integration tests for the FastAPI layer with real in-memory DB and mocked services."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from youtubesynth.main import app
from youtubesynth.services.db import Database
from youtubesynth.services.gemini_client import GeminiClient, GeminiResponse
from youtubesynth.services.youtube_service import TranscriptResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_KNOWN_VIDEO_ID = "dQw4w9WgXcQ"
_TXT_CONTENT = f"https://www.youtube.com/watch?v={_KNOWN_VIDEO_ID}\n".encode()


def _make_transcript(
    video_id: str = _KNOWN_VIDEO_ID,
    text: str = "Hello from the API integration test.",
) -> TranscriptResult:
    return TranscriptResult(
        video_id=video_id,
        text=text,
        transcript_type="manual",
        language="en",
        word_count=len(text.split()),
    )


def _make_gemini_mock(response_text: str = "# Summary\nAPI test summary.") -> MagicMock:
    client = MagicMock(spec=GeminiClient)
    client.generate = AsyncMock(
        return_value=GeminiResponse(text=response_text, input_tokens=100, output_tokens=50)
    )
    return client


async def _poll_for_status(db: Database, job_id: str, target: str, retries: int = 100) -> bool:
    """Poll DB until job reaches target status. Returns True if reached."""
    for _ in range(retries):
        await asyncio.sleep(0.05)
        job = await db.get_job(job_id)
        if job and job["status"] == target:
            return True
    return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_confirm_flow_pipeline_runs_to_done(db, tmp_path):
    """Submit → pending_confirmation → POST /confirm → pipeline runs → DB done."""
    known_job_id = "apitst01"
    transcript = _make_transcript()
    gemini = _make_gemini_mock()

    app.state.db = db

    with (
        patch("youtubesynth.api.routes.uuid") as mock_uuid,
        patch("youtubesynth.pipeline.YouTubeService") as MockYT,
        patch("youtubesynth.api.routes.GeminiClient", return_value=gemini),
        patch("youtubesynth.api.routes.settings") as mock_rt_settings,
    ):
        mock_uuid.uuid4.return_value.hex = known_job_id + "0" * 24
        mock_rt_settings.output_dir = str(tmp_path)
        mock_rt_settings.max_videos_per_job = 50
        mock_rt_settings.default_concurrency = 2
        mock_rt_settings.gemini_api_key = ""

        MockYT.return_value.get_transcript_batch = AsyncMock(return_value=[transcript])

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Start submit as a task (will block until pipeline completes)
            submit_task = asyncio.create_task(
                client.post(
                    "/api/jobs",
                    files={"file": ("videos.txt", _TXT_CONTENT, "text/plain")},
                    data={"style": "article"},
                    headers={"X-Gemini-Api-Key": "fake-key"},
                )
            )

            # Wait for pipeline to reach pending_confirmation
            reached = await _poll_for_status(db, known_job_id, "pending_confirmation")
            assert reached, "Job never reached pending_confirmation"

            # Confirm via API
            confirm_resp = await client.post(f"/api/jobs/{known_job_id}/confirm")
            assert confirm_resp.status_code == 200
            assert confirm_resp.json() == {"job_id": known_job_id, "status": "running"}

            # Await the pipeline to finish (generous timeout for the 1s sleep in finally)
            submit_resp = await asyncio.wait_for(submit_task, timeout=15.0)
            assert submit_resp.status_code == 202
            assert submit_resp.json()["job_id"] == known_job_id

    # DB: job is done
    job = await db.get_job(known_job_id)
    assert job["status"] == "done"

    # Output files were written
    assert (tmp_path / known_job_id / "overall_summary.md").exists()
    assert (tmp_path / known_job_id / "token_report.json").exists()


async def test_cancel_flow_pipeline_aborts(db, tmp_path):
    """Submit → pending_confirmation → POST /cancel → pipeline returns cancelled."""
    known_job_id = "apitst02"
    transcript = _make_transcript()
    gemini = _make_gemini_mock()

    app.state.db = db

    with (
        patch("youtubesynth.api.routes.uuid") as mock_uuid,
        patch("youtubesynth.pipeline.YouTubeService") as MockYT,
        patch("youtubesynth.api.routes.GeminiClient", return_value=gemini),
        patch("youtubesynth.api.routes.settings") as mock_rt_settings,
    ):
        mock_uuid.uuid4.return_value.hex = known_job_id + "0" * 24
        mock_rt_settings.output_dir = str(tmp_path)
        mock_rt_settings.max_videos_per_job = 50
        mock_rt_settings.default_concurrency = 2
        mock_rt_settings.gemini_api_key = ""

        MockYT.return_value.get_transcript_batch = AsyncMock(return_value=[transcript])

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            submit_task = asyncio.create_task(
                client.post(
                    "/api/jobs",
                    files={"file": ("videos.txt", _TXT_CONTENT, "text/plain")},
                    data={"style": "article"},
                    headers={"X-Gemini-Api-Key": "fake-key"},
                )
            )

            # Wait for pending_confirmation
            reached = await _poll_for_status(db, known_job_id, "pending_confirmation")
            assert reached, "Job never reached pending_confirmation"

            # Cancel via API
            cancel_resp = await client.post(f"/api/jobs/{known_job_id}/cancel")
            assert cancel_resp.status_code == 200
            assert cancel_resp.json() == {"job_id": known_job_id, "status": "cancelled"}

            # Pipeline should exit quickly after cancel
            submit_resp = await asyncio.wait_for(submit_task, timeout=15.0)
            assert submit_resp.status_code == 202

    # DB: job is cancelled
    job = await db.get_job(known_job_id)
    assert job["status"] == "cancelled"

    # No output files written
    assert not (tmp_path / known_job_id / "overall_summary.md").exists()

    # No Gemini calls were made (cancelled before Phase B)
    gemini.generate.assert_not_called()


async def test_confirm_on_wrong_status_returns_409(db):
    """POST /confirm on a job that is not pending_confirmation → 409."""
    # Create a job in "running" status directly
    await db.create_job(job_id="apitst03", style="article", title=None, total_videos=1)
    await db.update_job_status("apitst03", "running")

    app.state.db = db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/jobs/apitst03/confirm")

    assert resp.status_code == 409
    assert "pending_confirmation" in resp.json()["detail"]


async def test_get_job_status_reflects_real_db(db):
    """GET /api/jobs/{id} reads from real in-memory DB correctly."""
    await db.create_job(job_id="apitst04", style="bullets", title="My Job", total_videos=3)
    await db.update_job_status("apitst04", "fetching")

    app.state.db = db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/jobs/apitst04")

    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == "apitst04"
    assert body["status"] == "fetching"
    assert body["style"] == "bullets"
    assert body["title"] == "My Job"
    assert body["total_videos"] == 3


async def test_result_endpoint_after_pipeline_done(db, tmp_path):
    """GET /api/jobs/{id}/result returns output when job is done and files exist."""
    await db.create_job(job_id="apitst05", style="article", title=None, total_videos=1)
    await db.update_job_status("apitst05", "done")

    # Write the output files as the pipeline would
    out_dir = tmp_path / "apitst05"
    out_dir.mkdir(parents=True)
    (out_dir / "overall_summary.md").write_text("# Final Summary\nGreat content.")
    (out_dir / "token_report.json").write_text('{"total_cost_usd": 0.05, "by_agent": {}}')

    app.state.db = db

    with patch("youtubesynth.api.routes.settings") as mock_settings:
        mock_settings.output_dir = str(tmp_path)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/jobs/apitst05/result")

    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == "apitst05"
    assert body["status"] == "done"
    assert "Final Summary" in body["output"]
    assert body["token_report"]["total_cost_usd"] == 0.05


async def test_get_job_not_found_in_real_db(db):
    """GET /api/jobs/{id} with a non-existent job returns 404 from real DB."""
    app.state.db = db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/jobs/doesnotexist")

    assert resp.status_code == 404
