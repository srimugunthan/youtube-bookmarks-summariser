import asyncio
import os
from dataclasses import dataclass

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import NoTranscriptFound, TranscriptsDisabled

from youtubesynth.config import settings


def _fmt_snippet(snippet) -> str:
    """Format one transcript snippet as  [MM:SS] text  (or [HH:MM:SS] for >1 hour)."""
    total_seconds = int(snippet.start)
    mm, ss = divmod(total_seconds, 60)
    hh, mm = divmod(mm, 60)
    ts = f"[{hh:02d}:{mm:02d}:{ss:02d}]" if hh else f"[{mm:02d}:{ss:02d}]"
    return f"{ts} {snippet.text.strip()}"


@dataclass
class TranscriptResult:
    video_id: str
    text: str                  # full transcript as a single string
    transcript_type: str       # "manual" | "auto-generated" | "unavailable"
    language: str = "en"
    word_count: int = 0


class YouTubeService:
    def __init__(self, cache_dir: str | None = None, no_cache: bool = False):
        self._cache_dir = cache_dir or settings.cache_dir
        self._no_cache = no_cache

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_transcript(self, video_id: str) -> TranscriptResult:
        """Fetch transcript for a single video, using disk cache when available."""
        if not self._no_cache:
            cached = self._read_cache(video_id)
            if cached is not None:
                return cached

        result = await asyncio.to_thread(self._fetch_transcript, video_id)

        if not self._no_cache and result.transcript_type != "unavailable":
            self._write_cache(result)

        return result

    async def get_transcript_batch(
        self,
        video_ids: list[str],
        semaphore: asyncio.Semaphore,
    ) -> list[TranscriptResult]:
        """Fetch transcripts concurrently, bounded by semaphore."""
        async def _fetch_one(video_id: str) -> TranscriptResult:
            async with semaphore:
                return await self.get_transcript(video_id)

        return await asyncio.gather(*[_fetch_one(vid) for vid in video_ids])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_transcript(self, video_id: str) -> TranscriptResult:
        """Synchronous fetch — called via asyncio.to_thread()."""
        try:
            api = YouTubeTranscriptApi()
            transcript_list = api.list(video_id)

            # Prefer manual captions; fall back to auto-generated
            try:
                transcript = transcript_list.find_manually_created_transcript(
                    ["en", "en-US", "en-GB"]
                )
                transcript_type = "manual"
            except NoTranscriptFound:
                transcript = transcript_list.find_generated_transcript(
                    ["en", "en-US", "en-GB"]
                )
                transcript_type = "auto-generated"

            language = transcript.language_code
            entries = transcript.fetch()
            text = "\n".join(_fmt_snippet(s) for s in entries)
            return TranscriptResult(
                video_id=video_id,
                text=text,
                transcript_type=transcript_type,
                language=language,
                word_count=len(text.split()),
            )

        except (NoTranscriptFound, TranscriptsDisabled):
            return TranscriptResult(
                video_id=video_id,
                text="",
                transcript_type="unavailable",
            )

    def _cache_path(self, video_id: str) -> str:
        return os.path.join(self._cache_dir, f"{video_id}.txt")

    def _read_cache(self, video_id: str) -> TranscriptResult | None:
        path = self._cache_path(video_id)
        if not os.path.exists(path):
            return None

        with open(path, encoding="utf-8") as f:
            lines = f.readlines()

        transcript_type = "manual"
        language = "en"
        text_lines = []

        for line in lines:
            if line.startswith("# transcript_type:"):
                transcript_type = line.split(":", 1)[1].strip()
            elif line.startswith("# language:"):
                language = line.split(":", 1)[1].strip()
            else:
                text_lines.append(line)

        text = "".join(text_lines).strip()
        return TranscriptResult(
            video_id=video_id,
            text=text,
            transcript_type=transcript_type,
            language=language,
            word_count=len(text.split()),
        )

    def _write_cache(self, result: TranscriptResult) -> None:
        os.makedirs(self._cache_dir, exist_ok=True)
        path = self._cache_path(result.video_id)
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# transcript_type: {result.transcript_type}\n")
            f.write(f"# language: {result.language}\n")
            f.write(result.text)
