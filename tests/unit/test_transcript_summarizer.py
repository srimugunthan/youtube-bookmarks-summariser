"""Tests for TranscriptSummarizer (Phase 6)."""

import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from youtubesynth.agents.transcript_summarizer import TranscriptSummarizer
from youtubesynth.extractors.url_validator import VideoMeta
from youtubesynth.services.gemini_client import GeminiResponse
from youtubesynth.services.youtube_service import TranscriptResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SHORT_TEXT = "[00:00] Hello world\n[00:05] This is a short transcript."
LONG_TEXT = ("[00:00] word " * 900).strip()  # ~900 tokens > 8000 is false, let's use threshold=10
# We'll override threshold=10 to make SHORT_TEXT short and LONG_TEXT long in tests.


def _make_video(video_id="abc1234567x", title="Test Video"):
    return VideoMeta(
        video_id=video_id,
        url=f"https://www.youtube.com/watch?v={video_id}",
        title=title,
    )


def _make_transcript(text=SHORT_TEXT, transcript_type="manual", video_id="abc1234567x"):
    return TranscriptResult(
        video_id=video_id,
        text=text,
        transcript_type=transcript_type,
        word_count=len(text.split()),
    )


def _make_summarizer(tmp_path, db=None, token_tracker=None, gemini_client=None, threshold=8000):
    if db is None:
        db = AsyncMock()
        db.get_job_videos = AsyncMock(return_value=[])

    token_tracker = token_tracker or AsyncMock()
    gemini_client = gemini_client or AsyncMock()

    return TranscriptSummarizer(
        db=db,
        token_tracker=token_tracker,
        gemini_client=gemini_client,
        flash_model="gemini-2.5-flash-lite",
        summaries_dir=str(tmp_path / "summaries"),
        chunk_token_threshold=threshold,
    )


def _mock_generate(text="# Summary\n\nGreat video."):
    async def _generate(model, prompt):
        return GeminiResponse(text=text, input_tokens=100, output_tokens=50)
    return _generate


# ---------------------------------------------------------------------------
# Test: unavailable transcript
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unavailable_transcript_skipped(tmp_path):
    db = AsyncMock()
    db.get_job_videos = AsyncMock(return_value=[])
    summarizer = _make_summarizer(tmp_path, db=db)

    video = _make_video()
    transcript = _make_transcript(text="", transcript_type="unavailable")

    result = await summarizer.summarize_video("job1", video, transcript)

    assert result is None
    db.update_video_status.assert_called_once_with(
        "job1", video.video_id, "unavailable", transcript_type="unavailable"
    )
    db.increment_done_videos.assert_called_once_with("job1")


# ---------------------------------------------------------------------------
# Test: short transcript — single Flash call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_short_transcript_direct(tmp_path):
    db = AsyncMock()
    db.get_job_videos = AsyncMock(return_value=[])
    gemini_client = AsyncMock()
    gemini_client.generate = AsyncMock(
        return_value=GeminiResponse(text="## Summary", input_tokens=80, output_tokens=30)
    )
    token_tracker = AsyncMock()

    summarizer = _make_summarizer(tmp_path, db=db, gemini_client=gemini_client,
                                  token_tracker=token_tracker)

    video = _make_video()
    transcript = _make_transcript(SHORT_TEXT)

    result = await summarizer.summarize_video("job1", video, transcript)

    assert result == "## Summary"
    # One Gemini call for the short path
    assert gemini_client.generate.call_count == 1
    # Token tracker recorded with agent="summarizer"
    token_tracker.record.assert_called_once()
    call_kwargs = token_tracker.record.call_args.kwargs
    assert call_kwargs["agent"] == "summarizer"
    assert call_kwargs["video_id"] == video.video_id


# ---------------------------------------------------------------------------
# Test: long transcript — chunking path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_long_transcript_chunked(tmp_path):
    # threshold=10 forces chunking on any realistic transcript
    db = AsyncMock()
    db.get_job_videos = AsyncMock(return_value=[])
    gemini_client = AsyncMock()
    gemini_client.generate = AsyncMock(
        return_value=GeminiResponse(text="chunk summary", input_tokens=50, output_tokens=20)
    )
    token_tracker = AsyncMock()

    summarizer = _make_summarizer(tmp_path, db=db, gemini_client=gemini_client,
                                  token_tracker=token_tracker, threshold=10)

    video = _make_video()
    # Make a transcript that's definitely > 10 tokens
    long_text = "[00:00] " + ("word " * 50)
    transcript = _make_transcript(long_text)

    result = await summarizer.summarize_video("job1", video, transcript)

    # Multiple Gemini calls: N chunk calls + 1 merge call
    assert gemini_client.generate.call_count >= 2

    # token_tracker called with chunk_summarizer for chunks and summarizer for merge
    agents_recorded = [c.kwargs["agent"] for c in token_tracker.record.call_args_list]
    assert "chunk_summarizer" in agents_recorded
    assert "summarizer" in agents_recorded


# ---------------------------------------------------------------------------
# Test: summary file written
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_summary_file_written(tmp_path):
    db = AsyncMock()
    db.get_job_videos = AsyncMock(return_value=[])
    gemini_client = AsyncMock()
    gemini_client.generate = AsyncMock(
        return_value=GeminiResponse(text="# My Summary", input_tokens=100, output_tokens=40)
    )

    summarizer = _make_summarizer(tmp_path, db=db, gemini_client=gemini_client)

    video = _make_video(video_id="vid0000001xx")
    transcript = _make_transcript(SHORT_TEXT, video_id="vid0000001xx")

    await summarizer.summarize_video("jobA", video, transcript)

    expected_path = tmp_path / "summaries" / "jobA" / "vid0000001xx.md"
    assert expected_path.exists()
    content = expected_path.read_text()
    assert "Test Video" in content
    assert "https://www.youtube.com/watch?v=vid0000001xx" in content
    assert "# My Summary" in content


# ---------------------------------------------------------------------------
# Test: token usage recorded correctly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_token_usage_recorded(tmp_path):
    db = AsyncMock()
    db.get_job_videos = AsyncMock(return_value=[])
    gemini_client = AsyncMock()
    gemini_client.generate = AsyncMock(
        return_value=GeminiResponse(text="summary", input_tokens=120, output_tokens=60)
    )
    token_tracker = AsyncMock()

    summarizer = _make_summarizer(tmp_path, db=db, gemini_client=gemini_client,
                                  token_tracker=token_tracker)

    video = _make_video()
    transcript = _make_transcript()

    await summarizer.summarize_video("job2", video, transcript)

    token_tracker.record.assert_called_once_with(
        agent="summarizer",
        model="gemini-2.5-flash-lite",
        input_tokens=120,
        output_tokens=60,
        video_id=video.video_id,
    )


# ---------------------------------------------------------------------------
# Test: resume skips already-done video
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_skips_done_video(tmp_path):
    # Pre-write a summary file
    job_id = "jobResume"
    video_id = "abc1234567x"
    summary_dir = tmp_path / "summaries" / job_id
    summary_dir.mkdir(parents=True)
    (summary_dir / f"{video_id}.md").write_text("cached summary")

    db = AsyncMock()
    db.get_job_videos = AsyncMock(return_value=[
        {"video_id": video_id, "status": "done"}
    ])
    gemini_client = AsyncMock()

    summarizer = _make_summarizer(tmp_path, db=db, gemini_client=gemini_client)

    video = _make_video(video_id=video_id)
    transcript = _make_transcript(video_id=video_id)

    result = await summarizer.summarize_video(job_id, video, transcript)

    assert result == "cached summary"
    # No Gemini call made
    gemini_client.generate.assert_not_called()


# ---------------------------------------------------------------------------
# Test: SSE events emitted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sse_events_emitted(tmp_path):
    db = AsyncMock()
    db.get_job_videos = AsyncMock(return_value=[])
    gemini_client = AsyncMock()
    gemini_client.generate = AsyncMock(
        return_value=GeminiResponse(text="summary", input_tokens=50, output_tokens=20)
    )

    emitted = []

    class _Emitter:
        async def emit(self, job_id, event, data):
            emitted.append((event, data))

    summarizer = TranscriptSummarizer(
        db=db,
        token_tracker=AsyncMock(),
        gemini_client=gemini_client,
        flash_model="gemini-2.5-flash-lite",
        summaries_dir=str(tmp_path / "summaries"),
        progress_emitter=_Emitter(),
    )

    video = _make_video()
    transcript = _make_transcript()

    await summarizer.summarize_video("job3", video, transcript)

    events = [e for e, _ in emitted]
    assert "video_started" in events
    assert "video_done" in events


# ---------------------------------------------------------------------------
# Test: Gemini failure updates DB to "failed" and returns None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gemini_failure_returns_none(tmp_path):
    from youtubesynth.exceptions import GeminiError

    db = AsyncMock()
    db.get_job_videos = AsyncMock(return_value=[])
    gemini_client = AsyncMock()
    gemini_client.generate = AsyncMock(side_effect=GeminiError("rate limit"))

    summarizer = _make_summarizer(tmp_path, db=db, gemini_client=gemini_client)

    video = _make_video()
    transcript = _make_transcript()

    result = await summarizer.summarize_video("job4", video, transcript)

    assert result is None
    db.update_video_status.assert_called_with(
        "job4", video.video_id, "failed", error="rate limit"
    )
    db.increment_done_videos.assert_called_with("job4")


# ---------------------------------------------------------------------------
# Test: batch processes all videos
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_batch_summarizes_all(tmp_path):
    db = AsyncMock()
    db.get_job_videos = AsyncMock(return_value=[])
    call_count = 0

    async def _generate(model, prompt):
        nonlocal call_count
        call_count += 1
        return GeminiResponse(text=f"summary_{call_count}", input_tokens=50, output_tokens=20)

    gemini_client = AsyncMock()
    gemini_client.generate = _generate

    summarizer = _make_summarizer(tmp_path, db=db, gemini_client=gemini_client)

    videos = [_make_video(f"vid000000{i}xx") for i in range(3)]
    transcripts = [_make_transcript(SHORT_TEXT, video_id=v.video_id) for v in videos]

    results = await summarizer.summarize_batch(
        "jobBatch", videos, transcripts, asyncio.Semaphore(2)
    )

    assert len(results) == 3
    assert all(r is not None for r in results)


# ---------------------------------------------------------------------------
# Test: batch handles mixed available / unavailable
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_batch_handles_mixed(tmp_path):
    db = AsyncMock()
    db.get_job_videos = AsyncMock(return_value=[])
    gemini_client = AsyncMock()
    gemini_client.generate = AsyncMock(
        return_value=GeminiResponse(text="ok", input_tokens=50, output_tokens=20)
    )

    summarizer = _make_summarizer(tmp_path, db=db, gemini_client=gemini_client)

    videos = [_make_video("vid0000001xx"), _make_video("vid0000002xx")]
    transcripts = [
        _make_transcript(SHORT_TEXT, video_id="vid0000001xx"),
        _make_transcript("", transcript_type="unavailable", video_id="vid0000002xx"),
    ]

    results = await summarizer.summarize_batch(
        "jobMix", videos, transcripts, asyncio.Semaphore(2)
    )

    assert results[0] == "ok"
    assert results[1] is None


# ---------------------------------------------------------------------------
# Test: DB status transitions (summarizing → done)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_db_status_transitions(tmp_path):
    db = AsyncMock()
    db.get_job_videos = AsyncMock(return_value=[])
    gemini_client = AsyncMock()
    gemini_client.generate = AsyncMock(
        return_value=GeminiResponse(text="summary", input_tokens=80, output_tokens=30)
    )

    summarizer = _make_summarizer(tmp_path, db=db, gemini_client=gemini_client)

    video = _make_video()
    transcript = _make_transcript()

    await summarizer.summarize_video("job5", video, transcript)

    calls = db.update_video_status.call_args_list
    statuses = [c.args[2] for c in calls]
    assert "summarizing" in statuses
    assert "done" in statuses
    db.increment_done_videos.assert_called_once_with("job5")
