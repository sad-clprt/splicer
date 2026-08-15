---
name: film
description: Film processing tools for YouTube recap creation
---

# Film Processing Skill

Interactive film processing tools for creating high-quality YouTube film recaps.

## Commands

You can invoke these commands by running the `splicer` CLI tool located at the project root.

### Film Management

```bash
# Create a new film
./splicer film create "Title" --source path/to/video.mp4 --year 2010 --director "Name"

# List films
./splicer film list
./splicer film list --status in_progress
./splicer film list --year 2020

# Get film info
./splicer film info <film_id>

# Delete film
./splicer film delete <film_id>
./splicer film delete <film_id> --remove-files
```

### Proxy Generation (480p transcode)

```bash
# Generate proxy
./splicer proxy generate <film_id>

# Poll job status
./splicer proxy poll <film_id> <job_id>

# Download result
./splicer proxy download <film_id> <s3_url>
```

### Audio Analysis (WhisperX)

```bash
# Analyze audio
./splicer audio analyze <film_id>
./splicer audio analyze <film_id> --source source

# Enrich with metadata
./splicer audio enrich <film_id>
```

### Knowledge Enrichment

```bash
# Enrich from external sources
./splicer knowledge enrich <film_id>
./splicer knowledge enrich <film_id> --sources tmdb,omdb
```

### Visual Analysis (Qwen3-VL)

```bash
# Analyze frames (TODO: add visual command group)
```

### Script Generation

```bash
# Generate script
./splicer script generate <film_id>
./splicer script generate <film_id> --style engaging --context "Focus on dreams"

# Regenerate with feedback
./splicer script regenerate <film_id> --feedback "Too technical, make it accessible"
```

### Text-to-Speech

```bash
# Generate voiceover
./splicer tts generate <film_id>
./splicer tts generate <film_id> --voice default --speed 1.0
```

### Video Assembly

```bash
# Assemble final video
./splicer assemble video <film_id>
./splicer assemble video <film_id> --source proxy
```

### Safety & Compliance

```bash
# Run safety check
./splicer safety check <film_id>
```

## Workflow

The CLI enables iterative, human-in-the-loop processing:

1. **Create film** - Add source video to library
2. **Generate proxy** - Create 480p version for analysis
3. **Analyze** - Run audio, visual, and knowledge enrichment
4. **Generate script** - Create voiceover narration
5. **Iterate** - Regenerate script with feedback until perfect
6. **TTS** - Convert script to voiceover audio
7. **Assemble** - Combine video, voiceover, effects
8. **Safety check** - Verify compliance before upload

## Film Structure

Each film lives in `films/{film_id}/`:

```
films/inception_2010/
├── manifest.json          # State tracking
├── source.mp4             # Original video
├── proxy.mp4              # 480p version
├── audio/
│   ├── transcript.json
│   └── enrichment.json
├── visual/
│   └── vlm_output.json
├── knowledge/
│   └── context.json
├── script/
│   ├── v1.md
│   ├── v2.md
│   └── final.md
├── voiceover/
│   └── full.mp3
└── output/
    ├── final.mp4
    └── safety_report.json
```

## Usage Tips

- Use `film list` to see all films and their status
- Use `film info <film_id>` to check pipeline progress
- Each tool updates both manifest.json and the index database
- Tools can be run in any order (non-linear workflow)
- Scripts can be regenerated multiple times with feedback

## Implementation Status

**Working:**
- Film management (create, list, info, delete)
- Database indexing and search
- Manifest tracking

**TODO:**
- RunPod integration for proxy, audio, visual, TTS
- External API integration for knowledge enrichment
- LLM integration for script generation
- MoviePy integration for assembly
- Safety API integration

All tools have scaffolding in place with clear TODO markers.
