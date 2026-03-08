"""Tests for SynthesisAgent (Phase 7)."""

import json
import os
import pytest
from unittest.mock import AsyncMock

from youtubesynth.agents.synthesis_agent import SynthesisAgent
from youtubesynth.exceptions import SynthesisError
from youtubesynth.services.gemini_client import GeminiResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(tmp_path, db=None, token_tracker=None, gemini_client=None,
                style="article"):
    if db is None:
        db = AsyncMock()
    if token_tracker is None:
        token_tracker = AsyncMock()
        token_tracker.record = AsyncMock(return_value=0.01)
        token_tracker.write_report = AsyncMock(return_value={"job_id": "j1"})
    if gemini_client is None:
        gemini_client = AsyncMock()
        gemini_client.generate = AsyncMock(
            return_value=GeminiResponse(text="# Synthesis", input_tokens=100, output_tokens=50)
        )

    return SynthesisAgent(
        db=db,
        token_tracker=token_tracker,
        gemini_client=gemini_client,
        summaries_dir=str(tmp_path / "summaries"),
        output_dir=str(tmp_path / "output"),
        style=style,
    )


def _write_summaries(tmp_path, job_id, summaries: dict[str, str]):
    summary_dir = tmp_path / "summaries" / job_id
    summary_dir.mkdir(parents=True)
    for filename, content in summaries.items():
        (summary_dir / filename).write_text(content)


# ---------------------------------------------------------------------------
# Test: reads all summary files
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reads_all_summary_files(tmp_path):
    _write_summaries(tmp_path, "job1", {
        "vid001.md": "Summary of video 1.",
        "vid002.md": "Summary of video 2.",
        "vid003.md": "Summary of video 3.",
    })

    gemini_client = AsyncMock()
    gemini_client.generate = AsyncMock(
        return_value=GeminiResponse(text="synthesis", input_tokens=300, output_tokens=80)
    )
    token_tracker = AsyncMock()
    token_tracker.record = AsyncMock(return_value=0.01)
    token_tracker.write_report = AsyncMock(return_value={})

    agent = _make_agent(tmp_path, gemini_client=gemini_client, token_tracker=token_tracker)
    await agent.synthesize("job1")

    # All 3 summary bodies should appear in the prompt passed to Gemini
    prompt_arg = gemini_client.generate.call_args.args[1]
    assert "Summary of video 1." in prompt_arg
    assert "Summary of video 2." in prompt_arg
    assert "Summary of video 3." in prompt_arg


# ---------------------------------------------------------------------------
# Test: result.md written
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_result_written(tmp_path):
    _write_summaries(tmp_path, "jobA", {"vid001.md": "Content."})

    gemini_client = AsyncMock()
    gemini_client.generate = AsyncMock(
        return_value=GeminiResponse(text="# Final Result", input_tokens=100, output_tokens=40)
    )
    token_tracker = AsyncMock()
    token_tracker.record = AsyncMock(return_value=0.01)
    token_tracker.write_report = AsyncMock(return_value={})

    agent = _make_agent(tmp_path, gemini_client=gemini_client, token_tracker=token_tracker)
    result = await agent.synthesize("jobA")

    assert result == "# Final Result"
    result_file = tmp_path / "output" / "jobA" / "overall_summary.md"
    assert result_file.exists()
    assert result_file.read_text() == "# Final Result"
    transcripts_file = tmp_path / "output" / "jobA" / "transcripts.md"
    assert transcripts_file.exists()


# ---------------------------------------------------------------------------
# Test: token usage recorded with agent="synthesis" and video_id=None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_token_agent_is_synthesis(tmp_path):
    _write_summaries(tmp_path, "job2", {"vid001.md": "Content."})

    token_tracker = AsyncMock()
    token_tracker.record = AsyncMock(return_value=0.01)
    token_tracker.write_report = AsyncMock(return_value={})

    gemini_client = AsyncMock()
    gemini_client.generate = AsyncMock(
        return_value=GeminiResponse(text="ok", input_tokens=120, output_tokens=60)
    )

    agent = _make_agent(tmp_path, gemini_client=gemini_client, token_tracker=token_tracker)
    await agent.synthesize("job2")

    token_tracker.record.assert_called_once_with(
        agent="synthesis",
        model=agent._pro_model,
        input_tokens=120,
        output_tokens=60,
        video_id=None,
    )


# ---------------------------------------------------------------------------
# Test: token_report.json written
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_token_report_written(tmp_path):
    _write_summaries(tmp_path, "job3", {"vid001.md": "Content."})

    report_data = {"job_id": "job3", "total_cost_usd": 0.005}
    token_tracker = AsyncMock()
    token_tracker.record = AsyncMock(return_value=0.01)
    token_tracker.write_report = AsyncMock(return_value=report_data)

    gemini_client = AsyncMock()
    gemini_client.generate = AsyncMock(
        return_value=GeminiResponse(text="ok", input_tokens=100, output_tokens=40)
    )

    agent = _make_agent(tmp_path, gemini_client=gemini_client, token_tracker=token_tracker)
    await agent.synthesize("job3")

    expected_report_path = str(tmp_path / "output" / "job3" / "token_report.json")
    token_tracker.write_report.assert_called_once_with(expected_report_path)


# ---------------------------------------------------------------------------
# Test: SSE events emitted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sse_events_emitted(tmp_path):
    _write_summaries(tmp_path, "job4", {"vid001.md": "Content.", "vid002.md": "More."})

    emitted = []

    class _Emitter:
        async def emit(self, job_id, event, data):
            emitted.append((event, data))

    token_tracker = AsyncMock()
    token_tracker.record = AsyncMock(return_value=0.01)
    token_tracker.write_report = AsyncMock(return_value={})

    gemini_client = AsyncMock()
    gemini_client.generate = AsyncMock(
        return_value=GeminiResponse(text="synthesis", input_tokens=100, output_tokens=40)
    )

    agent = SynthesisAgent(
        db=AsyncMock(),
        token_tracker=token_tracker,
        gemini_client=gemini_client,
        summaries_dir=str(tmp_path / "summaries"),
        output_dir=str(tmp_path / "output"),
        progress_emitter=_Emitter(),
    )
    await agent.synthesize("job4")

    events = [e for e, _ in emitted]
    assert "synthesis_start" in events
    assert "job_done" in events

    # synthesis_start should include summary_count=2
    start_data = next(d for e, d in emitted if e == "synthesis_start")
    assert start_data["summary_count"] == 2


# ---------------------------------------------------------------------------
# Test: empty summaries raises SynthesisError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_summaries_raises(tmp_path):
    # No summary files written
    agent = _make_agent(tmp_path)

    with pytest.raises(SynthesisError):
        await agent.synthesize("jobEmpty")


# ---------------------------------------------------------------------------
# Test: job status updated to "done"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_job_status_done(tmp_path):
    _write_summaries(tmp_path, "job5", {"vid001.md": "Content."})

    db = AsyncMock()
    token_tracker = AsyncMock()
    token_tracker.record = AsyncMock(return_value=0.01)
    token_tracker.write_report = AsyncMock(return_value={})

    gemini_client = AsyncMock()
    gemini_client.generate = AsyncMock(
        return_value=GeminiResponse(text="done", input_tokens=80, output_tokens=30)
    )

    agent = _make_agent(tmp_path, db=db, gemini_client=gemini_client, token_tracker=token_tracker)
    await agent.synthesize("job5")

    db.update_job_status.assert_called_once_with("job5", "done")


# ---------------------------------------------------------------------------
# Test: style and num_videos injected into prompt
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prompt_includes_style_and_num_videos(tmp_path):
    _write_summaries(tmp_path, "job6", {
        "vid001.md": "Summary A.",
        "vid002.md": "Summary B.",
    })

    gemini_client = AsyncMock()
    gemini_client.generate = AsyncMock(
        return_value=GeminiResponse(text="ok", input_tokens=100, output_tokens=40)
    )
    token_tracker = AsyncMock()
    token_tracker.record = AsyncMock(return_value=0.01)
    token_tracker.write_report = AsyncMock(return_value={})

    agent = _make_agent(tmp_path, gemini_client=gemini_client,
                        token_tracker=token_tracker, style="tutorial")
    await agent.synthesize("job6")

    prompt_arg = gemini_client.generate.call_args.args[1]
    assert "tutorial" in prompt_arg
    assert "2" in prompt_arg  # num_videos
