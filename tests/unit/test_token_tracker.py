import pytest
from dataclasses import dataclass

from youtubesynth.services.db import Database
from youtubesynth.services.token_tracker import TokenTracker, compute_cost, estimate_cost, PRICING


@dataclass
class _T:
    """Minimal transcript stub satisfying the _Transcript protocol."""
    text: str
    transcript_type: str


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def tracker(db):
    await db.create_job("job-t1", "article", None, total_videos=3)
    return TokenTracker(job_id="job-t1", db=db)


# ------------------------------------------------------------------
# compute_cost
# ------------------------------------------------------------------

def test_compute_cost_flash():
    cost = compute_cost("gemini-2.5-flash-lite", input_tokens=1_000_000, output_tokens=1_000_000)
    expected = PRICING["gemini-2.5-flash-lite"]["input"] * 1_000_000 + \
               PRICING["gemini-2.5-flash-lite"]["output"] * 1_000_000
    assert abs(cost - expected) < 1e-9


def test_compute_cost_pro():
    cost = compute_cost("gemini-2.5-flash", input_tokens=1_000_000, output_tokens=1_000_000)
    expected = PRICING["gemini-2.5-flash"]["input"] * 1_000_000 + \
               PRICING["gemini-2.5-flash"]["output"] * 1_000_000
    assert abs(cost - expected) < 1e-9


def test_compute_cost_unknown_model_is_zero():
    cost = compute_cost("unknown-model", input_tokens=9999, output_tokens=9999)
    assert cost == 0.0


def test_compute_cost_flash_cheaper_than_pro():
    flash = compute_cost("gemini-2.5-flash-lite", 10000, 1000)
    pro = compute_cost("gemini-2.5-flash", 10000, 1000)
    assert flash < pro


# ------------------------------------------------------------------
# record — inserts to DB
# ------------------------------------------------------------------

async def test_record_inserts_to_db(tracker, db):
    cost = await tracker.record(
        agent="summarizer",
        model="gemini-2.5-flash-lite",
        input_tokens=4000,
        output_tokens=500,
        video_id="vidA",
    )

    assert cost > 0
    rows = await db.get_token_usage("job-t1")
    assert len(rows) == 1
    assert rows[0]["agent"] == "summarizer"
    assert rows[0]["video_id"] == "vidA"
    assert rows[0]["input_tokens"] == 4000


async def test_record_synthesis_has_null_video_id(tracker, db):
    await tracker.record(
        agent="synthesis",
        model="gemini-2.5-flash",
        input_tokens=12000,
        output_tokens=1500,
        video_id=None,
    )

    rows = await db.get_token_usage("job-t1")
    assert rows[0]["video_id"] is None


# ------------------------------------------------------------------
# get_report — aggregation
# ------------------------------------------------------------------

async def test_get_report_aggregates(tracker):
    await tracker.record("summarizer", "gemini-2.5-flash-lite", 3000, 400, video_id="vid1")
    await tracker.record("summarizer", "gemini-2.5-flash-lite", 2000, 300, video_id="vid2")
    await tracker.record("synthesis",  "gemini-2.5-flash",   8000, 1000, video_id=None)

    report = await tracker.get_report()

    assert report["job_id"] == "job-t1"
    assert report["total_input_tokens"] == 13000
    assert report["total_output_tokens"] == 1700
    assert report["total_cost_usd"] > 0

    assert "summarizer" in report["by_agent"]
    assert "synthesis" in report["by_agent"]
    assert report["by_agent"]["summarizer"]["input_tokens"] == 5000
    assert report["by_agent"]["synthesis"]["input_tokens"] == 8000

    assert len(report["by_video"]) == 2
    video_ids = {v["video_id"] for v in report["by_video"]}
    assert video_ids == {"vid1", "vid2"}


async def test_get_report_empty_job(db):
    await db.create_job("job-empty", "article", None, total_videos=0)
    tracker = TokenTracker(job_id="job-empty", db=db)
    report = await tracker.get_report()

    assert report["total_input_tokens"] == 0
    assert report["total_output_tokens"] == 0
    assert report["total_cost_usd"] == 0.0
    assert report["by_agent"] == {}
    assert report["by_video"] == []


# ------------------------------------------------------------------
# estimate_cost — pre-run projection
# ------------------------------------------------------------------

FLASH = "gemini-2.5-flash-lite"
PRO = "gemini-2.5-flash"
THRESHOLD = 8000


def test_estimate_cost_short_transcripts():
    # Two short transcripts well under the 8k-token threshold (~50 words each)
    transcripts = [
        _T(text="Hello world. " * 50, transcript_type="manual"),
        _T(text="Another video. " * 50, transcript_type="auto-generated"),
    ]
    est = estimate_cost(transcripts, FLASH, PRO, chunk_token_threshold=THRESHOLD)

    assert est.available_count == 2
    assert est.unavailable_count == 0
    assert est.summarizer_input_tokens > 0
    assert est.summarizer_output_tokens > 0
    # No chunking should occur
    assert est.chunk_summarizer_input_tokens == 0
    assert est.chunk_summarizer_output_tokens == 0
    # Synthesis should have something to work with
    assert est.synthesis_input_tokens > 0
    assert est.synthesis_output_tokens > 0
    assert est.total_cost_usd > 0
    assert "summarizer" in est.by_agent
    assert "chunk_summarizer" not in est.by_agent
    assert "synthesis" in est.by_agent


def test_estimate_cost_long_transcript_triggers_chunking():
    # ~7 tokens per phrase repetition; 1500 reps ≈ 10,500 tokens → well above 8k threshold
    long_text = "interesting machine learning concept explained in detail " * 1500
    transcripts = [_T(text=long_text, transcript_type="auto-generated")]

    est = estimate_cost(transcripts, FLASH, PRO, chunk_token_threshold=THRESHOLD)

    assert est.available_count == 1
    assert est.unavailable_count == 0
    # Chunk summarizer must have been triggered
    assert est.chunk_summarizer_input_tokens > 0
    assert est.chunk_summarizer_output_tokens > 0
    # Merge step populates summarizer too
    assert est.summarizer_input_tokens > 0
    assert "chunk_summarizer" in est.by_agent
    assert "summarizer" in est.by_agent
    assert est.total_cost_usd > 0


def test_estimate_cost_excludes_unavailable():
    transcripts = [
        _T(text="Good transcript. " * 50, transcript_type="manual"),
        _T(text="",                        transcript_type="unavailable"),
        _T(text="",                        transcript_type="unavailable"),
    ]
    est = estimate_cost(transcripts, FLASH, PRO, chunk_token_threshold=THRESHOLD)

    assert est.available_count == 1
    assert est.unavailable_count == 2
    # Only the one available transcript contributes to token counts
    assert est.summarizer_input_tokens > 0
    # Cost should be non-zero (from the one available video + synthesis)
    assert est.total_cost_usd > 0


def test_estimate_cost_all_unavailable_returns_zero_cost():
    transcripts = [
        _T(text="", transcript_type="unavailable"),
        _T(text="", transcript_type="unavailable"),
    ]
    est = estimate_cost(transcripts, FLASH, PRO, chunk_token_threshold=THRESHOLD)

    assert est.available_count == 0
    assert est.unavailable_count == 2
    assert est.total_input_tokens == 0
    assert est.total_output_tokens == 0
    assert est.total_cost_usd == 0.0
    assert est.by_agent == {}
