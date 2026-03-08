"""Composition root — two-phase pipeline shared by CLI and API."""

import asyncio
from dataclasses import dataclass
from typing import Optional, Protocol

from youtubesynth.agents.synthesis_agent import SynthesisAgent
from youtubesynth.agents.transcript_summarizer import ProgressEmitter, TranscriptSummarizer
from youtubesynth.config import settings
from youtubesynth.extractors.url_validator import VideoMeta
from youtubesynth.services.db import Database
from youtubesynth.services.gemini_client import GeminiClient
from youtubesynth.services.token_tracker import CostEstimate, TokenTracker, estimate_cost
from youtubesynth.services.youtube_service import YouTubeService


class ConfirmationEmitter(Protocol):
    async def confirm(self, job_id: str, estimate: CostEstimate) -> bool:
        """Return True to proceed with Gemini calls, False to cancel the job."""
        ...


@dataclass
class PipelineResult:
    job_id: str
    output_path: Optional[str]
    report_path: Optional[str]
    cost_usd: float
    cancelled: bool


async def run_pipeline(
    job_id: str,
    videos: list[VideoMeta],
    style: str,
    title: Optional[str],
    output_dir: str,
    concurrency: int,
    no_cache: bool,
    db: Database,
    summaries_dir: Optional[str] = None,
    flash_model: Optional[str] = None,
    pro_model: Optional[str] = None,
    chunk_token_threshold: Optional[int] = None,
    gemini_client: Optional[GeminiClient] = None,
    progress_callback: Optional[ProgressEmitter] = None,
    confirmation_callback: Optional[ConfirmationEmitter] = None,
) -> PipelineResult:
    """Two-phase pipeline.

    Phase A — free (no Gemini calls):
      1. create_job() in DB (status="fetching")
      2. upsert_video_progress(pending) for all videos
      3. fetch all transcripts concurrently
      4. estimate_cost()
      5. call confirmation_callback(estimate) → bool
         • False → update_job_status("cancelled"); return early
      6. update_job_status("running")

    Phase B — paid (Gemini calls):
      7. TranscriptSummarizer.summarize_batch()
      8. SynthesisAgent.synthesize()
    """
    _summaries_dir = summaries_dir or f"{output_dir}/{job_id}/summaries"
    _flash_model = flash_model or settings.gemini_model_flash
    _pro_model = pro_model or settings.gemini_model_pro
    _chunk_threshold = chunk_token_threshold or settings.chunk_token_threshold
    _gemini_client = gemini_client or GeminiClient()

    token_tracker = TokenTracker(job_id=job_id, db=db)
    semaphore = asyncio.Semaphore(concurrency)

    # ── Phase A ──────────────────────────────────────────────────────────────

    await db.create_job(
        job_id=job_id,
        style=style,
        title=title,
        total_videos=len(videos),
    )
    await db.update_job_status(job_id, "fetching")

    for video in videos:
        await db.upsert_video_progress(
            job_id=job_id,
            video_id=video.video_id,
            title=video.title,
            url=video.url,
            status="pending",
        )

    yt_service = YouTubeService(no_cache=no_cache)
    transcripts = list(
        await yt_service.get_transcript_batch(
            [v.video_id for v in videos], semaphore=semaphore
        )
    )

    cost_estimate = estimate_cost(
        transcripts=transcripts,
        flash_model=_flash_model,
        pro_model=_pro_model,
        chunk_token_threshold=_chunk_threshold,
    )

    await db.update_job_status(job_id, "pending_confirmation")

    if confirmation_callback is not None:
        confirmed = await confirmation_callback.confirm(job_id, cost_estimate)
    else:
        confirmed = True  # auto-confirm when no emitter (e.g. integration tests)

    if not confirmed:
        await db.update_job_status(job_id, "cancelled")
        return PipelineResult(
            job_id=job_id,
            output_path=None,
            report_path=None,
            cost_usd=0.0,
            cancelled=True,
        )

    await db.update_job_status(job_id, "running")

    # Emit job_started so SSE clients know Phase B is beginning
    if progress_callback is not None:
        await progress_callback.emit(job_id, "job_started", {
            "job_id": job_id,
            "total_videos": len(videos),
        })

    # ── Phase B ──────────────────────────────────────────────────────────────

    summarizer = TranscriptSummarizer(
        db=db,
        token_tracker=token_tracker,
        gemini_client=_gemini_client,
        flash_model=_flash_model,
        summaries_dir=_summaries_dir,
        chunk_token_threshold=_chunk_threshold,
        progress_emitter=progress_callback,
    )

    await summarizer.summarize_batch(
        job_id=job_id,
        videos=videos,
        transcripts=transcripts,
        semaphore=semaphore,
    )

    synthesis_agent = SynthesisAgent(
        db=db,
        token_tracker=token_tracker,
        gemini_client=_gemini_client,
        pro_model=_pro_model,
        summaries_dir=_summaries_dir,
        output_dir=output_dir,
        style=style,
        progress_emitter=progress_callback,
    )

    await synthesis_agent.synthesize(job_id=job_id)

    report = await token_tracker.get_report()
    result_path = f"{output_dir}/{job_id}/overall_summary.md"
    report_path = f"{output_dir}/{job_id}/token_report.json"

    return PipelineResult(
        job_id=job_id,
        output_path=result_path,
        report_path=report_path,
        cost_usd=report["total_cost_usd"],
        cancelled=False,
    )
