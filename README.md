# YouTubeSynth

Transform collections of YouTube videos into structured knowledge articles using a two-agent LLM pipeline.

Accepts a YouTube playlist URL or a bookmarks file (XML, JSON, TXT), fetches transcripts, summarizes each video with **Gemini Flash**, then synthesizes all summaries into a cohesive article or tutorial with **Gemini Pro**. Available as a **CLI tool**, a **REST API**, and a **React web UI**.

---
# Demo


https://github.com/user-attachments/assets/5ec8d6ca-204f-4d9a-8388-32f19ed5ff22


---


## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              User interfaces                                │
│                                                                             │
│   ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────────┐  │
│   │   React Web UI   │   │   REST API        │   │   CLI (youtubesynth) │  │
│   │  (Vite / React)  │   │  POST /api/jobs   │   │  --input / --playlist│  │
│   │  localhost:3000  │   │  SSE  /stream     │   │  --style / --verbose │  │
│   └────────┬─────────┘   └────────┬──────────┘   └──────────┬───────────┘  │
│            │  HTTP + SSE          │  FastAPI                 │ asyncio.run  │
└────────────┼──────────────────────┼──────────────────────────┼─────────────┘
             └──────────────────────▼──────────────────────────┘
                                    │
                         ┌──────────▼──────────┐
                         │    pipeline.py       │
                         │  Phase A: fetch +    │
                         │  estimate + confirm  │
                         │  Phase B: summarize  │
                         │  + synthesize        │
                         └──────────┬───────────┘
                                    │
              ┌─────────────────────┼──────────────────────┐
              │                     │                      │
   ┌──────────▼──────────┐          │           ┌──────────▼──────────┐
   │   URL Extractor      │          │           │   SQLite DB          │
   │  xml / json / txt /  │          │           │  jobs               │
   │  playlist (yt-dlp)   │          │           │  video_progress     │
   └──────────┬───────────┘          │           │  token_usage        │
              │ VideoMeta[]          │           └─────────────────────┘
              ▼                      │
   ┌──────────────────────┐          │
   │  Agent 1             │◄─────────┤
   │  Transcript          │          │
   │  Summarizer          │          │
   │  • Fetch transcript  │          │
   │  • Disk cache        │          │
   │  • Chunk if > 8k tok │          │
   │  • Gemini Flash      │          │
   │  • 3 concurrent      │          │
   └──────────┬───────────┘          │
              ▼                      │
   ┌──────────────────────┐          │
   │  Agent 2             │◄─────────┘
   │  Synthesis Agent     │
   │  • Gemini Pro        │
   │  • overall_summary   │
   │  • transcripts.md    │
   │  • token_report.json │
   └──────────┬───────────┘
              ▼
   output/{job_id}/
   ├── overall_summary.md
   ├── transcripts.md
   └── token_report.json
```

### Pipeline phases

The pipeline is split into two phases to allow cost confirmation before any Gemini calls:

```
Phase A (free)
  fetch all transcripts → estimate cost → prompt user to confirm or cancel

Phase B (paid, only if confirmed)
  summarize each video (Gemini Flash) → synthesize (Gemini Pro)
```

Job status transitions: `pending → fetching → pending_confirmation → running → done / failed / cancelled`

---

## Requirements

- Python 3.10+
- Node.js 18+ (frontend only)
- A [Google AI Studio](https://aistudio.google.com) API key (free tier available)

---

## Installation

```bash
git clone <repo-url>
cd youtube-bookmarks-summariser

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows

# Install the package with all runtime and dev dependencies
pip install -e ".[dev]"

# Copy the environment template and set your API key
cp .env.example .env
# Edit .env — GEMINI_API_KEY is the only required field
```

---

## Configuration (`.env`)

```bash
# Required
GEMINI_API_KEY=your_key_here

# Optional — Gemini model names
GEMINI_MODEL_FLASH=gemini-2.5-flash-lite   # used for per-video summarization
GEMINI_MODEL_PRO=gemini-2.5-flash           # used for final synthesis

# Optional — storage paths
DB_PATH=.data/youtubesynth.db
CACHE_DIR=.cache/transcripts
OUTPUT_DIR=output

# Optional — limits
MAX_VIDEOS_PER_JOB=50
DEFAULT_CONCURRENCY=3
CHUNK_TOKEN_THRESHOLD=8000
```

All fields have defaults — only `GEMINI_API_KEY` is needed to run.

---

## Usage

### Option A — Web UI (recommended)

#### Development mode (two terminals)

```bash
# Terminal 1 — start the backend
source .venv/bin/activate
uvicorn youtubesynth.main:app --reload --port 8000

# Terminal 2 — start the frontend dev server
cd frontend
npm install          # first time only
npm run dev
# Open http://localhost:3000
```

The Vite dev server proxies all `/api` requests to the backend on port 8000.

#### Production mode (single server)

```bash
# Build the frontend (output goes to youtubesynth/static/)
cd frontend && npm run build && cd ..

# Start the backend — it serves the built UI at /
source .venv/bin/activate
uvicorn youtubesynth.main:app --port 8000
# Open http://localhost:8000
```

#### UI walkthrough

1. **Sidebar** — If `GEMINI_API_KEY` is set in `.env`, the key field shows `•••••••••••••  from .env` and no input is needed. Otherwise enter your key — it is stored in `localStorage` and never sent to the server.
2. **Upload form** — Choose a `.xml`, `.json`, or `.txt` bookmarks file (drag-and-drop supported) **or** paste a YouTube playlist URL. Set output style, max videos, and an optional title.
3. **Fetching** — The backend fetches all transcripts and estimates the Gemini cost.
4. **Cost confirmation modal** — Shows a breakdown table (Summarizer + Synthesis, token counts, USD cost). Click **Proceed** to continue or **Cancel** to abort (no API calls made if cancelled).
5. **Progress panel** — Real-time per-video rows with ✓ / ✗ icons and token counts as each video is summarized.
6. **Result view** — Shows token cost stats and two download buttons:
   - `overall_summary.md` — the synthesized article
   - `transcripts.md` — all per-video summaries combined

---

### Option B — CLI

```bash
# From a text file (one YouTube URL per line)
youtubesynth --input videos.txt --style article --verbose

# From a YouTube playlist
youtubesynth --playlist "https://www.youtube.com/playlist?list=PLxxx" --style tutorial

# From an XML browser bookmarks export
youtubesynth --input bookmarks.xml --style guide --max-videos 20

# Custom output directory and title; skip cost prompt
youtubesynth --input videos.json --title "My ML Guide" --output-dir ./results --yes

# Bypass transcript cache (re-fetch from YouTube)
youtubesynth --input videos.txt --no-cache
```

Output files are written to `output/{job_id}/`:

```
output/
└── a3f1c2d4/
    ├── overall_summary.md    ← synthesized article / tutorial / guide
    ├── transcripts.md        ← all per-video summaries combined
    └── token_report.json     ← token usage and USD cost per agent
```

#### CLI flags

| Flag | Short | Default | Description |
|---|---|---|---|
| `--input PATH` | `-i` | — | XML, JSON, or TXT file with video URLs |
| `--playlist URL` | `-p` | — | YouTube playlist URL |
| `--style` | `-s` | `article` | `article` \| `tutorial` \| `guide` |
| `--title TEXT` | `-t` | auto | Title for the synthesized output |
| `--output-dir PATH` | `-o` | `./output` | Directory to write result files |
| `--max-videos N` | | `50` | Cap number of videos processed |
| `--concurrency N` | | `3` | Max concurrent Gemini summarization calls |
| `--no-cache` | | off | Bypass transcript disk cache |
| `--yes` | `-y` | off | Skip cost confirmation prompt |
| `--verbose` | `-v` | off | Print per-video progress lines |

`--input` and `--playlist` are mutually exclusive; exactly one is required.

---

### Option C — REST API

Start the backend:

```bash
source .venv/bin/activate
uvicorn youtubesynth.main:app --reload --port 8000
```

#### Check if a server key is configured

```bash
curl http://localhost:8000/api/config
# {"has_server_key": true}
```

#### Submit a job

```bash
# From a file
curl -X POST http://localhost:8000/api/jobs \
  -H "X-Gemini-Api-Key: YOUR_KEY" \
  -F "file=@videos.txt" \
  -F "style=article" \
  -F "max_videos=20"

# From a playlist URL
curl -X POST http://localhost:8000/api/jobs \
  -H "X-Gemini-Api-Key: YOUR_KEY" \
  -F "playlist_url=https://www.youtube.com/playlist?list=PLxxx" \
  -F "style=tutorial" \
  -F "title=My Tutorial"

# → {"job_id":"a3f1c2d4","status":"fetching","video_count":12}
```

The `X-Gemini-Api-Key` header is optional if `GEMINI_API_KEY` is set in `.env`.

#### Stream real-time progress (SSE)

```bash
curl -N http://localhost:8000/api/jobs/a3f1c2d4/stream
```

Events emitted:

| Event | When |
|---|---|
| `confirmation_required` | Transcripts fetched; cost estimate ready |
| `job_started` | User confirmed; summarization begins |
| `video_started` | A video is being summarized |
| `video_done` | A video summary is complete |
| `video_failed` | A video had no transcript |
| `synthesis_start` | All summaries done; synthesis begins |
| `job_done` | Pipeline complete |
| `job_cancelled` | User cancelled at cost confirmation |
| `job_failed` | Unrecoverable error |

#### Confirm or cancel after cost estimate

```bash
# Poll status until pending_confirmation
curl http://localhost:8000/api/jobs/a3f1c2d4
# {"job_id":"a3f1c2d4","status":"pending_confirmation", ...}

# Confirm — unblocks the pipeline
curl -X POST http://localhost:8000/api/jobs/a3f1c2d4/confirm

# Cancel — aborts cleanly (no Gemini calls made)
curl -X POST http://localhost:8000/api/jobs/a3f1c2d4/cancel
```

#### Poll status

```bash
curl http://localhost:8000/api/jobs/a3f1c2d4
# {"job_id":"a3f1c2d4","status":"running","total_videos":12,"done_videos":5, ...}
```

#### Get result (after job is done)

```bash
curl http://localhost:8000/api/jobs/a3f1c2d4/result
# {"job_id":"a3f1c2d4","status":"done","output":"# My Article\n...","token_report":{...}}
```

#### Download files

```bash
# Download overall_summary.md
curl -O http://localhost:8000/api/jobs/a3f1c2d4/download

# Download transcripts.md
curl -O http://localhost:8000/api/jobs/a3f1c2d4/transcripts

# Download token_report.json
curl -O http://localhost:8000/api/jobs/a3f1c2d4/token-report
```

#### Full endpoint reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/config` | Returns `{"has_server_key": bool}` |
| `POST` | `/api/jobs` | Submit a job (multipart: `file` or `playlist_url`) |
| `GET` | `/api/jobs/{id}/stream` | SSE event stream |
| `GET` | `/api/jobs/{id}` | Poll job status |
| `POST` | `/api/jobs/{id}/confirm` | Confirm cost and start summarization |
| `POST` | `/api/jobs/{id}/cancel` | Cancel at confirmation stage |
| `GET` | `/api/jobs/{id}/result` | Get synthesized output + token report (JSON) |
| `GET` | `/api/jobs/{id}/download` | Download `overall_summary.md` |
| `GET` | `/api/jobs/{id}/transcripts` | Download `transcripts.md` |
| `GET` | `/api/jobs/{id}/token-report` | Download `token_report.json` |
| `GET` | `/health` | Health check |

---

## Output files

```
output/{job_id}/
├── overall_summary.md       ← synthesized article, tutorial, or guide
├── transcripts.md           ← all per-video summaries combined (with title + URL headers)
├── token_report.json        ← cost breakdown by agent
└── summaries/
    └── {job_id}/
        └── {video_id}.md    ← intermediate per-video summary files
```

Example `token_report.json`:

```json
{
  "job_id": "a3f1c2d4",
  "total_input_tokens": 85000,
  "total_output_tokens": 12000,
  "total_cost_usd": 0.0106,
  "by_agent": {
    "summarizer":       { "input_tokens": 70000, "output_tokens": 9000, "cost_usd": 0.0017 },
    "synthesis":        { "input_tokens": 12000, "output_tokens": 3000, "cost_usd": 0.0065 },
    "chunk_summarizer": { "input_tokens":  3000, "output_tokens":  200, "cost_usd": 0.0003 }
  }
}
```

---

## Testing

### Backend tests

```bash
source .venv/bin/activate

# All 143 tests (unit + integration)
pytest tests/ -v

# Unit tests only (no network, no API key — all mocked)
pytest tests/unit/ -v

# Integration tests (mocked YouTube + Gemini, real SQLite)
pytest tests/integration/ -v

# With coverage report
pytest tests/ --cov=youtubesynth --cov-report=term-missing
```

### Frontend build check

```bash
cd frontend
npm run build    # must complete without errors
npm run lint     # ESLint
```

### Manual UI test checklist

#### Sidebar — API key

- [ ] If `GEMINI_API_KEY` is in `.env`: field shows `•••••••••••••  from .env` and status shows "Server key active"
- [ ] If no server key: input is editable; entering a key shows "API key saved"
- [ ] Entered key persists across page refreshes (stored in `localStorage`)
- [ ] Eye icon toggles key visibility
- [ ] Entering a key in the UI overrides the server key for that session

#### Upload form

- [ ] "Choose file" opens native picker, accepts `.xml`, `.json`, `.txt`
- [ ] Drag and drop a file onto the zone updates the filename
- [ ] `✕` clears the file selection
- [ ] Entering a playlist URL clears the file (inputs are mutually exclusive)
- [ ] Submit button is disabled until a file or URL is provided
- [ ] Style selector: `article` / `tutorial` / `guide`
- [ ] Max videos: 1–200
- [ ] Optional title field

#### Cost confirmation modal

- [ ] Modal appears after transcripts are fetched (before any Gemini calls)
- [ ] Shows correct available / unavailable video counts
- [ ] Summarizer row shows Flash model name, token estimate, and cost
- [ ] Synthesis row shows Pro model name, token estimate, and cost
- [ ] Total cost is the sum of both rows
- [ ] **Cancel** → modal closes, panel shows "Job cancelled. No API calls were made."
- [ ] **Proceed** → modal closes, per-video progress begins

#### Progress panel

- [ ] "Fetching transcripts…" spinner shown while transcripts are being fetched
- [ ] After confirming: video rows appear with correct total count
- [ ] Each row shows index, title, and a spinner while summarizing
- [ ] Completed rows show green ✓, transcript type, and token count
- [ ] Failed rows show red ✗ and error message
- [ ] Progress bar advances as videos complete
- [ ] "Synthesizing N summaries" indigo panel appears after all videos done
- [ ] Log area auto-scrolls

#### Result view

- [ ] Stats bar shows: total cost, input tokens, output tokens, summarizer cost, synthesis cost
- [ ] `overall_summary.md` download card is present and downloads the file
- [ ] `transcripts.md` download card is present and downloads the file
- [ ] "New job" button resets to the upload form

---

## Project structure

```
youtube-bookmarks-summariser/
├── youtubesynth/
│   ├── config.py                      # Pydantic settings — reads .env
│   ├── exceptions.py                  # Custom exception hierarchy
│   ├── pipeline.py                    # Two-phase composition root (CLI + API share this)
│   ├── cli.py                         # youtubesynth console script
│   ├── main.py                        # FastAPI app + lifespan + static file serving
│   ├── extractors/
│   │   ├── url_validator.py           # VideoMeta, extract_video_id()
│   │   ├── xml_extractor.py
│   │   ├── json_extractor.py
│   │   ├── txt_extractor.py           # Reads prev line as title hint
│   │   └── playlist_extractor.py      # yt-dlp
│   ├── agents/
│   │   ├── base_agent.py
│   │   ├── prompts.py                 # All Gemini prompt templates
│   │   ├── transcript_summarizer.py   # Agent 1 — Gemini Flash, chunking
│   │   └── synthesis_agent.py         # Agent 2 — Gemini Pro
│   ├── services/
│   │   ├── db.py                      # Async SQLite (aiosqlite)
│   │   ├── youtube_service.py         # Transcript fetch + disk cache
│   │   ├── gemini_client.py           # Async wrapper, exponential backoff
│   │   └── token_tracker.py           # Cost estimation and ledger
│   ├── api/
│   │   ├── routes.py                  # All FastAPI endpoints
│   │   ├── sse.py                     # Per-job asyncio.Queue SSE manager
│   │   └── schemas.py                 # Pydantic v2 request/response models
│   └── static/                        # Built React app (npm run build output)
├── frontend/
│   ├── package.json
│   ├── vite.config.js                 # Proxy /api → :8000; build → ../youtubesynth/static
│   ├── tailwind.config.js
│   ├── index.html
│   └── src/
│       ├── App.jsx                    # State machine: form → progress → result
│       └── components/
│           ├── Sidebar.jsx            # API key input; detects server key via /api/config
│           ├── UploadForm.jsx         # File / playlist URL, style, max-videos
│           ├── CostConfirmModal.jsx   # Cost breakdown table; Proceed / Cancel
│           ├── ProgressPanel.jsx      # SSE consumer, per-video log, modal trigger
│           └── ResultView.jsx         # Token stats + download cards
├── tests/
│   ├── unit/                          # Per-phase unit tests (all mocked)
│   ├── integration/                   # End-to-end pipeline tests
│   └── fixtures/
│       ├── sample_videos.{xml,json,txt}
│       ├── mock_transcripts/
│       └── mock_summaries/
├── .env.example
├── pyproject.toml
├── System-Design-v1.md
└── implementation-plan.md
```

---

## Implementation phases

| Phase | What was built |
|---|---|
| 1 | Scaffolding, `pyproject.toml`, editable install |
| 2 | URL extractors (XML / JSON / TXT / playlist) |
| 3 | Async SQLite database layer |
| 4 | YouTube transcript service + disk cache |
| 5 | Gemini client (retry/backoff) + token tracker + cost estimation |
| 6 | Agent 1 — Transcript Summarizer (chunking, concurrency) |
| 7 | Agent 2 — Synthesis Agent |
| 8 | CLI entry point + two-phase pipeline |
| 9 | FastAPI REST API + SSE streaming + cost confirmation endpoints |
| 10 | Integration tests (full pipeline + API layer) |
| 11 | React web frontend (Vite + Tailwind + cost confirm modal) |
