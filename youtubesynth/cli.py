"""CLI entry point for YouTubeSynth."""

import argparse
import asyncio
import sys
import uuid
from typing import Optional

from youtubesynth.config import settings
from youtubesynth.exceptions import ExtractionError, GeminiError, SynthesisError
from youtubesynth.extractors import extract_urls
from youtubesynth.extractors.url_validator import VideoMeta
from youtubesynth.pipeline import ConfirmationEmitter, PipelineResult, run_pipeline
from youtubesynth.services.db import Database
from youtubesynth.services.token_tracker import CostEstimate


# ---------------------------------------------------------------------------
# Progress emitter — prints formatted lines to stdout
# ---------------------------------------------------------------------------

class CLIProgressEmitter:
    """Translates SSE events from agents into human-readable stdout lines."""

    def __init__(
        self,
        videos: list[VideoMeta],
        concurrency: int,
        pro_model: str,
        verbose: bool = False,
    ) -> None:
        self._total = len(videos)
        self._concurrency = concurrency
        self._pro_model = pro_model
        self._verbose = verbose
        self._done_count = 0
        self._header_printed = False
        # Pre-populate titles so unavailable videos (no video_started event) can be named
        self._title_map: dict[str, str] = {
            v.video_id: (v.title or v.video_id) for v in videos
        }

    def _ensure_summarize_header(self) -> None:
        if not self._header_printed:
            print(f"[youtubesynth] Summarizing videos ({self._concurrency} concurrent)...")
            self._header_printed = True

    async def emit(self, job_id: str, event: str, data: dict) -> None:
        if event == "video_started":
            self._ensure_summarize_header()

        elif event == "video_done":
            self._ensure_summarize_header()
            self._done_count += 1
            if self._verbose:
                idx_w = len(str(self._total))
                video_id = data["video_id"]
                title = self._title_map.get(video_id, video_id)
                t_type = data.get("transcript_type", "unknown")
                tokens = data.get("tokens_used", 0)
                print(
                    f"  [{self._done_count:{idx_w}}/{self._total}]"
                    f" \u2713 \"{title}\"  ({t_type}, {tokens:,} tokens)"
                )

        elif event == "video_failed":
            self._ensure_summarize_header()
            self._done_count += 1
            if self._verbose:
                idx_w = len(str(self._total))
                video_id = data["video_id"]
                title = self._title_map.get(video_id, video_id)
                error = data.get("error", "unknown error")
                reason = (
                    "no transcript \u2014 skipped"
                    if "no transcript" in error.lower()
                    else error
                )
                print(
                    f"  [{self._done_count:{idx_w}}/{self._total}]"
                    f" \u2717 \"{title}\"  ({reason})"
                )

        elif event == "synthesis_start":
            summary_count = data.get("summary_count", "?")
            print(
                f"[youtubesynth] Synthesizing {summary_count} summaries"
                f" \u2192 {self._pro_model}..."
            )

        # job_started and job_done are handled by main(), not here


# ---------------------------------------------------------------------------
# Confirmation emitter — prints cost table and reads y/N from stdin
# ---------------------------------------------------------------------------

class CLIConfirmationEmitter:
    """Prints the pre-run cost estimate and optionally prompts the user."""

    def __init__(self, yes: bool = False) -> None:
        self._yes = yes

    async def confirm(self, job_id: str, estimate: CostEstimate) -> bool:
        # Complete the "Fetching transcripts..." line started by main()
        print(f"  {estimate.available_count} fetched, {estimate.unavailable_count} unavailable")
        print()

        # ── Cost table ──────────────────────────────────────────────────────
        by_agent = estimate.by_agent

        summ_in = estimate.summarizer_input_tokens + estimate.chunk_summarizer_input_tokens
        summ_out = estimate.summarizer_output_tokens + estimate.chunk_summarizer_output_tokens
        summ_cost = (
            by_agent.get("summarizer", {}).get("cost_usd", 0.0)
            + by_agent.get("chunk_summarizer", {}).get("cost_usd", 0.0)
        )

        synth_in = estimate.synthesis_input_tokens
        synth_out = estimate.synthesis_output_tokens
        synth_cost = by_agent.get("synthesis", {}).get("cost_usd", 0.0)

        sep = "\u2500" * 84

        print("Estimated API cost:")
        print(
            f"  Summarization  ({estimate.flash_model}):"
            f"  ~{summ_in:,} input / ~{summ_out:,} output"
            f"  \u2192  ${summ_cost:.3f}"
        )
        print(
            f"  Synthesis      ({estimate.pro_model}):"
            f"  ~{synth_in:,} input / ~{synth_out:,} output"
            f"  \u2192  ${synth_cost:.3f}"
        )
        print(f"  {sep}")
        print(f"  Total estimated cost:  ~${estimate.total_cost_usd:.3f}")
        print()

        if self._yes:
            return True

        try:
            answer = input("Proceed? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False

        return answer == "y"


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="youtubesynth",
        description="YouTubeSynth \u2014 summarise and synthesise YouTube video transcripts.",
    )

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--input", "-i",
        metavar="PATH",
        help="Path to XML, JSON, or TXT file containing YouTube video URLs.",
    )
    source.add_argument(
        "--playlist", "-p",
        metavar="URL",
        help="YouTube playlist URL (extracts all video URLs).",
    )

    parser.add_argument(
        "--style", "-s",
        default="article",
        choices=["tutorial", "article", "guide"],
        help="Output style (default: article).",
    )
    parser.add_argument(
        "--title", "-t",
        metavar="TEXT",
        help="Title for the synthesised output (auto-generated if omitted).",
    )
    parser.add_argument(
        "--output-dir", "-o",
        metavar="PATH",
        default=None,
        help=f"Directory for output files (default: {settings.output_dir}).",
    )
    parser.add_argument(
        "--max-videos",
        metavar="N",
        type=int,
        default=None,
        help=f"Cap number of videos to process (default: {settings.max_videos_per_job}).",
    )
    parser.add_argument(
        "--concurrency",
        metavar="N",
        type=int,
        default=None,
        help=f"Max concurrent Gemini API calls (default: {settings.default_concurrency}).",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass transcript cache and re-fetch from YouTube.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print per-video progress lines to stdout.",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip the cost confirmation prompt and proceed automatically.",
    )

    return parser


# ---------------------------------------------------------------------------
# Async pipeline runner
# ---------------------------------------------------------------------------

async def _async_main(
    job_id: str,
    videos: list[VideoMeta],
    args: argparse.Namespace,
    output_dir: str,
    max_videos: int,
    concurrency: int,
) -> PipelineResult:
    db = Database(settings.db_path)
    await db.connect()
    try:
        progress_emitter = CLIProgressEmitter(
            videos=videos,
            concurrency=concurrency,
            pro_model=settings.gemini_model_pro,
            verbose=args.verbose,
        )
        confirmation_emitter = CLIConfirmationEmitter(yes=args.yes)

        return await run_pipeline(
            job_id=job_id,
            videos=videos,
            style=args.style,
            title=args.title,
            output_dir=output_dir,
            concurrency=concurrency,
            no_cache=args.no_cache,
            db=db,
            progress_callback=progress_emitter,
            confirmation_callback=confirmation_emitter,
        )
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # Validate API key early — no point extracting URLs without it
    if not settings.gemini_api_key:
        print(
            "Error: GEMINI_API_KEY is not set. "
            "Add it to .env or export it as an environment variable.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Resolve defaults that depend on settings (allows per-test overrides)
    output_dir = args.output_dir or settings.output_dir
    max_videos = args.max_videos if args.max_videos is not None else settings.max_videos_per_job
    concurrency = args.concurrency if args.concurrency is not None else settings.default_concurrency

    source = args.input or args.playlist

    # ── Extract URLs ─────────────────────────────────────────────────────────
    print("[youtubesynth] Extracting URLs...", end="  ", flush=True)
    try:
        videos = extract_urls(source, max_videos=max_videos)
    except ExtractionError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"{len(videos)} videos found")

    if not videos:
        print("[youtubesynth] No videos found. Exiting.")
        sys.exit(0)

    # ── Fetch transcripts + run pipeline ─────────────────────────────────────
    print("[youtubesynth] Fetching transcripts...", end="", flush=True)

    job_id = uuid.uuid4().hex[:8]

    try:
        result = asyncio.run(
            _async_main(
                job_id=job_id,
                videos=videos,
                args=args,
                output_dir=output_dir,
                max_videos=max_videos,
                concurrency=concurrency,
            )
        )
    except KeyboardInterrupt:
        print("\n[youtubesynth] Aborted. No Gemini calls were made.", file=sys.stderr)
        sys.exit(130)
    except (GeminiError, SynthesisError, ExtractionError) as exc:
        print(f"\n[youtubesynth] Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if result.cancelled:
        print("[youtubesynth] Aborted. No Gemini calls were made.")
        sys.exit(0)

    print("[youtubesynth] Done.")
    print()
    print(f"Output : {result.output_path}")
    print(f"Report : {result.report_path}")
    print(f"Cost   : ${result.cost_usd:.3f} (actual)")


if __name__ == "__main__":
    main()
