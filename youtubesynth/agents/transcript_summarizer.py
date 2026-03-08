"""Agent 1 — per-video transcript summarizer with chunking support."""

import asyncio
import os
from typing import Optional, Protocol

import tiktoken

from youtubesynth.agents.base_agent import BaseAgent
from youtubesynth.agents.prompts import (
    CHUNK_SUMMARIZE_PROMPT,
    MERGE_CHUNKS_PROMPT,
    SUMMARIZE_TRANSCRIPT,
)
from youtubesynth.config import settings
from youtubesynth.extractors.url_validator import VideoMeta
from youtubesynth.services.db import Database
from youtubesynth.services.gemini_client import GeminiClient
from youtubesynth.services.token_tracker import TokenTracker
from youtubesynth.services.youtube_service import TranscriptResult


class ProgressEmitter(Protocol):
    async def emit(self, job_id: str, event: str, data: dict) -> None: ...


class TranscriptSummarizer(BaseAgent):
    """Summarize individual videos, chunking long transcripts automatically."""

    def __init__(
        self,
        db: Database,
        token_tracker: TokenTracker,
        gemini_client: GeminiClient,
        flash_model: str | None = None,
        summaries_dir: str | None = None,
        chunk_token_threshold: int | None = None,
        progress_emitter: Optional[ProgressEmitter] = None,
    ) -> None:
        super().__init__(db, token_tracker, gemini_client)
        self._flash_model = flash_model or settings.gemini_model_flash
        self._summaries_dir = summaries_dir or settings.summaries_dir
        self._chunk_token_threshold = chunk_token_threshold or settings.chunk_token_threshold
        self._progress_emitter = progress_emitter
        self._encoder = tiktoken.get_encoding("cl100k_base")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def summarize_video(
        self,
        job_id: str,
        video: VideoMeta,
        transcript: TranscriptResult,
    ) -> Optional[str]:
        """Summarize one video using a pre-fetched transcript.

        Returns the summary markdown string, or None if skipped/failed.
        """
        video_id = video.video_id

        # --- unavailable transcript ---
        if transcript.transcript_type == "unavailable":
            await self._db.update_video_status(
                job_id, video_id, "unavailable", transcript_type="unavailable"
            )
            await self._db.increment_done_videos(job_id)
            await self._emit(job_id, "video_failed", {
                "job_id": job_id,
                "video_id": video_id,
                "error": "No transcript available",
            })
            return None

        # --- resume check ---
        summary_path = self._summary_path(job_id, video_id)
        existing = await self._read_existing_summary(job_id, video_id, summary_path)
        if existing is not None:
            return existing

        # --- mark summarizing ---
        await self._db.update_video_status(job_id, video_id, "summarizing")
        await self._emit(job_id, "video_started", {
            "job_id": job_id,
            "video_id": video_id,
            "title": video.title or video_id,
        })

        try:
            token_count = len(self._encoder.encode(transcript.text))

            if token_count <= self._chunk_token_threshold:
                summary, total_in, total_out = await self._summarize_short(
                    job_id, video_id, video.url, transcript.text
                )
            else:
                summary, total_in, total_out = await self._summarize_long(
                    job_id, video_id, video.url, transcript.text
                )

        except Exception as exc:
            await self._db.update_video_status(
                job_id, video_id, "failed", error=str(exc)
            )
            await self._db.increment_done_videos(job_id)
            await self._emit(job_id, "video_failed", {
                "job_id": job_id,
                "video_id": video_id,
                "error": str(exc),
            })
            return None

        # --- write summary file ---
        os.makedirs(os.path.dirname(summary_path), exist_ok=True)
        title_line = video.title or video_id
        header = f"# {title_line}\n\n**URL:** [{video.url}]({video.url})\n\n"
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(header + summary)

        await self._db.update_video_status(
            job_id, video_id, "done", transcript_type=transcript.transcript_type
        )
        await self._db.increment_done_videos(job_id)
        await self._emit(job_id, "video_done", {
            "job_id": job_id,
            "video_id": video_id,
            "transcript_type": transcript.transcript_type,
            "tokens_used": total_in + total_out,
        })

        return summary

    async def summarize_batch(
        self,
        job_id: str,
        videos: list[VideoMeta],
        transcripts: list[TranscriptResult],
        semaphore: asyncio.Semaphore,
    ) -> list[Optional[str]]:
        """Summarize a batch of videos concurrently, bounded by semaphore."""
        async def _one(video: VideoMeta, transcript: TranscriptResult) -> Optional[str]:
            async with semaphore:
                return await self.summarize_video(job_id, video, transcript)

        return list(await asyncio.gather(
            *[_one(v, t) for v, t in zip(videos, transcripts)]
        ))

    # ------------------------------------------------------------------
    # Short-path: single Flash call
    # ------------------------------------------------------------------

    async def _summarize_short(
        self, job_id: str, video_id: str, video_url: str, text: str
    ) -> tuple[str, int, int]:
        prompt = SUMMARIZE_TRANSCRIPT.format(video_url=video_url, transcript=text)
        response = await self._gemini_client.generate(self._flash_model, prompt)
        await self._token_tracker.record(
            agent="summarizer",
            model=self._flash_model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            video_id=video_id,
        )
        return response.text, response.input_tokens, response.output_tokens

    # ------------------------------------------------------------------
    # Long-path: chunk → chunk_summarizer → merge → summarizer
    # ------------------------------------------------------------------

    async def _summarize_long(
        self, job_id: str, video_id: str, video_url: str, text: str
    ) -> tuple[str, int, int]:
        chunks = self._split_into_chunks(text)
        chunk_summaries: list[str] = []
        total_in = 0
        total_out = 0

        for chunk in chunks:
            prompt = CHUNK_SUMMARIZE_PROMPT.format(video_url=video_url, chunk=chunk)
            response = await self._gemini_client.generate(self._flash_model, prompt)
            await self._token_tracker.record(
                agent="chunk_summarizer",
                model=self._flash_model,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                video_id=video_id,
            )
            chunk_summaries.append(response.text)
            total_in += response.input_tokens
            total_out += response.output_tokens

        # Merge all chunk summaries into the final formatted summary
        merge_prompt = MERGE_CHUNKS_PROMPT.format(
            video_url=video_url,
            chunk_summaries="\n\n".join(chunk_summaries),
        )
        merge_response = await self._gemini_client.generate(self._flash_model, merge_prompt)
        await self._token_tracker.record(
            agent="summarizer",
            model=self._flash_model,
            input_tokens=merge_response.input_tokens,
            output_tokens=merge_response.output_tokens,
            video_id=video_id,
        )
        total_in += merge_response.input_tokens
        total_out += merge_response.output_tokens

        return merge_response.text, total_in, total_out

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _split_into_chunks(self, text: str) -> list[str]:
        """Split transcript text into chunks not exceeding chunk_token_threshold."""
        lines = text.splitlines(keepends=True)
        chunks: list[str] = []
        current_lines: list[str] = []
        current_tokens = 0

        for line in lines:
            line_tokens = len(self._encoder.encode(line))
            if current_tokens + line_tokens > self._chunk_token_threshold and current_lines:
                chunks.append("".join(current_lines))
                current_lines = [line]
                current_tokens = line_tokens
            else:
                current_lines.append(line)
                current_tokens += line_tokens

        if current_lines:
            chunks.append("".join(current_lines))

        return chunks

    def _summary_path(self, job_id: str, video_id: str) -> str:
        return os.path.join(self._summaries_dir, job_id, f"{video_id}.md")

    async def _read_existing_summary(
        self, job_id: str, video_id: str, summary_path: str
    ) -> Optional[str]:
        """Return cached summary if DB shows done and file exists, else None."""
        if not os.path.exists(summary_path):
            return None
        videos = await self._db.get_job_videos(job_id)
        for v in videos:
            if v["video_id"] == video_id and v["status"] == "done":
                with open(summary_path, encoding="utf-8") as f:
                    return f.read()
        return None

    async def _emit(self, job_id: str, event: str, data: dict) -> None:
        if self._progress_emitter is not None:
            await self._progress_emitter.emit(job_id, event, data)
