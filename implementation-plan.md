# YouTubeSynth — Implementation Plan

> **Status:** All 11 phases implemented and tested. 143/143 backend tests passing. Frontend builds cleanly.

---

## Phase Dependency Order

```
Phase 1 (scaffolding)
  ├── Phase 2 (extractors)
  ├── Phase 3 (database)
  │     ├── Phase 4 (youtube_service)
  │     └── Phase 5 (gemini_client + token_tracker)
  │           ├── Phase 6 (Agent 1: summarizer)
  │           │     └── Phase 7 (Agent 2: synthesis)
  │           │           └── Phase 8 (CLI + pipeline.py)
  │           │                 └── Phase 9 (FastAPI + SSE)
  │           │                       └── Phase 10 (integration tests)
  │           │                             └── Phase 11 (React frontend)
  └── (config.py imported by all)
```

Phases 1–5 have **zero LLM or network calls** in their test suites — all tests use mocks.

---

## Phase 1 — Project Scaffolding and Package Setup

**Goal:** Working editable install. `youtubesynth --help` prints a stub message. All dependencies importable.

### Files to create

| File | Purpose |
|---|---|
| `pyproject.toml` | Package metadata, all runtime deps, console script entry point, dev extras |
| `requirements.txt` | Pinned lock file (generated via `pip freeze`) |
| `.env.example` | Template of all environment variables |
| `.gitignore` | Excludes `.env`, `.data/`, `.cache/`, `output/`, `summaries/`, `__pycache__/` |
| `README.md` | Project overview and quickstart |
| `youtubesynth/__init__.py` | Package root, `__version__ = "0.1.0"` |
| `youtubesynth/config.py` | Pydantic `BaseSettings` loading `.env`; single source of truth for all config |
| `youtubesynth/exceptions.py` | Custom exception hierarchy: `YouTubeSynthError`, `ExtractionError`, `TranscriptError`, `GeminiError`, `JobNotFoundError` |
| `youtubesynth/cli.py` | **Stub** — `argparse` with no args, prints placeholder message |
| `youtubesynth/main.py` | **Stub** — FastAPI app with `/health` endpoint only |
| `youtubesynth/extractors/__init__.py` | Empty |
| `youtubesynth/agents/__init__.py` | Empty |
| `youtubesynth/services/__init__.py` | Empty |
| `youtubesynth/api/__init__.py` | Empty |
| `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py` | Empty |

**`pyproject.toml` key sections:**

```toml
[project]
name = "youtubesynth"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "fastapi>=0.109.0", "uvicorn>=0.27.0", "sse-starlette>=1.6.0",
    "pydantic>=2.0.0", "pydantic-settings>=2.0.0",
    "google-genai>=1.0.0",           # NOTE: NOT google-generativeai (deprecated)
    "youtube-transcript-api>=0.6.0", "yt-dlp>=2024.0.0",
    "aiosqlite>=0.19.0", "aiohttp>=3.9.0",
    "beautifulsoup4>=4.12.0", "python-dotenv>=1.0.0",
    "python-multipart>=0.0.9",       # required for FastAPI Form/File endpoints
    "tiktoken>=0.5.0",
]

[project.optional-dependencies]
dev = ["pytest>=7.0", "pytest-asyncio>=0.23", "httpx>=0.27", "pytest-mock>=3.12", "pytest-cov>=4.0"]

[project.scripts]
youtubesynth = "youtubesynth.cli:main"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

### How to test Phase 1

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

youtubesynth --help
# Expected: usage: youtubesynth [-h]  +  stub message

uvicorn youtubesynth.main:app --port 8000 &
curl http://localhost:8000/health
# Expected: {"status":"ok"}
kill %1

python -c "import fastapi, google.generativeai, youtube_transcript_api, yt_dlp, aiosqlite, tiktoken"
# Expected: no output (no import errors)

pytest tests/
# Expected: "no tests ran" or "collected 0 items"
```

---

## Phase 2 — URL Extractors and Validator

**Goal:** All four extractors + URL validator return `VideoMeta` lists from fixture files. No LLM involved.

### Files to create

| File | Purpose |
|---|---|
| `youtubesynth/extractors/url_validator.py` | `extract_video_id()`, `normalize_url()`, `VideoMeta` dataclass |
| `youtubesynth/extractors/xml_extractor.py` | `extract_from_xml()` — stdlib ET + beautifulsoup4 fallback |
| `youtubesynth/extractors/json_extractor.py` | `extract_from_json()` — handles array/object/nested/Takeout schemas |
| `youtubesynth/extractors/txt_extractor.py` | `extract_from_txt()` — skips `#` comments and blank lines |
| `youtubesynth/extractors/playlist_extractor.py` | `extract_from_playlist()` — yt-dlp Python API, respects `max_videos` cap |
| `youtubesynth/extractors/__init__.py` | `extract_urls(source, max_videos)` dispatcher — detects type by extension or URL pattern |
| `tests/fixtures/sample_videos.xml` | 5 YouTube URLs in bookmark XML format, 1 non-YouTube URL (filtered out) |
| `tests/fixtures/sample_videos.json` | 5 entries in `{"videos": [...]}` format with titles |
| `tests/fixtures/sample_videos.txt` | 5 lines, 1 comment, 1 blank line, 1 duplicate |
| `tests/unit/test_url_validator.py` | Tests all URL formats, invalid URLs, `VideoMeta` fields |
| `tests/unit/test_extractors.py` | Tests each extractor with fixtures; tests unified dispatcher |

**Supported YouTube URL formats:**
- `https://www.youtube.com/watch?v=VIDEO_ID`
- `https://youtu.be/VIDEO_ID`
- `https://www.youtube.com/embed/VIDEO_ID`
- `https://www.youtube.com/shorts/VIDEO_ID`

### How to test Phase 2

```bash
pytest tests/unit/test_url_validator.py tests/unit/test_extractors.py -v
# Expected: 14+ tests, all PASSED

python -c "
from youtubesynth.extractors import extract_urls
videos = extract_urls('tests/fixtures/sample_videos.txt', max_videos=50)
print(f'Extracted {len(videos)} videos')   # duplicates deduped
for v in videos: print(f'  {v.video_id}: {v.url}')
"
```

---

## Phase 3 — Database Layer

**Goal:** Async SQLite CRUD for all three tables via `aiosqlite`. All DB operations tested with in-memory SQLite.

### Files to create

| File | Purpose |
|---|---|
| `youtubesynth/services/db.py` | `Database` class — `connect()`, `close()`, schema migrations, all CRUD methods |
| `tests/unit/test_db.py` | Fixture uses `Database(":memory:")` — tests all CRUD methods |

**`Database` class methods:**

```python
# Job operations
async def create_job(job_id, style, title, total_videos) -> None
async def update_job_status(job_id, status) -> None
async def increment_done_videos(job_id) -> None
async def get_job(job_id) -> dict | None

# Video progress
async def upsert_video_progress(job_id, video_id, title, url, status, ...) -> None
async def update_video_status(job_id, video_id, status, transcript_type=None, error=None) -> None
async def get_job_videos(job_id) -> list[dict]

# Token usage
async def insert_token_usage(job_id, video_id, agent, model, input_tokens, output_tokens, cost_usd) -> None
async def get_token_usage(job_id) -> list[dict]
```

All timestamps use `datetime.utcnow().isoformat() + "Z"`. DB directory auto-created on connect.

### Why each table exists and when it is written

**`jobs` — job lifecycle**
- Written at pipeline start (`create_job`), at each status transition (`pending → running → done / failed`), and after each video completes (`increment_done_videos`).
- Powers `GET /api/jobs/{job_id}` progress polling and crash-recovery (pipeline checks `status == running` on restart).

**`video_progress` — per-video status**
- Written when Agent 1 starts a video (`summarizing`) and again when it finishes (`done / failed / unavailable`).
- Resume logic: before processing a video the pipeline checks `status == done` AND summary file exists — if both true, that video is skipped entirely (no re-fetch, no re-call to Gemini).

**`token_usage` — cost ledger**
- Written after every Gemini call (each chunk summary, each video summary, the synthesis call). `video_id` is `NULL` for the Agent 2 synthesis row.
- Aggregated at job completion into `token_report.json` and displayed in CLI output and the React UI stats bar.

### Data flow through the DB

```
pipeline start
    │
    ├─ create_job()                           ← jobs
    │
    ├─ for each video:
    │   ├─ upsert_video_progress(pending)     ← video_progress
    │   ├─ [fetch transcript]
    │   ├─ upsert_video_progress(summarizing) ← video_progress
    │   ├─ [call Gemini Flash]
    │   ├─ insert_token_usage()               ← token_usage
    │   ├─ update_video_status(done/failed)   ← video_progress
    │   └─ increment_done_videos()            ← jobs
    │
    ├─ [call Gemini Pro for synthesis]
    ├─ insert_token_usage(video_id=NULL)      ← token_usage
    └─ update_job_status(done)               ← jobs
```

### How to test Phase 3

```bash
pytest tests/unit/test_db.py -v
# Expected: 7+ tests, all PASSED
# Tests: create_job, get_job_not_found, update_status, increment_done_videos,
#        upsert_video_progress, update_video_status, insert_and_get_token_usage
```

---

## Phase 4 — YouTube Transcript Service

**Goal:** Fetch transcripts via `youtube-transcript-api`, cache to disk, return structured `TranscriptResult`. Wraps sync API in `asyncio.to_thread()`.

### Files to create

| File | Purpose |
|---|---|
| `youtubesynth/services/youtube_service.py` | `TranscriptResult` dataclass, `YouTubeService` class |
| `tests/fixtures/mock_transcripts/short_transcript.txt` | ~2,000 words (< 8k token threshold) |
| `tests/fixtures/mock_transcripts/long_transcript.txt` | ~20,000 words (> 8k token threshold) |
| `tests/unit/test_youtube_service.py` | Mocks `YouTubeTranscriptApi` — no network calls |

**`YouTubeService` key methods:**

```python
async def get_transcript(video_id: str) -> TranscriptResult
async def get_transcript_batch(video_ids: list[str], semaphore: asyncio.Semaphore) -> list[TranscriptResult]
```

**Cache file format** (`{cache_dir}/{video_id}.txt`):
```
# transcript_type: manual
# language: en
Hello and welcome to this tutorial...
```

**`transcript_type` values:** `"manual"` | `"auto-generated"` | `"unavailable"`

Returns `transcript_type="unavailable"` (instead of raising) when no transcript exists.

### How to test Phase 4

```bash
pytest tests/unit/test_youtube_service.py -v
# Expected: 7+ tests, all PASSED
# Tests: cache_hit, cache_miss_calls_api, manual_type, auto_generated_type,
#        no_transcript_returns_unavailable, cache_file_format, no_cache_flag
```

---

## Phase 5 — Gemini Client and Token Tracker

**Goal:** Async Gemini wrapper with exponential backoff retry; cost computation, DB-backed token ledger, and **pre-run cost estimation** before any Gemini calls are made.

### Files to create

| File | Purpose |
|---|---|
| `youtubesynth/services/gemini_client.py` | `GeminiResponse` dataclass, `GeminiClient` class, factory functions |
| `youtubesynth/services/token_tracker.py` | `PRICING` constants, `CostEstimate` dataclass, `compute_cost()`, `estimate_cost()`, `TokenTracker` class |
| `tests/unit/test_gemini_client.py` | Mocks `genai` — tests retry logic, error handling |
| `tests/unit/test_token_tracker.py` | Tests cost math, estimation, DB insertion, report aggregation |

**Retry policy in `GeminiClient.generate()`:**
- Retry on: `ResourceExhausted`, `ServiceUnavailable`
- No retry on: `InvalidArgument` (raises immediately)
- Backoff: `2^attempt` seconds + jitter, max 5 retries → raises `GeminiError`
- Wraps sync `model.generate_content()` in `asyncio.to_thread()`

**Pricing constants:**
```python
PRICING = {
    "gemini-2.5-flash-lite": {"input": 0.10 / 1_000_000, "output": 0.40  / 1_000_000},
    "gemini-2.5-flash":      {"input": 0.30 / 1_000_000, "output": 2.50  / 1_000_000},
}
# Default flash model (summarizer): gemini-2.5-flash-lite
# Default pro model (synthesis):    gemini-2.5-flash
```

**`CostEstimate` dataclass** (used before any Gemini calls):
```python
@dataclass
class CostEstimate:
    flash_model: str
    pro_model: str
    summarizer_input_tokens: int     # sum of all transcript token counts
    summarizer_output_tokens: int    # projected at 25% of input
    chunk_summarizer_input_tokens: int   # tokens for any transcripts exceeding CHUNK_TOKEN_THRESHOLD
    chunk_summarizer_output_tokens: int
    synthesis_input_tokens: int      # projected as sum of estimated summary sizes
    synthesis_output_tokens: int     # fixed estimate (e.g. 3000 tokens)
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    by_agent: dict                   # same shape as TokenTracker.get_report()["by_agent"]
    available_count: int             # videos with transcripts (excludes "unavailable")
    unavailable_count: int
```

**`estimate_cost()` standalone function:**
```python
def estimate_cost(
    transcripts: list[TranscriptResult],
    flash_model: str,
    pro_model: str,
    chunk_token_threshold: int = 8000,
    output_ratio: float = 0.25,        # projected output = input * output_ratio
    synthesis_output_tokens: int = 3000,
) -> CostEstimate:
    """
    Tokenize transcripts with tiktoken cl100k_base; project output tokens;
    return full CostEstimate without making any API calls.
    """
```

**`TokenTracker.get_report()` output shape:**
```json
{
  "job_id": "...",
  "total_input_tokens": 85000,
  "total_output_tokens": 12000,
  "total_cost_usd": 0.0412,
  "by_agent": {
    "summarizer":       {"input_tokens": 70000, "output_tokens": 9000, "cost_usd": 0.0327},
    "synthesis":        {"input_tokens": 12000, "output_tokens": 3000, "cost_usd": 0.0073},
    "chunk_summarizer": {"input_tokens":  3000, "output_tokens":  200, "cost_usd": 0.0012}
  },
  "by_video": [...]
}
```

### How to test Phase 5

```bash
pytest tests/unit/test_gemini_client.py tests/unit/test_token_tracker.py -v
# Expected: 12+ tests, all PASSED
# gemini_client: successful_generate, rate_limit_retries, max_retries_raises, invalid_arg_no_retry, token_counts
# token_tracker: compute_cost_flash, compute_cost_pro, record_inserts_to_db, get_report_aggregates,
#                estimate_cost_short_transcripts, estimate_cost_long_transcripts_triggers_chunking,
#                estimate_cost_excludes_unavailable
```

---

## Phase 6 — Agent 1: Transcript Summarizer

**Goal:** Per-video summarization with chunking for long transcripts. Concurrent batch via `asyncio.Semaphore`. Accepts pre-fetched `TranscriptResult` objects so that `pipeline.py` can fetch all transcripts, estimate cost, confirm with the user, and then summarize — without re-fetching.

### Files to create

| File | Purpose |
|---|---|
| `youtubesynth/agents/base_agent.py` | Abstract `BaseAgent(ABC)` with injected `db`, `token_tracker`, `gemini_client` |
| `youtubesynth/agents/transcript_summarizer.py` | `TranscriptSummarizer` — single video + batch processing |
| `tests/unit/test_transcript_summarizer.py` | Mocks YouTube + Gemini — tests all code paths |

**`TranscriptSummarizer` key methods:**

```python
# Summarize one video using a pre-fetched transcript (no re-fetch).
async def summarize_video(
    job_id: str,
    video: VideoMeta,
    transcript: TranscriptResult,      # pre-fetched by pipeline before confirmation
) -> Optional[str]

# Summarize a batch using pre-fetched transcripts.
async def summarize_batch(
    job_id: str,
    videos: list[VideoMeta],
    transcripts: list[TranscriptResult],   # parallel list, same order as videos
    semaphore: asyncio.Semaphore,
) -> list[Optional[str]]
```

> **Why pre-fetched transcripts?** The pipeline fetches all transcripts first, calls `estimate_cost()`,
> shows the user the cost breakdown, and waits for confirmation. Only after confirmation does it call
> `summarize_batch()`. Passing transcripts in avoids a redundant second network fetch.

**Chunking flow** (when transcript > `CHUNK_TOKEN_THRESHOLD` tokens):
```
long transcript
  ├── chunk 1 → Gemini Flash (agent="chunk_summarizer") → chunk summary 1
  ├── chunk 2 → Gemini Flash (agent="chunk_summarizer") → chunk summary 2
  └── chunk N → ...
                    ↓
        merge all chunk summaries → Gemini Flash → final video summary
```

**Token counting:** `tiktoken` with `"cl100k_base"` encoding (proxy for Gemini token counts).

**SSE emitter:** Injected optional `ProgressEmitter` protocol:
```python
class ProgressEmitter(Protocol):
    async def emit(self, job_id: str, event: str, data: dict) -> None: ...
```

**Prompt constants:** `SUMMARIZE_PROMPT`, `CHUNK_SUMMARIZE_PROMPT`, `MERGE_CHUNKS_PROMPT` (verbatim from spec).

**Summary file path:** `summaries/{job_id}/{video_id}.md`

### How to test Phase 6

```bash
pytest tests/unit/test_transcript_summarizer.py -v
# Expected: 8+ tests, all PASSED
# Tests: short_transcript_direct, long_transcript_chunked, unavailable_skipped,
#        summary_file_written, token_usage_recorded, sse_events_emitted,
#        batch_handles_failures, summarize_video_accepts_prefetched_transcript
```

---

## Phase 7 — Agent 2: Synthesis Agent

**Goal:** Read all per-video summaries for a job → call Gemini Pro → write `result.md` + `token_report.json`.

> **Note on cost estimation:** The upfront `CostEstimate` produced in Phase 5 already includes a projected synthesis cost (using estimated summary token sizes and the Pro model pricing). The `SynthesisAgent` itself does not re-estimate — it simply proceeds after the user has already confirmed in Phase 8/9.

### Files to create

| File | Purpose |
|---|---|
| `youtubesynth/agents/synthesis_agent.py` | `SynthesisAgent` — reads summaries, synthesizes, writes output |
| `tests/unit/test_synthesis_agent.py` | Mocks Gemini — tests file I/O, DB updates, SSE events |

**`SynthesisAgent.synthesize()` steps:**
1. Read all `summaries/{job_id}/{video_id}/*.md` files
2. Write `output/{job_id}/transcripts.md` — all per-video summaries concatenated with `---` separators
3. Emit `synthesis_start` SSE event
4. Format `SYNTHESIS_PROMPT` with style, num_videos, concatenated summaries
5. Call Gemini Pro
6. Write `output/{job_id}/overall_summary.md`
7. Record token usage with `agent="synthesis"`, `video_id=None`
8. Call `token_tracker.write_report()` → `output/{job_id}/token_report.json`
9. Update job status to `"done"` in DB
10. Emit `job_done` SSE event

Raises `SynthesisError` if no summary files exist.

**Output files written by SynthesisAgent:**
```
output/{job_id}/
├── overall_summary.md    ← synthesis result (formerly result.md)
├── transcripts.md        ← all per-video summaries combined
└── token_report.json
```

### How to test Phase 7

```bash
pytest tests/unit/test_synthesis_agent.py -v
# Expected: 7+ tests, all PASSED
# Tests: reads_all_summary_files, result_written, token_agent_is_synthesis,
#        token_report_written, sse_events, empty_summaries_raises, job_status_done
```

---

## Phase 8 — CLI Entry Point (End-to-End Pipeline)

**Goal:** `youtubesynth --input file.txt` runs the full pipeline with human-readable stdout progress, including a cost estimation step and interactive confirmation before any Gemini calls are made.

### Files to create

| File | Purpose |
|---|---|
| `youtubesynth/pipeline.py` | `run_pipeline()` async function — composition root shared by CLI and API |
| `youtubesynth/cli.py` | Full implementation replacing the Phase 1 stub |
| `tests/unit/test_cli.py` | Tests arg parsing, error cases, KeyboardInterrupt, confirmation prompt |

**`pipeline.py` — two-phase execution flow:**

```
Phase A — Transcript fetch (no Gemini calls):
  1. create_job() in DB (status = "fetching")
  2. upsert_video_progress(pending) for all videos
  3. YouTubeService.get_transcript_batch() — fetch all transcripts concurrently
  4. estimate_cost(transcripts, flash_model, pro_model)
  5. call confirmation_callback(estimate) → bool
     • if False → update_job_status("cancelled"); return early
  6. update_job_status("running")

Phase B — Summarize + Synthesize (Gemini calls):
  7. TranscriptSummarizer.summarize_batch(videos, transcripts, semaphore)
  8. SynthesisAgent.synthesize()
```

**`pipeline.py` signature:**
```python
async def run_pipeline(
    job_id: str,
    videos: list[VideoMeta],
    style: str,
    title: Optional[str],
    output_dir: str,
    concurrency: int,
    no_cache: bool,
    db: Database,
    progress_callback: Optional[ProgressEmitter] = None,
    confirmation_callback: Optional[ConfirmationEmitter] = None,
) -> PipelineResult:
    ...
```

**`ConfirmationEmitter` protocol** (defined in `pipeline.py`, shared by CLI and API):
```python
class ConfirmationEmitter(Protocol):
    async def confirm(self, job_id: str, estimate: CostEstimate) -> bool:
        """Return True to proceed, False to cancel."""
        ...
```

- **CLI:** `CLIConfirmationEmitter` — prints the estimate table to stdout, reads `y/N` from stdin (or auto-confirms if `--yes` passed)
- **API:** `APIConfirmationEmitter` — emits `confirmation_required` SSE event, then waits on a per-job `asyncio.Event` that is set when `POST /api/jobs/{job_id}/confirm` (or `/cancel`) is called

**`PipelineResult`** gains a `cancelled: bool` field. When cancelled, `result.md` is not written.

**Job status transitions (updated):**
```
pending → fetching → pending_confirmation → running → done / failed
                                          ↘ cancelled
```

**CLI argument reference:**

| Argument | Short | Default | Notes |
|---|---|---|---|
| `--input PATH` | `-i` | — | Mutually exclusive with `--playlist` |
| `--playlist URL` | `-p` | — | Mutually exclusive with `--input` |
| `--style` | `-s` | `article` | `tutorial` \| `article` \| `guide` |
| `--title TEXT` | `-t` | Auto | Title for synthesized output |
| `--output-dir PATH` | `-o` | `./output` | Overrides `OUTPUT_DIR` for this run only |
| `--max-videos N` | | `50` | |
| `--concurrency N` | | `3` | Max concurrent Gemini calls |
| `--no-cache` | | false | Bypass transcript cache |
| `--verbose` | `-v` | false | Per-video progress lines |
| `--yes` | `-y` | false | Skip cost confirmation prompt and proceed automatically |

**Expected stdout (with confirmation prompt):**
```
[youtubesynth] Extracting URLs...  12 videos found
[youtubesynth] Fetching transcripts...  11 fetched, 1 unavailable

Estimated API cost:
  Summarization  (gemini-2.5-flash-lite):  ~420,000 input / ~105,000 output  →  $0.084
  Synthesis      (gemini-2.5-flash):         ~30,000 input /   ~3,000 output  →  $0.017
  ──────────────────────────────────────────────────────────────────────────────────────
  Total estimated cost:                                                          ~$0.101

Proceed? [y/N] y

[youtubesynth] Summarizing videos (3 concurrent)...
  [ 1/12] ✓ "Intro to Transformers"              (manual transcript, 1,240 tokens)
  [ 2/12] ✓ "Attention Walkthrough"               (auto-generated, 3,400 tokens)
  [ 3/12] ✗ "Deleted video"                       (no transcript — skipped)
[youtubesynth] Synthesizing 11 summaries → gemini-2.5-flash...
[youtubesynth] Done.

Output     : output/a3f1c2d4/overall_summary.md
Transcripts: output/a3f1c2d4/transcripts.md
Report     : output/a3f1c2d4/token_report.json
Cost       : $0.098 (actual)
```

If the user answers `N` (or hits Ctrl+C at the prompt):
```
[youtubesynth] Aborted. No Gemini calls were made.
```

### How to test Phase 8

```bash
youtubesynth --help
# Expected: full argument listing including --yes

GEMINI_API_KEY="" youtubesynth --input tests/fixtures/sample_videos.txt
# Expected: "Error: GEMINI_API_KEY is not set..."

youtubesynth --input f.txt --playlist https://youtube.com/playlist?list=PL123
# Expected: argparse error: not allowed with argument --input

pytest tests/unit/test_cli.py -v
# Tests: args_parsed, missing_api_key_error, mutual_exclusion_error,
#        yes_flag_skips_confirmation, no_answer_cancels_job,
#        keyboard_interrupt_handled

# Live end-to-end test (requires real GEMINI_API_KEY + network):
youtubesynth --input tests/fixtures/sample_videos.txt --max-videos 2 --verbose --yes
# Expected: estimate printed, auto-confirmed, result.md + token_report.json written
```

---

## Phase 9 — FastAPI Web Server and SSE Streaming

**Goal:** Full REST API. Pipeline runs as a background task. SSE streams real-time progress to clients, including a `confirmation_required` event that pauses the pipeline until the client calls `/confirm` or `/cancel`.

### Files to create

| File | Purpose |
|---|---|
| `youtubesynth/api/schemas.py` | Pydantic v2 models for all request/response shapes |
| `youtubesynth/api/sse.py` | `SSEManager` — per-job `asyncio.Queue`, `emit()`, `stream_events()`; per-job `asyncio.Event` for confirmation gate |
| `youtubesynth/api/routes.py` | All eight endpoints |
| `youtubesynth/main.py` | Full FastAPI app with `lifespan` for DB connection |
| `tests/unit/test_api.py` | `httpx.AsyncClient` with `ASGITransport`, mocked pipeline |

**DB status values** (updated for this phase — add to `db.py` schema comment):
```
pending → fetching → pending_confirmation → running → done / failed
                                          ↘ cancelled
```

**API endpoints:**

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/config` | Returns `{"has_server_key": bool}` — used by frontend Sidebar |
| `POST` | `/api/jobs` | Submit job (multipart: `file` or `playlist_url`, `style`, `title`, `max_videos`) |
| `GET` | `/api/jobs/{job_id}/stream` | SSE progress stream |
| `GET` | `/api/jobs/{job_id}` | Poll job status |
| `POST` | `/api/jobs/{job_id}/confirm` | Confirm cost estimate → pipeline proceeds to summarization |
| `POST` | `/api/jobs/{job_id}/cancel` | Cancel after cost estimate → pipeline aborts cleanly |
| `GET` | `/api/jobs/{job_id}/result` | Get synthesized content + token report (JSON) |
| `GET` | `/api/jobs/{job_id}/download` | Download `overall_summary.md` |
| `GET` | `/api/jobs/{job_id}/transcripts` | Download `transcripts.md` |
| `GET` | `/api/jobs/{job_id}/token-report` | Download `token_report.json` |

**`POST /api/jobs` response** (updated to include cost estimate when transcripts are ready):
```json
{
  "job_id": "a3f1c2d4",
  "status": "fetching",
  "video_count": 12
}
```
The cost estimate arrives later as the `confirmation_required` SSE event (the pipeline fetches transcripts asynchronously in the background before pausing for confirmation).

**`POST /api/jobs/{job_id}/confirm` response:**
```json
{ "job_id": "a3f1c2d4", "status": "running" }
```
Returns `409 Conflict` if job is not in `pending_confirmation` status.

**`POST /api/jobs/{job_id}/cancel` response:**
```json
{ "job_id": "a3f1c2d4", "status": "cancelled" }
```

**`APIConfirmationEmitter`** (in `api/sse.py`):
```python
class APIConfirmationEmitter:
    """Emits confirmation_required SSE event; blocks until /confirm or /cancel called."""
    async def confirm(self, job_id: str, estimate: CostEstimate) -> bool:
        await sse_manager.emit(job_id, "confirmation_required", estimate_to_dict(estimate))
        await db.update_job_status(job_id, "pending_confirmation")
        result = await sse_manager.wait_for_confirmation(job_id)  # blocks on asyncio.Event
        return result  # True = confirmed, False = cancelled
```

**SSE event shapes** (updated):
```json
{ "event": "job_started",             "data": { "job_id": "...", "total_videos": 20 } }
{ "event": "confirmation_required",   "data": { "job_id": "...", "estimate": {
    "available_count": 11,
    "unavailable_count": 1,
    "summarizer_input_tokens": 420000,
    "summarizer_output_tokens": 105000,
    "synthesis_input_tokens": 30000,
    "synthesis_output_tokens": 3000,
    "total_cost_usd": 0.101,
    "by_agent": { "summarizer": {...}, "synthesis": {...} }
  }
}}
{ "event": "video_started",           "data": { "job_id": "...", "video_id": "...", "title": "...", "index": 3, "total": 20 } }
{ "event": "video_done",              "data": { "job_id": "...", "video_id": "...", "transcript_type": "auto-generated", "tokens_used": 1200 } }
{ "event": "video_failed",            "data": { "job_id": "...", "video_id": "...", "error": "No transcript available" } }
{ "event": "synthesis_start",         "data": { "job_id": "...", "summary_count": 18 } }
{ "event": "job_done",                "data": { "job_id": "...", "output_path": "...", "total_cost_usd": 0.042 } }
{ "event": "job_cancelled",           "data": { "job_id": "..." } }
{ "event": "job_failed",              "data": { "job_id": "...", "error": "..." } }
```

### How to test Phase 9

```bash
pytest tests/unit/test_api.py -v
# Expected: 10+ tests
# submit_202, playlist_url, both_inputs_422,
# get_status, not_found_404, result_not_done_404,
# sse_emits_confirmation_required, confirm_returns_running,
# cancel_returns_cancelled, confirm_on_wrong_status_409,
# sse_closes_on_job_done, sse_closes_on_cancelled

uvicorn youtubesynth.main:app --reload --port 8000

curl -s http://localhost:8000/health
# Expected: {"status":"ok"}

curl -s -X POST http://localhost:8000/api/jobs \
  -F "file=@tests/fixtures/sample_videos.txt" -F "style=article"
# Expected: {"job_id":"...","status":"fetching","video_count":2}

# In a second terminal, watch the SSE stream (will pause at confirmation_required):
curl -N http://localhost:8000/api/jobs/{job_id}/stream

# Confirm from a third terminal:
curl -s -X POST http://localhost:8000/api/jobs/{job_id}/confirm
# Expected: {"job_id":"...","status":"running"}
# SSE stream resumes with video_started events...

# Or cancel:
curl -s -X POST http://localhost:8000/api/jobs/{job_id}/cancel
# Expected: {"job_id":"...","status":"cancelled"}
# SSE stream closes with job_cancelled event
```

---

## Phase 10 — Integration Tests and Fixture Completion

**Goal:** Full pipeline test with mocked external services. All 80+ tests pass from a clean checkout. Confirmation step is auto-confirmed in integration tests via a mock `ConfirmationEmitter`.

### Files to create

| File | Purpose |
|---|---|
| `tests/fixtures/mock_summaries/` | Pre-written `.md` summary files per fixture video ID |
| `tests/integration/test_full_pipeline.py` | End-to-end `run_pipeline()` test with mocked YouTube + Gemini |
| `tests/integration/test_api_pipeline.py` | Submit via API, poll to completion, verify result endpoint |

**Confirmation handling in integration tests:**

```python
# Auto-confirming stub used in all pipeline integration tests
class AutoConfirmEmitter:
    async def confirm(self, job_id: str, estimate: CostEstimate) -> bool:
        return True  # always proceed

# Cancelling stub used in cancellation test
class AutoCancelEmitter:
    async def confirm(self, job_id: str, estimate: CostEstimate) -> bool:
        return False
```

**Integration test assertions for `test_full_pipeline.py`:**
- Cost estimate is produced before any Gemini calls (`estimate.total_cost_usd > 0`)
- `estimate.available_count` matches number of non-unavailable transcripts
- `output/{job_id}/result.md` exists and has content (when confirmed)
- `output/{job_id}/token_report.json` is valid JSON with `job_id`, `total_cost_usd`, `by_agent`
- `by_agent` contains `summarizer` and `synthesis` keys
- DB job status is `"done"`, `done_videos == len(videos)`
- All DB video statuses are `"done"`
- `summaries/{job_id}/` contains one `.md` file per successful video
- Unavailable transcript: video skipped, others continue, job status still `"done"`
- Long transcript: `chunk_summarizer` agent appears in `by_agent` (chunking triggered)
- **Cancellation test:** user cancels at confirmation → job status is `"cancelled"`, no `result.md`, zero Gemini calls made

**Integration test assertions for `test_api_pipeline.py`:**
- SSE stream emits `confirmation_required` event with valid `estimate` payload
- `POST /confirm` transitions job to `running` and SSE resumes
- `POST /cancel` transitions job to `cancelled`, SSE closes with `job_cancelled`
- `POST /confirm` on a non-`pending_confirmation` job returns `409`

### How to test Phase 10

```bash
pytest tests/ -v --tb=short
# Expected: 80+ tests, all PASSED across unit + integration suites

pytest tests/ --cov=youtubesynth --cov-report=term-missing
# Target: > 80% coverage
```

---

## Architectural Decisions

### 1. Dependency Injection over Module-Level Singletons

`pipeline.py` is the composition root. `Database`, `YouTubeService`, `GeminiClient`, and `TokenTracker` are constructed once per run and injected downward. This makes every unit test trivially mockable without patching module globals.

### 2. Shared SSE Emitter Protocol

Both CLI and API need progress reporting through different channels:

```python
class ProgressEmitter(Protocol):
    async def emit(self, job_id: str, event: str, data: dict) -> None: ...
```

- **CLI:** `CLIProgressEmitter` — prints formatted lines to stdout
- **API:** `SSEManager` instance — puts events on per-job `asyncio.Queue`

Agents accept `Optional[ProgressEmitter]` — silent when `None`.

### 3. Sync → Async Wrapping

Both `youtube-transcript-api` and `google-generativeai` are synchronous libraries. Wrap blocking calls with `asyncio.to_thread()` to avoid blocking the event loop.

### 4. Resume Logic

Before summarizing a video, check:
1. DB `video_progress.status == "done"` for this `(job_id, video_id)`
2. Summary file exists at `summaries/{job_id}/{video_id}.md`

If both are true, skip that video. This makes the pipeline restartable after interruption (Ctrl+C or crash) without re-fetching or re-summarizing already-completed videos.

### 5. Max Videos Guard

`POST /api/jobs` and `extract_urls()` both enforce `MAX_VIDEOS_PER_JOB`. If exceeded, return a clear error before any processing starts.

### 6. Cost Confirmation Gate

The pipeline is split into two phases to allow the user to see the estimated cost and confirm before any Gemini API calls are made:

**Phase A (free):** Extract URLs → fetch all transcripts from YouTube → tokenize with `tiktoken` → compute `CostEstimate` → present to user.

**Phase B (paid):** After confirmation → summarize transcripts → synthesize → write output.

The confirmation mechanism is injected as a `ConfirmationEmitter` protocol, keeping agents and `pipeline.py` unaware of whether they are running in CLI or API mode:
- **CLI:** Prints a formatted cost breakdown table to stdout; reads `y/N` from stdin (bypassed with `--yes`)
- **API:** Emits `confirmation_required` SSE event with the estimate payload; blocks on an `asyncio.Event` until `POST /confirm` or `POST /cancel` is received

If cancelled, the job status is set to `"cancelled"` in the DB and `pipeline.py` returns early. No summaries or output files are written.

---

## Complete File Manifest

```
Phase 1 — Scaffolding
├── pyproject.toml
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── youtubesynth/__init__.py
├── youtubesynth/config.py
├── youtubesynth/exceptions.py
├── youtubesynth/cli.py                    (stub → full in Phase 8)
├── youtubesynth/main.py                   (stub → full in Phase 9)
├── youtubesynth/extractors/__init__.py
├── youtubesynth/agents/__init__.py
├── youtubesynth/services/__init__.py
├── youtubesynth/api/__init__.py
└── tests/{__init__,unit/__init__,integration/__init__}.py

Phase 2 — Extractors
├── youtubesynth/extractors/url_validator.py
├── youtubesynth/extractors/xml_extractor.py
├── youtubesynth/extractors/json_extractor.py
├── youtubesynth/extractors/txt_extractor.py
├── youtubesynth/extractors/playlist_extractor.py
├── tests/fixtures/sample_videos.{xml,json,txt}
└── tests/unit/{test_url_validator,test_extractors}.py

Phase 3 — Database
├── youtubesynth/services/db.py
└── tests/unit/test_db.py

Phase 4 — YouTube Service
├── youtubesynth/services/youtube_service.py
├── tests/fixtures/mock_transcripts/short_transcript.txt
├── tests/fixtures/mock_transcripts/long_transcript.txt
└── tests/unit/test_youtube_service.py

Phase 5 — Gemini Client + Token Tracker
├── youtubesynth/services/gemini_client.py
├── youtubesynth/services/token_tracker.py
└── tests/unit/{test_gemini_client,test_token_tracker}.py

Phase 6 — Agent 1: Summarizer
├── youtubesynth/agents/base_agent.py
├── youtubesynth/agents/transcript_summarizer.py
└── tests/unit/test_transcript_summarizer.py

Phase 7 — Agent 2: Synthesis
├── youtubesynth/agents/synthesis_agent.py
└── tests/unit/test_synthesis_agent.py

Phase 8 — CLI + Pipeline
├── youtubesynth/pipeline.py               (ConfirmationEmitter protocol, two-phase run_pipeline)
├── youtubesynth/cli.py                    (full implementation + --yes flag + CLIConfirmationEmitter)
└── tests/unit/test_cli.py

Phase 9 — FastAPI + SSE
├── youtubesynth/api/schemas.py            (Pydantic v2 models: JobSubmitResponse, JobStatusResponse, etc.)
├── youtubesynth/api/sse.py                (SSEManager + per-job asyncio.Event confirmation gate + APIConfirmationEmitter)
├── youtubesynth/api/routes.py             (10 endpoints incl. /confirm, /cancel, /config, /transcripts)
├── youtubesynth/main.py                   (FastAPI app + lifespan DB + CORS + conditional StaticFiles)
└── tests/unit/test_api.py

Phase 10 — Integration Tests
├── tests/fixtures/mock_summaries/         (pre-written .md fixture files)
├── tests/integration/test_full_pipeline.py
└── tests/integration/test_api_pipeline.py

Phase 11 — Web Frontend
├── frontend/package.json                  (React 18, Vite 5, Tailwind 3; no react-markdown in final build)
├── frontend/vite.config.js               (proxy /api → :8000; build → youtubesynth/static/)
├── frontend/tailwind.config.js
├── frontend/postcss.config.js
├── frontend/index.html
├── frontend/src/main.jsx
├── frontend/src/index.css
├── frontend/src/App.jsx                   (state machine: form | progress | result)
├── frontend/src/components/Sidebar.jsx    (API key input; detects server key via GET /api/config)
├── frontend/src/components/UploadForm.jsx (file drag-drop or playlist URL; style/max-videos/title)
├── frontend/src/components/CostConfirmModal.jsx  (cost table; Proceed/Cancel; calls /confirm or /cancel)
├── frontend/src/components/ProgressPanel.jsx     (SSE consumer; 7 phases; renders CostConfirmModal)
└── frontend/src/components/ResultView.jsx        (token stats bar + 2 download cards; no inline render)
```

---

---

## Phase 11 — Web Frontend (React)

**Goal:** Browser-based UI matching the design mockup. File upload or playlist URL → real-time progress via SSE → **cost confirmation modal** → summarization progress → rendered markdown result with download.

**Depends on:** Phase 9 (FastAPI backend must be running). Build output is served as static files by FastAPI.

### Files created

| File | Purpose |
|---|---|
| `frontend/package.json` | React 18, Vite 5, Tailwind 3, react-markdown, remark-gfm |
| `frontend/vite.config.js` | Dev proxy `/api → http://localhost:8000`; build output → `youtubesynth/static/` |
| `frontend/tailwind.config.js` | `@tailwindcss/typography` plugin for prose rendering |
| `frontend/postcss.config.js` | Autoprefixer |
| `frontend/index.html` | Single-page app shell |
| `frontend/src/main.jsx` | React root mount |
| `frontend/src/index.css` | Tailwind directives + scrollbar styles |
| `frontend/src/App.jsx` | Top-level state machine: `form → fetching → confirming → progress → result` |
| `frontend/src/components/Sidebar.jsx` | API key input with show/hide toggle; persisted in `localStorage`; fetches `GET /api/config` on mount — shows `•••  from .env` + "Server key active" when server key is set, normal input otherwise |
| `frontend/src/components/UploadForm.jsx` | File chooser (drag-and-drop) OR playlist URL; style + max-videos selectors; submits `POST /api/jobs` |
| `frontend/src/components/CostConfirmModal.jsx` | Shown when `confirmation_required` SSE event arrives; displays cost breakdown table (Summarizer + Synthesis rows, token counts, USD); "Proceed" → `POST /confirm`, "Cancel" → `POST /cancel` |
| `frontend/src/components/ProgressPanel.jsx` | Connects to `GET /api/jobs/{id}/stream` SSE; phases: `fetching → confirming → summarizing → synthesizing → done / cancelled / failed`; renders `CostConfirmModal` on `confirmation_required`; shows amber cancellation message on `job_cancelled` |
| `frontend/src/components/ResultView.jsx` | Token cost stats bar; two download anchor cards: `overall_summary.md` and `transcripts.md`; no inline markdown rendering |

### Backend additions required for Phase 11

These are already implemented across `routes.py` and `main.py`:

1. **CORS middleware** (allows `http://localhost:3000` in dev):
```python
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"], allow_headers=["*"])
```

2. **`X-Gemini-Api-Key` header support** in `POST /api/jobs`:
```python
api_key = x_gemini_api_key or settings.gemini_api_key
```

3. **`GET /api/config`** endpoint — tells the frontend whether a server-side key is configured:
```python
@router.get("/config")
async def get_config() -> dict:
    return {"has_server_key": bool(settings.gemini_api_key)}
```

4. **`GET /api/jobs/{id}/transcripts`** endpoint — downloads `transcripts.md`.

5. **Static file serving** (conditional — only mounts if `youtubesynth/static/` exists):
```python
_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
```
Must be added **after** `app.include_router(router)` so API routes take precedence.

### UI flow (updated)

```
Sidebar       UploadForm          ProgressPanel          CostConfirmModal    ResultView
  │               │                     │                       │                │
  │ API key        │ POST /api/jobs       │ SSE stream opens      │                │
  │ in             │ → status: fetching   │                       │                │
  │ localStorage   │                     │ (transcript fetch      │                │
  │               │                     │  progress shown)       │                │
  │               │                     │                       │                │
  │               │                     │ confirmation_required  │ Cost breakdown │
  │               │                     │ ─────────────────────▶│ table shown    │
  │               │                     │                       │                │
  │               │                     │ POST /confirm ◀────── │ "Proceed" btn  │
  │               │                     │ POST /cancel  ◀────── │ "Cancel" btn   │
  │               │                     │                       │                │
  │               │                     │ per-video log rows    │                │
  │               │                     │ progress bar          │                │
  │               │                     │ synthesis spinner     │                │
  │               │                     │ job_done ─────────────────────────────▶│
  │               │                     │                       │  token stats    │
  │               │                     │ job_cancelled →       │  download cards │
  │               │                     │ "Cancelled" message   │  (2 .md files)  │
```

### How to test Phase 11

```bash
# Install dependencies
cd frontend && npm install

# Start backend (Phase 9 must be running)
uvicorn youtubesynth.main:app --reload --port 8000 &

# Start Vite dev server (proxies /api to port 8000)
npm run dev
# Open http://localhost:3000

# Manual test checklist:
# Sidebar
# [ ] If GEMINI_API_KEY in .env → field shows "•••••••••  from .env", status "Server key active"
# [ ] If no server key → normal editable input; entering key shows "API key saved"
# [ ] Key persists across page refreshes (localStorage)
# [ ] Eye icon toggles key visibility
#
# Upload form
# [ ] Choose a .txt/.xml/.json file → filename shown; playlist URL clears
# [ ] Enter playlist URL → file chooser clears
# [ ] Submit disabled until file or URL provided
# [ ] Style / max-videos / title options work
#
# Fetching + confirmation
# [ ] Click "GetTranscript and Summary" → "Fetching transcripts…" spinner shown
# [ ] Cost confirmation modal appears (Summarizer + Synthesis rows, total USD, token counts)
# [ ] Modal shows correct available / unavailable video counts
# [ ] "Cancel" → panel shows "Job cancelled. No API calls were made."
# [ ] Resubmit → modal appears again; click "Proceed"
#
# Progress
# [ ] Per-video rows appear with correct total count
# [ ] Each row shows spinner while summarizing, ✓ when done, ✗ when failed
# [ ] Progress bar advances; failed count shown in red
# [ ] Synthesis spinner appears after all videos done
#
# Result view
# [ ] Token stats bar shows total cost, input/output tokens, per-agent costs
# [ ] "overall_summary.md" download card downloads the synthesized article
# [ ] "transcripts.md" download card downloads per-video summaries
# [ ] "New job" button resets to upload form

# Build for production (output → youtubesynth/static/)
npm run build

# Verify FastAPI serves the built frontend
curl http://localhost:8000/
# Expected: HTML of the React app (index.html)
```

---

## Critical Files

| File | Why It's Critical |
|---|---|
| [System-Design-v1.md](System-Design-v1.md) | Authoritative spec — prompts, SSE event shapes, CLI flags, pricing, DB schema |
| `youtubesynth/pipeline.py` | Composition root shared by CLI and API; interface must satisfy both callers |
| `youtubesynth/services/db.py` | All job state flows through here; must be solid before agents build on it |
| `youtubesynth/agents/transcript_summarizer.py` | Most complex file: chunking, concurrency, SSE emission, token tracking, error isolation |
| `youtubesynth/api/sse.py` | Bridges async background tasks to HTTP clients; timing of stream registration matters |
