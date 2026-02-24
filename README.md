# YouTubeSynth

Transform collections of YouTube videos into structured knowledge articles using a two-agent LLM pipeline.

Accepts a YouTube playlist URL or a bookmarks file (XML, JSON, TXT), fetches transcripts, summarizes each video with **Gemini Flash**, then synthesizes all summaries into a cohesive article or tutorial with **Gemini Pro**. Available as a **CLI tool**, a **REST API**, and a **React web UI**.

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
             │                      │                          │
             └──────────────────────▼──────────────────────────┘
                                    │
                         ┌──────────▼──────────┐
                         │    pipeline.py       │
                         │  (composition root)  │
                         └──────────┬───────────┘
                                    │
              ┌─────────────────────┼──────────────────────┐
              │                     │                      │
   ┌──────────▼──────────┐          │           ┌──────────▼──────────┐
   │   URL Extractor      │          │           │   SQLite DB          │
   │  (no LLM)            │          │           │  jobs               │
   │                      │          │           │  video_progress     │
   │  xml_extractor.py    │          │           │  token_usage        │
   │  json_extractor.py   │          │           └─────────────────────┘
   │  txt_extractor.py    │          │
   │  playlist_extractor  │          │
   │  (yt-dlp)            │          │
   └──────────┬───────────┘          │
              │ VideoMeta[]          │
              ▼                      │
   ┌──────────────────────┐          │
   │  Agent 1             │          │
   │  Transcript          │◄─────────┤
   │  Summarizer          │          │
   │                      │          │
   │  • Fetch transcript  │          │
   │    (youtube-         │          │
   │     transcript-api)  │          │
   │  • Disk cache        │          │
   │  • Chunk if > 8k tok │          │
   │  • Gemini Flash      │          │
   │  • asyncio.Semaphore │          │
   │    (3 concurrent)    │          │
   └──────────┬───────────┘          │
              │ summaries/           │
              │ {job_id}/            │
              │ {video_id}.md        │
              ▼                      │
   ┌──────────────────────┐          │
   │  Agent 2             │          │
   │  Synthesis Agent     │◄─────────┘
   │                      │
   │  • Read all .md      │
   │  • Gemini Pro        │
   │  • Write result.md   │
   │  • Write             │
   │    token_report.json │
   └──────────┬───────────┘
              │
              ▼
   ┌──────────────────────┐
   │  output/{job_id}/    │
   │  ├── result.md       │   ← synthesized article / tutorial / guide
   │  └── token_report    │   ← per-agent token usage and USD cost
   │       .json          │
   └──────────────────────┘
```

### Data flow summary

```
Input
  └─► URL Extractor ──► VideoMeta[]
                              │
                    ┌─────────┘  (per video, async concurrent)
                    │
                    ▼
            YouTube Transcript API
                    │ raw transcript text
                    ▼
            .cache/transcripts/{video_id}.txt   (disk cache)
                    │
                    ▼
            tiktoken: count tokens
                    │
              ┌─────┴────────┐
         ≤ 8k tokens    > 8k tokens
              │               │
              ▼               ▼
        Gemini Flash    chunk → Flash × N
        (direct)        → merge → Flash
              │               │
              └──────┬─────────┘
                     ▼
            summaries/{job_id}/{video_id}.md
                     │
          (all videos complete)
                     ▼
               Gemini Pro
            (single synthesis call)
                     │
                     ▼
            output/{job_id}/result.md
            output/{job_id}/token_report.json
```

### Component map

| Layer | Module | Responsibility |
|---|---|---|
| Extractors | `youtubesynth/extractors/` | Parse XML/JSON/TXT/playlist → `VideoMeta[]` |
| Services | `youtube_service.py` | Fetch + cache transcripts |
| Services | `gemini_client.py` | Async Gemini wrapper, retry + backoff |
| Services | `token_tracker.py` | Cost computation, DB ledger |
| Services | `db.py` | Async SQLite CRUD (aiosqlite) |
| Agents | `transcript_summarizer.py` | Agent 1 — per-video, Gemini Flash, chunking |
| Agents | `synthesis_agent.py` | Agent 2 — all summaries → Gemini Pro |
| Pipeline | `pipeline.py` | Composition root; shared by CLI + API |
| CLI | `cli.py` | `youtubesynth` console script |
| API | `api/routes.py` | FastAPI REST endpoints |
| API | `api/sse.py` | Per-job SSE event queues |
| Frontend | `frontend/src/` | React 18 + Vite + Tailwind web UI |

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

# Install the package (with dev extras for testing)
pip install -e ".[dev]"

# Copy and fill in the environment file
cp .env.example .env
# Edit .env — set GEMINI_API_KEY at minimum
```

---

## Usage

### Option A — Web UI (recommended)

Start the backend and frontend dev server:

```bash
# Terminal 1: backend
uvicorn youtubesynth.main:app --reload --port 8000

# Terminal 2: frontend
cd frontend
npm install
npm run dev
```

Open **http://localhost:3000**, enter your Gemini API key in the sidebar, then upload a file or paste a playlist URL.

### Option B — CLI

```bash
# From a text file (one URL per line)
youtubesynth --input videos.txt --style article --verbose

# From a YouTube playlist
youtubesynth --playlist "https://www.youtube.com/playlist?list=PLxxx" --style tutorial

# From an XML bookmarks export
youtubesynth --input bookmarks.xml --style guide --max-videos 20

# Custom output directory and title
youtubesynth --input videos.json --title "My ML Guide" --output-dir ./results
```

Result files are written to `output/{job_id}/`:
```
output/
└── a3f1c2d4/
    ├── result.md            # synthesized article
    └── token_report.json    # token usage and USD cost per agent
```

### Option C — REST API

```bash
# Submit a job
curl -X POST http://localhost:8000/api/jobs \
  -F "file=@videos.txt" \
  -F "style=article"
# → {"job_id":"a3f1c2d4","status":"pending","video_count":12}

# Stream real-time progress
curl -N http://localhost:8000/api/jobs/a3f1c2d4/stream

# Poll status
curl http://localhost:8000/api/jobs/a3f1c2d4

# Fetch result when done
curl http://localhost:8000/api/jobs/a3f1c2d4/result

# Download files
curl -O http://localhost:8000/api/jobs/a3f1c2d4/download
curl -O http://localhost:8000/api/jobs/a3f1c2d4/token-report
```

---

## CLI reference

| Argument | Short | Default | Description |
|---|---|---|---|
| `--input PATH` | `-i` | — | XML, JSON, or TXT file with video URLs |
| `--playlist URL` | `-p` | — | YouTube playlist URL |
| `--style` | `-s` | `article` | `tutorial` \| `article` \| `guide` |
| `--title TEXT` | `-t` | auto | Title for synthesized output |
| `--output-dir PATH` | `-o` | `./output` | Where to write result files |
| `--max-videos N` | | `50` | Cap number of videos |
| `--concurrency N` | | `3` | Max concurrent Gemini calls |
| `--no-cache` | | off | Bypass transcript cache |
| `--verbose` | `-v` | off | Per-video progress lines |

`--input` and `--playlist` are mutually exclusive; exactly one is required.

---

## Configuration (`.env`)

```bash
GEMINI_API_KEY=your_key_here          # required

# Models
SUMMARIZER_MODEL=gemini-1.5-flash
SYNTHESIS_MODEL=gemini-1.5-pro

# Concurrency
MAX_CONCURRENT_GEMINI_CALLS=3
YOUTUBE_FETCH_DELAY_SECONDS=1.0

# Chunking (tokens)
CHUNK_TOKEN_THRESHOLD=8000
CHUNK_SIZE_TOKENS=6000

# Guards
MAX_VIDEOS_PER_JOB=50

# Storage paths
CACHE_DIR=.cache/transcripts
SUMMARIES_DIR=summaries
OUTPUT_DIR=output
DB_PATH=.data/youtubesynth.db

LOG_LEVEL=INFO
```

---

## Testing

### Backend unit tests

```bash
# All unit tests (no network, no API key needed — all mocked)
pytest tests/unit/ -v

# By phase
pytest tests/unit/test_url_validator.py tests/unit/test_extractors.py -v   # Phase 2
pytest tests/unit/test_db.py -v                                             # Phase 3
pytest tests/unit/test_youtube_service.py -v                                # Phase 4
pytest tests/unit/test_gemini_client.py tests/unit/test_token_tracker.py -v # Phase 5
pytest tests/unit/test_transcript_summarizer.py -v                          # Phase 6
pytest tests/unit/test_synthesis_agent.py -v                                # Phase 7
pytest tests/unit/test_cli.py -v                                            # Phase 8
pytest tests/unit/test_api.py -v                                            # Phase 9
```

### Backend integration tests

```bash
# Full pipeline — mocked YouTube + Gemini, real filesystem + SQLite
pytest tests/integration/ -v
```

### Full test suite with coverage

```bash
pytest tests/ --cov=youtubesynth --cov-report=term-missing
# Target: > 80% coverage
```

---

## Testing the Frontend

### Prerequisites

```bash
# Backend must be running
uvicorn youtubesynth.main:app --reload --port 8000

# Install frontend dependencies (first time only)
cd frontend && npm install
```

### Development server

```bash
cd frontend
npm run dev
# Vite dev server starts at http://localhost:3000
# All /api requests are proxied to http://localhost:8000
```

### Manual test checklist

#### Sidebar — API key
- [ ] Enter a key → the green "API key saved" indicator appears
- [ ] Refresh the page → key is still present (persisted in `localStorage`)
- [ ] Click the eye icon → key toggles between masked and visible
- [ ] Clear the key → green indicator disappears

#### UploadForm — file input
- [ ] Click "Choose file" → native file picker opens, accepts `.xml`, `.json`, `.txt`
- [ ] Select a file → filename replaces "No file chosen"
- [ ] Drag and drop a file onto the zone → filename updates
- [ ] Click the `✕` next to the filename → clears the selection
- [ ] After selecting a file, type in the playlist URL field → file clears (inputs are mutually exclusive)
- [ ] Click "GetTranscript and Summary" without any input → button stays disabled

#### UploadForm — playlist URL
- [ ] Type a playlist URL → file chooser clears
- [ ] Clear the URL → submit button disables again

#### UploadForm — options
- [ ] Change "Output style" dropdown → persists until submission
- [ ] Change "Max videos" → accepts 1–200
- [ ] Enter a custom title → optional, can be left blank

#### UploadForm — submission
- [ ] Click "GetTranscript and Summary" → spinner appears in button, view switches to ProgressPanel
- [ ] Submit with an invalid/unreachable API key → error message shown in red below the form
- [ ] Submit with backend not running → network error shown

#### ProgressPanel — real-time progress
- [ ] "Connecting to job stream…" spinner appears immediately
- [ ] After `job_started` SSE event: list of pending video rows appears with correct total count
- [ ] After each `video_started` event: the corresponding row shows a spinner and the video title
- [ ] After each `video_done` event: row shows a green ✓, transcript type, and token count
- [ ] After each `video_failed` event: row shows a red ✕ and the error message (e.g., "No transcript available")
- [ ] Progress bar advances as videos complete
- [ ] Failed video count shown in red below the bar
- [ ] After all videos: "Synthesizing N summaries" panel appears with an indigo spinner
- [ ] Log area auto-scrolls as new rows arrive

#### ResultView — rendered output
- [ ] View switches automatically after `job_done` SSE event
- [ ] Synthesized markdown is rendered with correct headings, bullets, and code blocks
- [ ] Stats bar shows: total cost, input tokens, output tokens, summarizer cost, synthesis cost
- [ ] **Copy** button copies raw markdown to clipboard; button text briefly changes to "Copied!"
- [ ] **Download** button downloads `result.md` to local machine
- [ ] **New job** button resets to the UploadForm (entering API key is not required again)

### Build for production

```bash
cd frontend
npm run build
# Output written to youtubesynth/static/
# FastAPI serves it at http://localhost:8000/
```

Verify the production build is served:

```bash
uvicorn youtubesynth.main:app --port 8000
curl -s http://localhost:8000/ | grep -o '<title>.*</title>'
# Expected: <title>YouTubeSynth</title>
```

### Lint

```bash
cd frontend
npm run lint
```

---

## Project structure

```
youtube-bookmarks-summariser/
├── youtubesynth/
│   ├── config.py                      # Pydantic settings — reads .env
│   ├── exceptions.py                  # Custom exception hierarchy
│   ├── pipeline.py                    # Composition root (CLI + API share this)
│   ├── cli.py                         # youtubesynth console script
│   ├── main.py                        # FastAPI app + lifespan + static files
│   ├── extractors/
│   │   ├── url_validator.py           # VideoMeta, extract_video_id()
│   │   ├── xml_extractor.py
│   │   ├── json_extractor.py
│   │   ├── txt_extractor.py
│   │   └── playlist_extractor.py      # yt-dlp
│   ├── agents/
│   │   ├── base_agent.py
│   │   ├── transcript_summarizer.py   # Agent 1 — Gemini Flash
│   │   └── synthesis_agent.py         # Agent 2 — Gemini Pro
│   ├── services/
│   │   ├── db.py                      # Async SQLite (aiosqlite)
│   │   ├── youtube_service.py         # Transcript fetch + disk cache
│   │   ├── gemini_client.py           # API wrapper, exponential backoff
│   │   └── token_tracker.py           # Cost ledger
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
│           ├── Sidebar.jsx            # API key input (localStorage)
│           ├── UploadForm.jsx         # File / playlist URL submission
│           ├── ProgressPanel.jsx      # SSE consumer, per-video log
│           └── ResultView.jsx         # Markdown render, copy, download
├── tests/
│   ├── unit/                          # Phase-by-phase unit tests (all mocked)
│   ├── integration/                   # End-to-end pipeline tests (mocked I/O)
│   └── fixtures/
│       ├── sample_videos.{xml,json,txt}
│       └── mock_transcripts/
├── .cache/transcripts/                # Persistent transcript cache (gitignored)
├── summaries/                         # Intermediate per-video summaries (gitignored)
├── output/                            # Final results (gitignored)
├── .data/youtubesynth.db              # SQLite job state (gitignored)
├── .env.example
├── pyproject.toml
├── System-Design-v1.md
└── implementation-plan.md
```

---

## Output files

After a successful run:

```
output/{job_id}/
├── result.md              # Synthesized article — ready to publish
└── token_report.json      # Cost breakdown by agent and video
```

```json
{
  "job_id": "a3f1c2d4",
  "total_input_tokens": 85000,
  "total_output_tokens": 12000,
  "total_cost_usd": 0.0412,
  "by_agent": {
    "summarizer":       { "input_tokens": 70000, "output_tokens": 9000,  "cost_usd": 0.0327 },
    "synthesis":        { "input_tokens": 12000, "output_tokens": 3000,  "cost_usd": 0.0073 },
    "chunk_summarizer": { "input_tokens":  3000, "output_tokens":  200,  "cost_usd": 0.0012 }
  },
  "by_video": [
    { "video_id": "abc123", "title": "...", "input_tokens": 4200, "output_tokens": 600, "cost_usd": 0.0005, "transcript_type": "manual" }
  ]
}
```

---

## Implementation phases

See [implementation-plan.md](implementation-plan.md) for the full phased build plan with per-phase test commands.

| Phase | What gets built |
|---|---|
| 1 | Scaffolding, `pyproject.toml`, editable install |
| 2 | URL extractors (XML / JSON / TXT / playlist) |
| 3 | Async SQLite database layer |
| 4 | YouTube transcript service + disk cache |
| 5 | Gemini client (retry/backoff) + token tracker |
| 6 | Agent 1 — Transcript Summarizer (chunking, concurrency) |
| 7 | Agent 2 — Synthesis Agent |
| 8 | CLI entry point + shared pipeline |
| 9 | FastAPI REST API + SSE streaming |
| 10 | Integration tests |
| 11 | React web frontend |
