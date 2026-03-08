"""Agent 2 — synthesis agent: merges all per-video summaries into one document."""

import glob
import os
from typing import Optional

from youtubesynth.agents.base_agent import BaseAgent
from youtubesynth.agents.prompts import SYNTHESIS_PROMPT
from youtubesynth.config import settings
from youtubesynth.exceptions import GeminiError, SynthesisError
from youtubesynth.services.db import Database
from youtubesynth.services.gemini_client import GeminiClient
from youtubesynth.services.token_tracker import TokenTracker
from youtubesynth.agents.transcript_summarizer import ProgressEmitter


class SynthesisAgent(BaseAgent):
    """Synthesize all per-video summary files into a single output document."""

    def __init__(
        self,
        db: Database,
        token_tracker: TokenTracker,
        gemini_client: GeminiClient,
        pro_model: str | None = None,
        summaries_dir: str | None = None,
        output_dir: str | None = None,
        style: str = "article",
        progress_emitter: Optional[ProgressEmitter] = None,
    ) -> None:
        super().__init__(db, token_tracker, gemini_client)
        self._pro_model = pro_model or settings.gemini_model_pro
        self._summaries_dir = summaries_dir or settings.summaries_dir
        self._output_dir = output_dir or settings.output_dir
        self._style = style
        self._progress_emitter = progress_emitter

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def synthesize(self, job_id: str) -> str:
        """Read all per-video summaries, call Gemini Pro, write result.md.

        Returns the synthesized markdown string.
        Raises SynthesisError if no summary files exist for the job.
        """
        summary_files = sorted(
            glob.glob(os.path.join(self._summaries_dir, job_id, "*.md"))
        )
        if not summary_files:
            raise SynthesisError(
                f"No summary files found for job {job_id!r} in "
                f"{os.path.join(self._summaries_dir, job_id)}"
            )

        summaries = []
        for path in summary_files:
            with open(path, encoding="utf-8") as f:
                summaries.append(f.read())

        num_videos = len(summaries)

        job_out_dir = os.path.join(self._output_dir, job_id)
        os.makedirs(job_out_dir, exist_ok=True)

        # Write transcripts.md — all per-video summaries in one file
        transcripts_path = os.path.join(job_out_dir, "transcripts.md")
        with open(transcripts_path, "w", encoding="utf-8") as f:
            f.write("\n\n---\n\n".join(summaries))

        await self._emit(job_id, "synthesis_start", {
            "job_id": job_id,
            "summary_count": num_videos,
        })

        prompt = SYNTHESIS_PROMPT.format(
            style=self._style,
            num_videos=num_videos,
            summaries="\n\n---\n\n".join(summaries),
        )

        response = await self._gemini_client.generate(self._pro_model, prompt)

        # Write overall_summary.md
        result_path = os.path.join(job_out_dir, "overall_summary.md")
        with open(result_path, "w", encoding="utf-8") as f:
            f.write(response.text)

        # Record token usage (video_id=None for synthesis)
        await self._token_tracker.record(
            agent="synthesis",
            model=self._pro_model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            video_id=None,
        )

        # Write token report
        report_path = os.path.join(self._output_dir, job_id, "token_report.json")
        await self._token_tracker.write_report(report_path)

        # Mark job done in DB
        await self._db.update_job_status(job_id, "done")

        await self._emit(job_id, "job_done", {
            "job_id": job_id,
            "output_path": result_path,
            "total_cost_usd": response.input_tokens + response.output_tokens,
        })

        return response.text

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _emit(self, job_id: str, event: str, data: dict) -> None:
        if self._progress_emitter is not None:
            await self._progress_emitter.emit(job_id, event, data)
