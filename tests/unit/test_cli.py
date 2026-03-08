"""Unit tests for youtubesynth/cli.py — Phase 8."""

import asyncio
from unittest import mock

import pytest

from youtubesynth.extractors.url_validator import VideoMeta
from youtubesynth.pipeline import PipelineResult
from youtubesynth.services.token_tracker import CostEstimate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_estimate(**overrides) -> CostEstimate:
    defaults = dict(
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
        total_cost_usd=0.001,
        by_agent={
            "summarizer": {"input_tokens": 1000, "output_tokens": 250, "cost_usd": 0.0002},
            "synthesis":  {"input_tokens": 250,  "output_tokens": 3000, "cost_usd": 0.0008},
        },
    )
    defaults.update(overrides)
    return CostEstimate(**defaults)


def _make_video(video_id: str = "abc123", title: str = "Test Video") -> VideoMeta:
    return VideoMeta(
        video_id=video_id,
        url=f"https://www.youtube.com/watch?v={video_id}",
        title=title,
    )


# ---------------------------------------------------------------------------
# _build_parser — argument parsing
# ---------------------------------------------------------------------------

class TestArgParsing:
    def test_input_flag_parsed(self):
        from youtubesynth.cli import _build_parser
        args = _build_parser().parse_args(["--input", "videos.txt"])
        assert args.input == "videos.txt"
        assert args.playlist is None

    def test_playlist_flag_parsed(self):
        from youtubesynth.cli import _build_parser
        args = _build_parser().parse_args(["--playlist", "https://youtube.com/playlist?list=PL123"])
        assert args.playlist == "https://youtube.com/playlist?list=PL123"
        assert args.input is None

    def test_mutual_exclusion_error(self):
        """--input and --playlist cannot both be given."""
        from youtubesynth.cli import _build_parser
        with pytest.raises(SystemExit) as exc_info:
            _build_parser().parse_args([
                "--input", "f.txt", "--playlist", "https://youtube.com/playlist?list=PL1"
            ])
        assert exc_info.value.code == 2

    def test_one_of_input_playlist_required(self):
        """Neither --input nor --playlist given → exit 2."""
        from youtubesynth.cli import _build_parser
        with pytest.raises(SystemExit) as exc_info:
            _build_parser().parse_args([])
        assert exc_info.value.code == 2

    def test_defaults(self):
        from youtubesynth.cli import _build_parser
        args = _build_parser().parse_args(["--input", "f.txt"])
        assert args.style == "article"
        assert args.title is None
        assert args.output_dir is None
        assert args.max_videos is None
        assert args.concurrency is None
        assert args.no_cache is False
        assert args.verbose is False
        assert args.yes is False

    def test_all_flags(self):
        from youtubesynth.cli import _build_parser
        args = _build_parser().parse_args([
            "--input", "videos.xml",
            "--style", "tutorial",
            "--title", "My Guide",
            "--output-dir", "./out",
            "--max-videos", "10",
            "--concurrency", "5",
            "--no-cache",
            "--verbose",
            "--yes",
        ])
        assert args.style == "tutorial"
        assert args.title == "My Guide"
        assert args.output_dir == "./out"
        assert args.max_videos == 10
        assert args.concurrency == 5
        assert args.no_cache is True
        assert args.verbose is True
        assert args.yes is True

    def test_short_flags(self):
        from youtubesynth.cli import _build_parser
        args = _build_parser().parse_args([
            "-i", "f.txt", "-s", "guide", "-t", "G", "-o", "/tmp", "-v", "-y"
        ])
        assert args.input == "f.txt"
        assert args.style == "guide"
        assert args.title == "G"
        assert args.output_dir == "/tmp"
        assert args.verbose is True
        assert args.yes is True


# ---------------------------------------------------------------------------
# main() — API key guard
# ---------------------------------------------------------------------------

class TestMissingApiKey:
    def test_missing_api_key_exits_1(self, capsys):
        from youtubesynth.cli import main
        with (
            mock.patch("sys.argv", ["youtubesynth", "--input", "file.txt"]),
            mock.patch("youtubesynth.cli.settings") as mock_settings,
        ):
            mock_settings.gemini_api_key = ""
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1
        assert "GEMINI_API_KEY" in capsys.readouterr().err

    def test_api_key_present_passes_guard(self, capsys):
        """With a valid API key, execution continues past the guard."""
        from youtubesynth.cli import main
        with (
            mock.patch("sys.argv", ["youtubesynth", "--input", "file.txt"]),
            mock.patch("youtubesynth.cli.settings") as mock_settings,
            mock.patch("youtubesynth.cli.extract_urls", return_value=[]),
        ):
            mock_settings.gemini_api_key = "test-key"
            mock_settings.output_dir = "output"
            mock_settings.max_videos_per_job = 50
            mock_settings.default_concurrency = 3
            # Should exit 0 (no videos found), NOT exit 1
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# CLIConfirmationEmitter
# ---------------------------------------------------------------------------

class TestCLIConfirmationEmitter:
    @pytest.mark.asyncio
    async def test_yes_flag_skips_prompt(self, capsys):
        """--yes flag auto-confirms without touching stdin."""
        from youtubesynth.cli import CLIConfirmationEmitter
        emitter = CLIConfirmationEmitter(yes=True)
        result = await emitter.confirm("job1", _make_estimate())
        assert result is True

    @pytest.mark.asyncio
    async def test_y_answer_confirms(self, monkeypatch, capsys):
        from youtubesynth.cli import CLIConfirmationEmitter
        monkeypatch.setattr("builtins.input", lambda _: "y")
        emitter = CLIConfirmationEmitter(yes=False)
        result = await emitter.confirm("job1", _make_estimate())
        assert result is True

    @pytest.mark.asyncio
    async def test_n_answer_cancels(self, monkeypatch):
        from youtubesynth.cli import CLIConfirmationEmitter
        monkeypatch.setattr("builtins.input", lambda _: "N")
        emitter = CLIConfirmationEmitter(yes=False)
        result = await emitter.confirm("job1", _make_estimate())
        assert result is False

    @pytest.mark.asyncio
    async def test_empty_answer_cancels(self, monkeypatch):
        from youtubesynth.cli import CLIConfirmationEmitter
        monkeypatch.setattr("builtins.input", lambda _: "")
        emitter = CLIConfirmationEmitter(yes=False)
        result = await emitter.confirm("job1", _make_estimate())
        assert result is False

    @pytest.mark.asyncio
    async def test_eof_cancels(self, monkeypatch):
        from youtubesynth.cli import CLIConfirmationEmitter
        monkeypatch.setattr("builtins.input", mock.Mock(side_effect=EOFError))
        emitter = CLIConfirmationEmitter(yes=False)
        result = await emitter.confirm("job1", _make_estimate())
        assert result is False

    @pytest.mark.asyncio
    async def test_cost_table_printed(self, capsys):
        """confirm() prints the cost breakdown to stdout."""
        from youtubesynth.cli import CLIConfirmationEmitter
        estimate = _make_estimate(
            available_count=3,
            unavailable_count=1,
            total_cost_usd=0.042,
        )
        emitter = CLIConfirmationEmitter(yes=True)
        await emitter.confirm("job1", estimate)
        out = capsys.readouterr().out
        assert "3 fetched, 1 unavailable" in out
        assert "Estimated API cost" in out
        assert "0.042" in out

    @pytest.mark.asyncio
    async def test_flash_and_pro_model_names_shown(self, capsys):
        from youtubesynth.cli import CLIConfirmationEmitter
        estimate = _make_estimate(
            flash_model="gemini-2.5-flash-lite",
            pro_model="gemini-2.5-flash",
        )
        emitter = CLIConfirmationEmitter(yes=True)
        await emitter.confirm("job1", estimate)
        out = capsys.readouterr().out
        assert "gemini-2.5-flash-lite" in out
        assert "gemini-2.5-flash" in out


# ---------------------------------------------------------------------------
# CLIProgressEmitter
# ---------------------------------------------------------------------------

class TestCLIProgressEmitter:
    @pytest.mark.asyncio
    async def test_summarize_header_printed_on_video_started(self, capsys):
        from youtubesynth.cli import CLIProgressEmitter
        emitter = CLIProgressEmitter(
            videos=[_make_video()], concurrency=3,
            pro_model="gemini-2.5-flash", verbose=True
        )
        await emitter.emit("job1", "video_started", {"video_id": "abc123", "title": "Test"})
        assert "Summarizing videos" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_video_done_verbose(self, capsys):
        from youtubesynth.cli import CLIProgressEmitter
        video = _make_video("abc123", "My Video")
        emitter = CLIProgressEmitter(
            videos=[video], concurrency=3,
            pro_model="gemini-2.5-flash", verbose=True
        )
        await emitter.emit("job1", "video_started", {"video_id": "abc123", "title": "My Video"})
        await emitter.emit("job1", "video_done", {
            "video_id": "abc123",
            "transcript_type": "manual",
            "tokens_used": 1200,
        })
        out = capsys.readouterr().out
        assert "\u2713" in out  # ✓
        assert "My Video" in out
        assert "manual" in out
        assert "1,200" in out

    @pytest.mark.asyncio
    async def test_video_failed_verbose(self, capsys):
        from youtubesynth.cli import CLIProgressEmitter
        video = _make_video("abc123", "Deleted Video")
        emitter = CLIProgressEmitter(
            videos=[video], concurrency=3,
            pro_model="gemini-2.5-flash", verbose=True
        )
        await emitter.emit("job1", "video_failed", {
            "video_id": "abc123",
            "error": "No transcript available",
        })
        out = capsys.readouterr().out
        assert "\u2717" in out  # ✗
        assert "Deleted Video" in out
        assert "no transcript" in out

    @pytest.mark.asyncio
    async def test_video_done_silent_without_verbose(self, capsys):
        from youtubesynth.cli import CLIProgressEmitter
        video = _make_video()
        emitter = CLIProgressEmitter(
            videos=[video], concurrency=3,
            pro_model="gemini-2.5-flash", verbose=False
        )
        await emitter.emit("job1", "video_started", {"video_id": "abc123"})
        await emitter.emit("job1", "video_done", {
            "video_id": "abc123",
            "transcript_type": "manual",
            "tokens_used": 500,
        })
        out = capsys.readouterr().out
        # Header prints; per-video line does not
        assert "Summarizing" in out
        assert "\u2713" not in out

    @pytest.mark.asyncio
    async def test_synthesis_start_printed(self, capsys):
        from youtubesynth.cli import CLIProgressEmitter
        emitter = CLIProgressEmitter(
            videos=[_make_video()], concurrency=3,
            pro_model="gemini-2.5-flash", verbose=False
        )
        await emitter.emit("job1", "synthesis_start", {"summary_count": 5})
        out = capsys.readouterr().out
        assert "Synthesizing 5 summaries" in out
        assert "gemini-2.5-flash" in out

    @pytest.mark.asyncio
    async def test_header_printed_once_for_multiple_videos(self, capsys):
        from youtubesynth.cli import CLIProgressEmitter
        videos = [_make_video("v1"), _make_video("v2")]
        emitter = CLIProgressEmitter(
            videos=videos, concurrency=3,
            pro_model="gemini-2.5-flash", verbose=False
        )
        await emitter.emit("job1", "video_started", {"video_id": "v1"})
        await emitter.emit("job1", "video_started", {"video_id": "v2"})
        out = capsys.readouterr().out
        assert out.count("Summarizing videos") == 1


# ---------------------------------------------------------------------------
# main() — keyboard interrupt handling
# ---------------------------------------------------------------------------

def _mock_settings():
    """Return a configured mock for youtubesynth.cli.settings."""
    m = mock.MagicMock()
    m.gemini_api_key = "test-key"
    m.output_dir = "output"
    m.max_videos_per_job = 50
    m.default_concurrency = 3
    m.gemini_model_pro = "gemini-2.5-flash"
    m.gemini_model_flash = "gemini-2.5-flash-lite"
    m.chunk_token_threshold = 8000
    m.summaries_dir = "summaries"
    m.db_path = ":memory:"
    return m


class TestKeyboardInterrupt:
    def test_keyboard_interrupt_exits_130(self, capsys):
        from youtubesynth.cli import main
        video = _make_video()

        async def raise_interrupt(*args, **kwargs):
            raise KeyboardInterrupt

        with (
            mock.patch("sys.argv", ["youtubesynth", "--input", "file.txt", "--yes"]),
            mock.patch("youtubesynth.cli.settings", _mock_settings()),
            mock.patch("youtubesynth.cli.extract_urls", return_value=[video]),
            mock.patch("youtubesynth.cli._async_main", raise_interrupt),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 130
        assert "Aborted" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# main() — successful run (happy path, mocked pipeline)
# ---------------------------------------------------------------------------

class TestMainHappyPath:
    def test_successful_run_prints_output_paths(self, capsys):
        from youtubesynth.cli import main
        video = _make_video()
        fake_result = PipelineResult(
            job_id="abc12345",
            output_path="output/abc12345/overall_summary.md",
            report_path="output/abc12345/token_report.json",
            cost_usd=0.042,
            cancelled=False,
        )

        async def mock_async(*args, **kwargs):
            return fake_result

        with (
            mock.patch("sys.argv", ["youtubesynth", "--input", "file.txt", "--yes"]),
            mock.patch("youtubesynth.cli.settings", _mock_settings()),
            mock.patch("youtubesynth.cli.extract_urls", return_value=[video]),
            mock.patch("youtubesynth.cli._async_main", mock_async),
        ):
            main()

        out = capsys.readouterr().out
        assert "Done" in out
        assert "output/abc12345/overall_summary.md" in out
        assert "output/abc12345/token_report.json" in out
        assert "0.042" in out

    def test_cancelled_run_prints_aborted(self, capsys):
        from youtubesynth.cli import main
        video = _make_video()
        fake_result = PipelineResult(
            job_id="abc12345",
            output_path=None,
            report_path=None,
            cost_usd=0.0,
            cancelled=True,
        )

        async def mock_async(*args, **kwargs):
            return fake_result

        with (
            mock.patch("sys.argv", ["youtubesynth", "--input", "file.txt"]),
            mock.patch("youtubesynth.cli.settings", _mock_settings()),
            mock.patch("youtubesynth.cli.extract_urls", return_value=[video]),
            mock.patch("youtubesynth.cli._async_main", mock_async),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        assert "Aborted" in capsys.readouterr().out

    def test_no_videos_exits_0(self, capsys):
        from youtubesynth.cli import main
        with (
            mock.patch("sys.argv", ["youtubesynth", "--input", "file.txt"]),
            mock.patch("youtubesynth.cli.settings", _mock_settings()),
            mock.patch("youtubesynth.cli.extract_urls", return_value=[]),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0
        assert "No videos found" in capsys.readouterr().out
