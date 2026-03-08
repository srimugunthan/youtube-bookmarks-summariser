"""SSE infrastructure: per-job event queues and confirmation gate."""

import asyncio
import json
from typing import AsyncIterator, Optional

from youtubesynth.services.db import Database
from youtubesynth.services.token_tracker import CostEstimate


def _estimate_to_dict(estimate: CostEstimate) -> dict:
    return {
        "flash_model": estimate.flash_model,
        "pro_model": estimate.pro_model,
        "available_count": estimate.available_count,
        "unavailable_count": estimate.unavailable_count,
        "summarizer_input_tokens": estimate.summarizer_input_tokens,
        "summarizer_output_tokens": estimate.summarizer_output_tokens,
        "chunk_summarizer_input_tokens": estimate.chunk_summarizer_input_tokens,
        "chunk_summarizer_output_tokens": estimate.chunk_summarizer_output_tokens,
        "synthesis_input_tokens": estimate.synthesis_input_tokens,
        "synthesis_output_tokens": estimate.synthesis_output_tokens,
        "total_input_tokens": estimate.total_input_tokens,
        "total_output_tokens": estimate.total_output_tokens,
        "total_cost_usd": estimate.total_cost_usd,
        "by_agent": estimate.by_agent,
    }


class SSEManager:
    """Manages per-job SSE queues and confirmation events."""

    def __init__(self) -> None:
        # per-job event queues: job_id → asyncio.Queue of (event, data) tuples
        self._queues: dict[str, asyncio.Queue] = {}
        # per-job confirmation events: job_id → asyncio.Event; True=confirmed, False=cancelled
        self._confirm_events: dict[str, asyncio.Event] = {}
        self._confirm_results: dict[str, bool] = {}

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    def register(self, job_id: str) -> None:
        """Create queue and confirmation event for a new job."""
        self._queues[job_id] = asyncio.Queue()
        self._confirm_events[job_id] = asyncio.Event()
        self._confirm_results[job_id] = False

    def unregister(self, job_id: str) -> None:
        self._queues.pop(job_id, None)
        self._confirm_events.pop(job_id, None)
        self._confirm_results.pop(job_id, None)

    # ------------------------------------------------------------------
    # Emit
    # ------------------------------------------------------------------

    async def emit(self, job_id: str, event: str, data: dict) -> None:
        """Put an event on the job's queue (no-op if job not registered)."""
        q = self._queues.get(job_id)
        if q is not None:
            await q.put((event, data))

    # ------------------------------------------------------------------
    # Stream
    # ------------------------------------------------------------------

    async def stream_events(self, job_id: str) -> AsyncIterator[str]:
        """Yield SSE-formatted strings until job_done/job_cancelled/job_failed."""
        q = self._queues.get(job_id)
        if q is None:
            return

        terminal = {"job_done", "job_cancelled", "job_failed"}
        while True:
            event, data = await q.get()
            payload = json.dumps(data)
            yield f"event: {event}\ndata: {payload}\n\n"
            if event in terminal:
                break

    # ------------------------------------------------------------------
    # Confirmation gate
    # ------------------------------------------------------------------

    async def wait_for_confirmation(self, job_id: str) -> bool:
        """Block until /confirm or /cancel is called. Returns True if confirmed."""
        event = self._confirm_events.get(job_id)
        if event is None:
            return False
        await event.wait()
        return self._confirm_results.get(job_id, False)

    def set_confirmed(self, job_id: str) -> None:
        self._confirm_results[job_id] = True
        ev = self._confirm_events.get(job_id)
        if ev:
            ev.set()

    def set_cancelled(self, job_id: str) -> None:
        self._confirm_results[job_id] = False
        ev = self._confirm_events.get(job_id)
        if ev:
            ev.set()


# Module-level singleton shared by routes and background tasks
sse_manager = SSEManager()


# ---------------------------------------------------------------------------
# APIConfirmationEmitter
# ---------------------------------------------------------------------------

class APIConfirmationEmitter:
    """Emits confirmation_required SSE event; blocks until /confirm or /cancel."""

    def __init__(self, db: Database, manager: Optional[SSEManager] = None) -> None:
        self._db = db
        self._manager = manager or sse_manager

    async def confirm(self, job_id: str, estimate: CostEstimate) -> bool:
        await self._manager.emit(job_id, "confirmation_required", {
            "job_id": job_id,
            "estimate": _estimate_to_dict(estimate),
        })
        await self._db.update_job_status(job_id, "pending_confirmation")
        return await self._manager.wait_for_confirmation(job_id)
