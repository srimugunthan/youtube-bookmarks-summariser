import json
import os
from dataclasses import dataclass, field
from typing import Protocol, Sequence

import tiktoken

from youtubesynth.services.db import Database

PRICING: dict[str, dict[str, float]] = {
    # Current models
    "gemini-2.5-flash-lite": {"input": 0.10 / 1_000_000, "output": 0.40 / 1_000_000},
    "gemini-2.5-flash":      {"input": 0.30 / 1_000_000, "output": 2.50 / 1_000_000},
    # Legacy (deprecated) — kept for historical token reports
    "gemini-1.5-flash":      {"input": 0.075 / 1_000_000, "output": 0.30 / 1_000_000},
    "gemini-1.5-pro":        {"input": 3.50  / 1_000_000, "output": 10.50 / 1_000_000},
}


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return cost in USD for a single Gemini call."""
    pricing = PRICING.get(model, {"input": 0.0, "output": 0.0})
    return input_tokens * pricing["input"] + output_tokens * pricing["output"]


# ---------------------------------------------------------------------------
# Pre-run cost estimation (no Gemini calls made)
# ---------------------------------------------------------------------------

class _Transcript(Protocol):
    """Structural protocol satisfied by TranscriptResult and test stubs alike."""
    text: str
    transcript_type: str


@dataclass
class CostEstimate:
    """Projected API cost for a batch of transcripts before any Gemini calls."""
    flash_model: str
    pro_model: str
    available_count: int
    unavailable_count: int
    # Tokens from direct (short) summarize calls and the merge step of chunked videos
    summarizer_input_tokens: int
    summarizer_output_tokens: int
    # Tokens from the per-chunk Flash calls on long transcripts
    chunk_summarizer_input_tokens: int
    chunk_summarizer_output_tokens: int
    # Tokens for the final Pro synthesis call
    synthesis_input_tokens: int
    synthesis_output_tokens: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    by_agent: dict = field(default_factory=dict)


def estimate_cost(
    transcripts: Sequence[_Transcript],
    flash_model: str,
    pro_model: str,
    chunk_token_threshold: int = 8000,
    output_ratio: float = 0.25,
    synthesis_output_tokens: int = 3000,
) -> CostEstimate:
    """
    Estimate API cost for a transcript batch without making any Gemini calls.

    Token counts use tiktoken cl100k_base as a proxy for Gemini token counts.

    Chunking model (mirrors TranscriptSummarizer):
      Short transcript (≤ threshold):
        - 1 Flash call (summarizer):  input=T, output=T*ratio
      Long transcript (> threshold):
        - N Flash calls (chunk_summarizer): input=T, output=T*ratio  (chunk summaries)
        - 1 Flash call (summarizer/merge):  input=T*ratio, output=T*ratio*ratio

    Synthesis:
      - 1 Pro call: input = sum of all per-video final summaries, output = fixed estimate
    """
    encoder = tiktoken.get_encoding("cl100k_base")

    available = [t for t in transcripts if t.transcript_type != "unavailable"]
    unavailable_count = len(transcripts) - len(available)

    summarizer_input = 0
    summarizer_output = 0
    chunk_summarizer_input = 0
    chunk_summarizer_output = 0
    per_video_finals: list[int] = []

    for t in available:
        token_count = len(encoder.encode(t.text))

        if token_count <= chunk_token_threshold:
            out = int(token_count * output_ratio)
            summarizer_input += token_count
            summarizer_output += out
            per_video_finals.append(out)
        else:
            # Phase 1 — chunk_summarizer calls
            chunk_out = int(token_count * output_ratio)
            chunk_summarizer_input += token_count
            chunk_summarizer_output += chunk_out
            # Phase 2 — merge call (summarizer uses chunk summaries as input)
            merge_out = int(chunk_out * output_ratio)
            summarizer_input += chunk_out
            summarizer_output += merge_out
            per_video_finals.append(merge_out)

    synth_input = sum(per_video_finals)
    synth_output = synthesis_output_tokens if per_video_finals else 0

    flash_p = PRICING.get(flash_model, {"input": 0.0, "output": 0.0})
    pro_p = PRICING.get(pro_model, {"input": 0.0, "output": 0.0})

    summarizer_cost = summarizer_input * flash_p["input"] + summarizer_output * flash_p["output"]
    chunk_cost = chunk_summarizer_input * flash_p["input"] + chunk_summarizer_output * flash_p["output"]
    synthesis_cost = synth_input * pro_p["input"] + synth_output * pro_p["output"]

    by_agent: dict = {}
    if summarizer_input or summarizer_output:
        by_agent["summarizer"] = {
            "input_tokens": summarizer_input,
            "output_tokens": summarizer_output,
            "cost_usd": round(summarizer_cost, 8),
        }
    if chunk_summarizer_input or chunk_summarizer_output:
        by_agent["chunk_summarizer"] = {
            "input_tokens": chunk_summarizer_input,
            "output_tokens": chunk_summarizer_output,
            "cost_usd": round(chunk_cost, 8),
        }
    if synth_input or synth_output:
        by_agent["synthesis"] = {
            "input_tokens": synth_input,
            "output_tokens": synth_output,
            "cost_usd": round(synthesis_cost, 8),
        }

    total_input = summarizer_input + chunk_summarizer_input + synth_input
    total_output = summarizer_output + chunk_summarizer_output + synth_output
    total_cost = summarizer_cost + chunk_cost + synthesis_cost

    return CostEstimate(
        flash_model=flash_model,
        pro_model=pro_model,
        available_count=len(available),
        unavailable_count=unavailable_count,
        summarizer_input_tokens=summarizer_input,
        summarizer_output_tokens=summarizer_output,
        chunk_summarizer_input_tokens=chunk_summarizer_input,
        chunk_summarizer_output_tokens=chunk_summarizer_output,
        synthesis_input_tokens=synth_input,
        synthesis_output_tokens=synth_output,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_cost_usd=round(total_cost, 8),
        by_agent=by_agent,
    )


class TokenTracker:
    """Records every Gemini call to SQLite and produces cost reports."""

    def __init__(self, job_id: str, db: Database):
        self._job_id = job_id
        self._db = db

    async def record(
        self,
        agent: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        video_id: str | None = None,
    ) -> float:
        """Persist one token usage row. Returns cost_usd."""
        cost = compute_cost(model, input_tokens, output_tokens)
        await self._db.insert_token_usage(
            job_id=self._job_id,
            video_id=video_id,
            agent=agent,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )
        return cost

    async def get_report(self) -> dict:
        """Aggregate token usage for this job into a cost report."""
        rows = await self._db.get_token_usage(self._job_id)

        total_input = 0
        total_output = 0
        total_cost = 0.0
        by_agent: dict[str, dict] = {}
        by_video_map: dict[str, dict] = {}

        for row in rows:
            total_input += row["input_tokens"]
            total_output += row["output_tokens"]
            total_cost += row["cost_usd"]

            agent = row["agent"]
            if agent not in by_agent:
                by_agent[agent] = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
            by_agent[agent]["input_tokens"] += row["input_tokens"]
            by_agent[agent]["output_tokens"] += row["output_tokens"]
            by_agent[agent]["cost_usd"] += row["cost_usd"]

            vid = row["video_id"]
            if vid is not None:
                if vid not in by_video_map:
                    by_video_map[vid] = {"video_id": vid, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
                by_video_map[vid]["input_tokens"] += row["input_tokens"]
                by_video_map[vid]["output_tokens"] += row["output_tokens"]
                by_video_map[vid]["cost_usd"] += row["cost_usd"]

        # Round agent costs to avoid floating point noise in reports
        for agent_data in by_agent.values():
            agent_data["cost_usd"] = round(agent_data["cost_usd"], 8)

        return {
            "job_id": self._job_id,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_cost_usd": round(total_cost, 8),
            "by_agent": by_agent,
            "by_video": list(by_video_map.values()),
        }

    async def write_report(self, output_path: str) -> dict:
        """Write the token report as JSON to output_path. Returns the report dict."""
        report = await self.get_report()
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        return report
