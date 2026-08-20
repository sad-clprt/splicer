# Splicer - Tool-Based Film Processing

Interactive, agent-assisted video processing pipeline for high-quality YouTube film recaps.

## Architecture

**Philosophy:** Quality over automation. Each stage is a callable tool that can be executed independently, allowing human-in-the-loop refinement and iteration.

## Project Structure

```
splicer/
├── films/                          # Film library (gitignored except index + manifests)
│   ├── index.db                    # SQLite index for discovery
│   ├── .gitignore                  # Track index.db and manifests, ignore media
│   └── {film_id}/                  # One directory per film
│       ├── manifest.json           # State, history, metadata
│       ├── source.mp4              # Original 1080p video
│       ├── proxy.mp4               # 480p for analysis
│       ├── audio/
│       │   ├── transcript.json     # WhisperX output
│       │   └── enrichment.json     # Audio analysis
│       ├── visual/
│       │   └── vlm_output.json     # Frame analysis (Qwen3-VL)
│       ├── knowledge/
│       │   └── context.json        # KB enrichment (cast, plot, themes)
│       ├── script/
│       │   ├── v1.md               # Script iterations
│       │   ├── v2.md
│       │   └── final.md
│       ├── voiceover/
│       │   ├── full.mp3            # Complete TTS output
│       │   └── segments/           # Individual clips
│       └── output/
│           ├── final.mp4           # Final assembled video
│           ├── versions/           # Previous versions
│           └── safety_report.json
│
├── lib/                            # Core library
│   ├── db.py                       # Films index database
│   ├── film_manager.py             # Film lifecycle management
│   └── tools/                      # Processing tools (TODO)
│       ├── proxy.py
│       ├── audio.py
│       ├── knowledge.py
│       ├── visual.py
│       ├── script.py
│       ├── tts.py
│       ├── assemble.py
│       └── safety.py
│
├── modal_app/                     # Modal endpoints (one per tool)
│   └── proxy.py                    # 1080p → 480p transcoding
│
├── handlers/                       # Deprecated: RunPod handlers removed
│   └── proxy/                      # (now Modal, kept as placeholder)
│
├── src/                            # Old pipeline (deprecated, stubs)
└── archive/                        # Archived FastAPI/Inngest code
```

## Film Database

### Index Database (`films/index.db`)

Fast search/discovery layer for finding films:

```python
from lib import db, film_manager

# Search by title
films = db.search_films(title="inception")

# Full-text search
films = db.search_films(query="nolan dream thriller")

# Filter by status
in_progress = db.search_films(status="in_progress")

# Get film location
film = db.get_film("inception_2010")
print(film["directory_path"])  # "inception_2010/"
```

### Manifest (`films/{film_id}/manifest.json`)

Detailed state per film:

```json
{
  "film_id": "inception_2010",
  "title": "Inception",
  "year": 2010,
  "status": {
    "proxy": {"status": "completed", "timestamp": "2026-08-15T18:00:00Z", "job_id": "abc123"},
    "audio": {"status": "completed", "timestamp": "2026-08-15T18:05:00Z"},
    "script": {"status": "completed", "version": 2, "timestamp": "2026-08-15T19:00:00Z"},
    "voiceover": {"status": "in_progress"},
    "assembly": {"status": "not_started"}
  },
  "history": [
    {"action": "created", "timestamp": "...", "details": {}},
    {"action": "proxy_completed", "timestamp": "...", "details": {"job_id": "abc123"}},
    {"action": "script_regenerated", "timestamp": "...", "details": {"reason": "pacing too slow"}}
  ],
  "files": {
    "source": "source.mp4",
    "proxy": "proxy.mp4"
  }
}
```

## Film Manager API

```python
from lib import film_manager

# Create new film
film_id = film_manager.create_film(
    title="Inception",
    year=2010,
    director="Christopher Nolan",
    source_path=Path("~/Downloads/inception.mp4"),
    tags=["sci-fi", "thriller"]
)

# Get film info
info = film_manager.get_film_info(film_id)

# Update stage status
film_manager.update_stage_status(
    film_id=film_id,
    stage="proxy",
    status="completed",
    details={"job_id": "abc123", "duration": 120}
)

# Get manifest
manifest = film_manager.get_manifest(film_id)

# Add to history
film_manager.add_history_entry(
    film_id=film_id,
    action="script_edited",
    details={"editor": "human", "changes": "improved pacing"}
)

# List all films
films = film_manager.list_films(status="in_progress")
```

## Tool-Based Workflow

Each pipeline component is a standalone tool that can be called independently:

### Example: Proxy Generation

```python
from lib.tools import proxy

# Submit transcode job
job_id = proxy.generate_proxy(film_id="inception_2010")

# Poll and download when ready
proxy_path = proxy.download_proxy(film_id="inception_2010", job_id=job_id)
```

### Example: Agent Workflow

```
User: "Start working on Inception - generate proxy and analyze audio"

Agent:
  1. Searches: db.search_films(title="inception")
  2. Calls: proxy.generate_proxy("inception_2010")
  3. Polls until complete
  4. Calls: proxy.download_proxy()
  5. Calls: audio.analyze_audio("inception_2010")
  6. Reports: "Proxy ready at 480p. Audio analysis found 3 key dialogue scenes..."

User: "Generate a script emphasizing the dream-within-dream concept"

Agent: Calls script.generate_script(film_id, context="emphasize dream layers")

User: "Too technical. Make it more accessible"

Agent: Regenerates with adjusted prompt, saves as script/v2.md
```

## Processing Tools (TODO)

Each tool operates independently and updates both manifest.json and index.db:

- **proxy** - FFmpeg/PyNvVideoCodec transcode to 480p via Modal (GPU)
- **audio** - WhisperX transcription + timing via Modal
- **knowledge** - External API enrichment (cast, plot, themes)
- **visual** - Qwen3-VL frame analysis via Modal
- **script** - OpenRouter/Claude script generation
- **tts** - Text-to-speech via Modal
- **assemble** - MoviePy video assembly
- **safety** - Content moderation check

## Modal Endpoints

GPU endpoints deployed on Modal (replaces RunPod):

- **proxy** - Video transcoding (CUDA-accelerated) via Modal Function + Volume
- **audio** - WhisperX (faster-whisper + alignment)
- **visual** - Qwen3-VL multimodal LLM
- **tts** - F5-TTS or similar

Each endpoint:
1. Triggered via `modal.Function.from_name().remote()` or `.spawn()`
2. Processes on Modal GPU (A10G/L4/A100 as needed, configurable timeout)
3. Reads/writes via Modal Volume (`/films`)
4. Returns metadata to caller; client updates manifest + index.db

## Development Status

### ✅ Completed
- Films directory structure
- SQLite index database with FTS
- Film manager API (create, search, update)
- Manifest schema and tracking
- Git ignore configuration

### 🚧 In Progress
- Tool implementations (proxy, audio, knowledge, visual, script, tts, assemble, safety)
- Modal endpoint for proxy (planning)

### 📋 TODO
- Remaining Modal endpoints (audio, visual, tts, safety)
- Agent integration layer
- CLI interface
- Full pipeline testing

## Migration Notes

This is a **complete architecture shift** from the old automated pipeline:

**Old:** `src/` - Sequential stage_*.py scripts, fully automated SQLite pipeline  
**New:** `lib/` - Tool-based, interactive, agent-assisted workflow

The `src/` directory is kept as backup during migration. Will be cleaned up after all tools are implemented and tested.
