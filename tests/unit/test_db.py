import pytest

from youtubesynth.services.db import Database


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


# ------------------------------------------------------------------
# jobs table
# ------------------------------------------------------------------

async def test_create_job(db):
    await db.create_job("job-1", "article", "My Title", total_videos=5)
    row = await db.get_job("job-1")

    assert row is not None
    assert row["job_id"] == "job-1"
    assert row["status"] == "pending"
    assert row["style"] == "article"
    assert row["title"] == "My Title"
    assert row["total_videos"] == 5
    assert row["done_videos"] == 0
    assert row["created_at"].endswith("Z")


async def test_get_job_not_found(db):
    row = await db.get_job("nonexistent")
    assert row is None


async def test_update_job_status(db):
    await db.create_job("job-2", "tutorial", None, total_videos=3)
    await db.update_job_status("job-2", "running")

    row = await db.get_job("job-2")
    assert row["status"] == "running"


async def test_increment_done_videos(db):
    await db.create_job("job-3", "guide", None, total_videos=4)
    await db.increment_done_videos("job-3")
    await db.increment_done_videos("job-3")

    row = await db.get_job("job-3")
    assert row["done_videos"] == 2


# ------------------------------------------------------------------
# video_progress table
# ------------------------------------------------------------------

async def test_upsert_video_progress(db):
    await db.create_job("job-4", "article", None, total_videos=1)
    await db.upsert_video_progress(
        "job-4", "vid-abc", "Cool Video", "https://youtu.be/vid-abc", "pending"
    )

    videos = await db.get_job_videos("job-4")
    assert len(videos) == 1
    assert videos[0]["video_id"] == "vid-abc"
    assert videos[0]["status"] == "pending"
    assert videos[0]["title"] == "Cool Video"


async def test_upsert_video_progress_updates_on_conflict(db):
    await db.create_job("job-5", "article", None, total_videos=1)
    await db.upsert_video_progress("job-5", "vid-xyz", "Title", "https://youtu.be/vid-xyz", "pending")
    await db.upsert_video_progress("job-5", "vid-xyz", "Title", "https://youtu.be/vid-xyz", "summarizing")

    videos = await db.get_job_videos("job-5")
    assert len(videos) == 1
    assert videos[0]["status"] == "summarizing"


async def test_update_video_status(db):
    await db.create_job("job-6", "article", None, total_videos=1)
    await db.upsert_video_progress("job-6", "vid-001", "Vid", "https://youtu.be/vid-001", "summarizing")
    await db.update_video_status("job-6", "vid-001", "done", transcript_type="manual")

    videos = await db.get_job_videos("job-6")
    assert videos[0]["status"] == "done"
    assert videos[0]["transcript_type"] == "manual"
    assert videos[0]["error"] is None


async def test_update_video_status_failed(db):
    await db.create_job("job-7", "article", None, total_videos=1)
    await db.upsert_video_progress("job-7", "vid-002", "Vid", "https://youtu.be/vid-002", "summarizing")
    await db.update_video_status("job-7", "vid-002", "failed", error="No transcript available")

    videos = await db.get_job_videos("job-7")
    assert videos[0]["status"] == "failed"
    assert videos[0]["error"] == "No transcript available"


# ------------------------------------------------------------------
# token_usage table
# ------------------------------------------------------------------

async def test_insert_and_get_token_usage(db):
    await db.create_job("job-8", "article", None, total_videos=2)

    await db.insert_token_usage(
        job_id="job-8",
        video_id="vid-aaa",
        agent="summarizer",
        model="gemini-1.5-flash",
        input_tokens=4000,
        output_tokens=500,
        cost_usd=0.00045,
    )
    await db.insert_token_usage(
        job_id="job-8",
        video_id=None,
        agent="synthesis",
        model="gemini-1.5-pro",
        input_tokens=8000,
        output_tokens=1200,
        cost_usd=0.0404,
    )

    rows = await db.get_token_usage("job-8")
    assert len(rows) == 2

    summarizer_row = rows[0]
    assert summarizer_row["agent"] == "summarizer"
    assert summarizer_row["video_id"] == "vid-aaa"
    assert summarizer_row["input_tokens"] == 4000
    assert summarizer_row["output_tokens"] == 500
    assert summarizer_row["created_at"].endswith("Z")

    synthesis_row = rows[1]
    assert synthesis_row["agent"] == "synthesis"
    assert synthesis_row["video_id"] is None
    assert synthesis_row["model"] == "gemini-1.5-pro"
