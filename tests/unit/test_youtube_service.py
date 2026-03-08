import os
import asyncio

from unittest.mock import MagicMock, patch

from youtubesynth.services.youtube_service import YouTubeService, TranscriptResult

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "mock_transcripts")


def _snippet(text: str, start: float = 0.0):
    """Return a mock snippet object matching v1.x FetchedTranscriptSnippet."""
    s = MagicMock()
    s.text = text
    s.start = start
    return s


def _make_api_mock(texts: list[str], is_generated: bool = False):
    """
    Return a mock for the YouTubeTranscriptApi *class*.
    In v1.x the class is instantiated: api = YouTubeTranscriptApi()
    so the instance is mock_class.return_value and list() is on the instance.
    """
    from youtube_transcript_api._errors import NoTranscriptFound

    transcript = MagicMock()
    transcript.language_code = "en"
    transcript.fetch.return_value = [_snippet(t) for t in texts]

    transcript_list = MagicMock()
    if is_generated:
        transcript_list.find_manually_created_transcript.side_effect = NoTranscriptFound(
            "vid", [], MagicMock()
        )
        transcript_list.find_generated_transcript.return_value = transcript
    else:
        transcript_list.find_manually_created_transcript.return_value = transcript

    mock_class = MagicMock()
    mock_class.return_value.list.return_value = transcript_list
    return mock_class


# ------------------------------------------------------------------
# Cache tests
# ------------------------------------------------------------------

async def test_cache_hit(tmp_path):
    cache_dir = str(tmp_path / "cache")
    os.makedirs(cache_dir)
    with open(os.path.join(cache_dir, "vid123.txt"), "w") as f:
        f.write("# transcript_type: manual\n# language: en\n[00:05] Hello world from cache.\n")

    service = YouTubeService(cache_dir=cache_dir)

    with patch("youtubesynth.services.youtube_service.YouTubeTranscriptApi") as mock_class:
        result = await service.get_transcript("vid123")

    mock_class.return_value.list.assert_not_called()
    assert result.transcript_type == "manual"
    assert "Hello world from cache." in result.text


async def test_cache_miss_calls_api(tmp_path):
    cache_dir = str(tmp_path / "cache")
    service = YouTubeService(cache_dir=cache_dir)

    with patch(
        "youtubesynth.services.youtube_service.YouTubeTranscriptApi",
        _make_api_mock(["Hello from API."]),
    ):
        result = await service.get_transcript("vid456")

    assert "Hello from API." in result.text
    assert "[00:00]" in result.text
    assert result.transcript_type == "manual"


async def test_cache_file_written_after_fetch(tmp_path):
    cache_dir = str(tmp_path / "cache")
    service = YouTubeService(cache_dir=cache_dir)

    with patch(
        "youtubesynth.services.youtube_service.YouTubeTranscriptApi",
        _make_api_mock(["Cached content."]),
    ):
        await service.get_transcript("vid789")

    cache_file = os.path.join(cache_dir, "vid789.txt")
    assert os.path.exists(cache_file)
    content = open(cache_file).read()
    assert "# transcript_type: manual" in content
    assert "# language: en" in content
    assert "Cached content." in content
    assert "[00:00]" in content


# ------------------------------------------------------------------
# Transcript type tests
# ------------------------------------------------------------------

async def test_manual_transcript_type(tmp_path):
    service = YouTubeService(cache_dir=str(tmp_path), no_cache=True)

    with patch(
        "youtubesynth.services.youtube_service.YouTubeTranscriptApi",
        _make_api_mock(["Manual captions here."], is_generated=False),
    ):
        result = await service.get_transcript("vidM01")

    assert result.transcript_type == "manual"
    assert result.language == "en"


async def test_auto_generated_transcript_type(tmp_path):
    service = YouTubeService(cache_dir=str(tmp_path), no_cache=True)

    with patch(
        "youtubesynth.services.youtube_service.YouTubeTranscriptApi",
        _make_api_mock(["Auto generated captions."], is_generated=True),
    ):
        result = await service.get_transcript("vidA01")

    assert result.transcript_type == "auto-generated"


# ------------------------------------------------------------------
# Unavailable transcript
# ------------------------------------------------------------------

async def test_no_transcript_returns_unavailable(tmp_path):
    from youtube_transcript_api._errors import TranscriptsDisabled

    service = YouTubeService(cache_dir=str(tmp_path), no_cache=True)

    mock_class = MagicMock()
    mock_class.return_value.list.side_effect = TranscriptsDisabled("vidX01")

    with patch("youtubesynth.services.youtube_service.YouTubeTranscriptApi", mock_class):
        result = await service.get_transcript("vidX01")

    assert result.transcript_type == "unavailable"
    assert result.text == ""
    assert result.video_id == "vidX01"


async def test_unavailable_not_written_to_cache(tmp_path):
    from youtube_transcript_api._errors import TranscriptsDisabled

    cache_dir = str(tmp_path / "cache")
    service = YouTubeService(cache_dir=cache_dir, no_cache=False)

    mock_class = MagicMock()
    mock_class.return_value.list.side_effect = TranscriptsDisabled("vidX02")

    with patch("youtubesynth.services.youtube_service.YouTubeTranscriptApi", mock_class):
        await service.get_transcript("vidX02")

    assert not os.path.exists(os.path.join(cache_dir, "vidX02.txt"))


# ------------------------------------------------------------------
# no_cache flag
# ------------------------------------------------------------------

async def test_no_cache_flag_bypasses_cache(tmp_path):
    cache_dir = str(tmp_path / "cache")
    os.makedirs(cache_dir)
    with open(os.path.join(cache_dir, "vidNC1.txt"), "w") as f:
        f.write("# transcript_type: manual\n# language: en\nStale cached text.\n")

    mock_class = _make_api_mock(["Fresh API text."])
    service = YouTubeService(cache_dir=cache_dir, no_cache=True)

    with patch("youtubesynth.services.youtube_service.YouTubeTranscriptApi", mock_class):
        result = await service.get_transcript("vidNC1")

    mock_class.return_value.list.assert_called_once()
    assert "Fresh API text." in result.text


# ------------------------------------------------------------------
# Batch fetch
# ------------------------------------------------------------------

async def test_batch_fetch(tmp_path):
    service = YouTubeService(cache_dir=str(tmp_path), no_cache=True)

    with patch(
        "youtubesynth.services.youtube_service.YouTubeTranscriptApi",
        _make_api_mock(["Batch video text."]),
    ):
        semaphore = asyncio.Semaphore(2)
        results = await service.get_transcript_batch(["vidB1", "vidB2", "vidB3"], semaphore)

    assert len(results) == 3
    assert all(isinstance(r, TranscriptResult) for r in results)


# ------------------------------------------------------------------
# Fixture file integration
# ------------------------------------------------------------------

async def test_short_fixture_is_below_threshold():
    path = os.path.join(FIXTURES, "short_transcript.txt")
    with open(path) as f:
        lines = [l for l in f if not l.startswith("#")]
    word_count = len(" ".join(lines).split())
    assert word_count < 5000, f"Expected < 5000 words, got {word_count}"


async def test_long_fixture_is_above_threshold():
    path = os.path.join(FIXTURES, "long_transcript.txt")
    with open(path) as f:
        lines = [l for l in f if not l.startswith("#")]
    word_count = len(" ".join(lines).split())
    # ~1.3 words per token — 8000 tokens ≈ 6000 words
    assert word_count > 6000, f"Expected > 6000 words, got {word_count}"
