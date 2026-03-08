"""Integration tests for run_pipeline() with mocked external services."""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from youtubesynth.extractors.url_validator import VideoMeta
from youtubesynth.pipeline import run_pipeline
from youtubesynth.services.db import Database
from youtubesynth.services.gemini_client import GeminiClient, GeminiResponse
from youtubesynth.services.token_tracker import CostEstimate
from youtubesynth.services.youtube_service import TranscriptResult


# ---------------------------------------------------------------------------
# Confirmation stubs
# ---------------------------------------------------------------------------


class AutoConfirmEmitter:
    async def confirm(self, job_id: str, estimate: CostEstimate) -> bool:
        return True


class AutoCancelEmitter:
    async def confirm(self, job_id: str, estimate: CostEstimate) -> bool:
        return False


class CapturingConfirmEmitter:
    def __init__(self):
        self.estimate: CostEstimate | None = None

    async def confirm(self, job_id: str, estimate: CostEstimate) -> bool:
        self.estimate = estimate
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _video(video_id: str, title: str | None = None) -> VideoMeta:
    return VideoMeta(
        video_id=video_id,
        url=f"https://www.youtube.com/watch?v={video_id}",
        title=title or video_id,
    )


def _transcript(
    video_id: str,
    text: str = "Hello world.",
    transcript_type: str = "manual",
) -> TranscriptResult:
    return TranscriptResult(
        video_id=video_id,
        text=text,
        transcript_type=transcript_type,
        language="en",
        word_count=len(text.split()),
    )


def _mock_gemini(response_text: str = "# Summary\nThis is a summary.") -> MagicMock:
    """Return a mock GeminiClient that always returns successfully."""
    client = MagicMock(spec=GeminiClient)
    client.generate = AsyncMock(
        return_value=GeminiResponse(text=response_text, input_tokens=100, output_tokens=50)
    )
    return client


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


async def test_happy_path_two_videos(db, tmp_path):
    """Full pipeline: 2 available videos → all output files written, DB done."""
    videos = [_video("videoID0001", "Video One"), _video("videoID0002", "Video Two")]
    transcripts = [
        _transcript("videoID0001", "Content for video one."),
        _transcript("videoID0002", "Content for video two."),
    ]
    gemini = _mock_gemini("# Synthesis\nOverall great content.")

    with patch("youtubesynth.pipeline.YouTubeService") as MockYT:
        MockYT.return_value.get_transcript_batch = AsyncMock(return_value=transcripts)

        result = await run_pipeline(
            job_id="integ001",
            videos=videos,
            style="article",
            title="Test Run",
            output_dir=str(tmp_path),
            concurrency=2,
            no_cache=True,
            db=db,
            gemini_client=gemini,
            confirmation_callback=AutoConfirmEmitter(),
        )

    assert not result.cancelled
    assert result.output_path == str(tmp_path / "integ001" / "overall_summary.md")
    assert result.report_path == str(tmp_path / "integ001" / "token_report.json")

    # All three output files exist
    assert os.path.exists(result.output_path)
    assert os.path.exists(result.report_path)
    assert (tmp_path / "integ001" / "transcripts.md").exists()

    # overall_summary.md has non-empty content
    assert (tmp_path / "integ001" / "overall_summary.md").read_text().strip()

    # token_report.json has expected structure
    report = json.loads((tmp_path / "integ001" / "token_report.json").read_text())
    assert report["total_cost_usd"] > 0
    assert "by_agent" in report
    assert "summarizer" in report["by_agent"]
    assert "synthesis" in report["by_agent"]

    # DB: job done, done_videos == 2
    job = await db.get_job("integ001")
    assert job["status"] == "done"
    assert job["done_videos"] == 2

    # DB: all video statuses are done
    vids = await db.get_job_videos("integ001")
    assert all(v["status"] == "done" for v in vids)


async def test_cancellation_no_output_no_gemini_calls(db, tmp_path):
    """Cancelling at confirmation → no output files, zero Gemini calls, DB cancelled."""
    videos = [_video("videoID0003")]
    transcripts = [_transcript("videoID0003", "Some content.")]
    gemini = _mock_gemini()

    with patch("youtubesynth.pipeline.YouTubeService") as MockYT:
        MockYT.return_value.get_transcript_batch = AsyncMock(return_value=transcripts)

        result = await run_pipeline(
            job_id="integ002",
            videos=videos,
            style="article",
            title=None,
            output_dir=str(tmp_path),
            concurrency=1,
            no_cache=True,
            db=db,
            gemini_client=gemini,
            confirmation_callback=AutoCancelEmitter(),
        )

    assert result.cancelled
    assert result.output_path is None
    assert result.cost_usd == 0.0

    # No Gemini calls made at all
    gemini.generate.assert_not_called()

    # No output directory or files written
    assert not (tmp_path / "integ002" / "overall_summary.md").exists()

    # DB: job is cancelled
    job = await db.get_job("integ002")
    assert job["status"] == "cancelled"


async def test_one_unavailable_transcript_skipped(db, tmp_path):
    """Unavailable video is skipped; the other succeeds; job finishes as done."""
    videos = [_video("videoID0004"), _video("videoID0005")]
    transcripts = [
        _transcript("videoID0004", "", transcript_type="unavailable"),
        _transcript("videoID0005", "Good content here."),
    ]
    gemini = _mock_gemini()

    with patch("youtubesynth.pipeline.YouTubeService") as MockYT:
        MockYT.return_value.get_transcript_batch = AsyncMock(return_value=transcripts)

        result = await run_pipeline(
            job_id="integ003",
            videos=videos,
            style="bullets",
            title=None,
            output_dir=str(tmp_path),
            concurrency=2,
            no_cache=True,
            db=db,
            gemini_client=gemini,
            confirmation_callback=AutoConfirmEmitter(),
        )

    assert not result.cancelled

    job = await db.get_job("integ003")
    assert job["status"] == "done"
    assert job["done_videos"] == 2

    vids = {v["video_id"]: v for v in await db.get_job_videos("integ003")}
    assert vids["videoID0004"]["status"] == "unavailable"
    assert vids["videoID0005"]["status"] == "done"


async def test_long_transcript_triggers_chunk_summarizer(db, tmp_path):
    """Very low chunk_token_threshold forces chunking → chunk_summarizer in report."""
    fixture = os.path.join(
        os.path.dirname(__file__), "..", "fixtures", "mock_transcripts", "long_transcript.txt"
    )
    with open(fixture, encoding="utf-8") as f:
        raw = f.read()

    # Strip the cache header lines (lines starting with #)
    text = "\n".join(line for line in raw.splitlines() if not line.startswith("#")).strip()

    videos = [_video("videoID0006", "Long Video")]
    transcripts = [
        TranscriptResult("videoID0006", text, "auto-generated", "en", len(text.split()))
    ]
    gemini = _mock_gemini()

    with patch("youtubesynth.pipeline.YouTubeService") as MockYT:
        MockYT.return_value.get_transcript_batch = AsyncMock(return_value=transcripts)

        result = await run_pipeline(
            job_id="integ004",
            videos=videos,
            style="article",
            title=None,
            output_dir=str(tmp_path),
            concurrency=1,
            no_cache=True,
            db=db,
            gemini_client=gemini,
            chunk_token_threshold=50,  # very low to force chunking
            confirmation_callback=AutoConfirmEmitter(),
        )

    assert not result.cancelled
    report = json.loads((tmp_path / "integ004" / "token_report.json").read_text())
    assert "chunk_summarizer" in report["by_agent"]


async def test_cost_estimate_reflects_transcript_availability(db, tmp_path):
    """CostEstimate passed to emitter has correct available/unavailable counts."""
    videos = [_video("videoID0007"), _video("videoID0008")]
    transcripts = [
        _transcript("videoID0007", "Content A."),
        _transcript("videoID0008", "", transcript_type="unavailable"),
    ]
    gemini = _mock_gemini()
    emitter = CapturingConfirmEmitter()

    with patch("youtubesynth.pipeline.YouTubeService") as MockYT:
        MockYT.return_value.get_transcript_batch = AsyncMock(return_value=transcripts)

        await run_pipeline(
            job_id="integ005",
            videos=videos,
            style="article",
            title=None,
            output_dir=str(tmp_path),
            concurrency=2,
            no_cache=True,
            db=db,
            gemini_client=gemini,
            confirmation_callback=emitter,
        )

    assert emitter.estimate is not None
    assert emitter.estimate.available_count == 1
    assert emitter.estimate.unavailable_count == 1
    assert emitter.estimate.total_cost_usd > 0


async def test_summaries_dir_has_per_video_md_files(db, tmp_path):
    """Each successfully summarized video produces a .md file in summaries_dir."""
    videos = [_video("videoID0009"), _video("videoID0010")]
    transcripts = [
        _transcript("videoID0009", "Content nine."),
        _transcript("videoID0010", "Content ten."),
    ]
    gemini = _mock_gemini()

    with patch("youtubesynth.pipeline.YouTubeService") as MockYT:
        MockYT.return_value.get_transcript_batch = AsyncMock(return_value=transcripts)

        await run_pipeline(
            job_id="integ006",
            videos=videos,
            style="article",
            title=None,
            output_dir=str(tmp_path),
            concurrency=2,
            no_cache=True,
            db=db,
            gemini_client=gemini,
            confirmation_callback=AutoConfirmEmitter(),
        )

    # summaries_dir = output/{job_id}/summaries/{job_id}/*.md
    summaries_dir = tmp_path / "integ006" / "summaries" / "integ006"
    assert summaries_dir.exists()
    md_files = list(summaries_dir.glob("*.md"))
    assert len(md_files) == 2


async def test_mock_summary_fixture_is_valid_markdown(tmp_path):
    """Sanity check: the mock_summaries fixture file is valid markdown."""
    fixture = os.path.join(
        os.path.dirname(__file__), "..", "fixtures", "mock_summaries", "videoID0011.md"
    )
    with open(fixture, encoding="utf-8") as f:
        content = f.read()

    assert content.startswith("# ")
    assert "**URL:**" in content
    assert len(content.strip()) > 0
