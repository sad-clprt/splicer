"""Script generation via OpenRouter stronger model → 14-20 min voiceover.

- Input: Stage3 beats + KB metadata + audio enrichment
- Output: videos.script + script_hash + target_duration_sec (780-1200), plus TTS-ready segments.
"""

import hashlib
import json
import os
import pathlib
import tempfile

from dotenv import load_dotenv

load_dotenv()


def _openrouter_chat(prompt: str, model: str | None = None) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        # stub for dev without key
        return f"[STUB SCRIPT] {prompt[:400]} ... Voiceover: In a desolate New York, Robert Neville ... (generated stub, set OPENROUTER_API_KEY for real)"
    try:
        from openai import OpenAI

        client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
        chosen = model or os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")
        resp = client.chat.completions.create(
            model=chosen,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=4000,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        return f"[ERROR {e}] {prompt[:200]}"


def build_prompt(beats: list, metadata: dict | None, audio_scenes: list | None) -> str:
    meta_str = json.dumps(metadata or {}, indent=2)[:2000]
    beats_str = json.dumps(beats[:20], indent=2)[:4000]
    scenes_str = json.dumps(audio_scenes[:5] if audio_scenes else [], indent=2)[:2000]
    return f"""You are a YouTube movie recap writer for fair-use, advertiser-friendly recaps.

GOAL: Write a cohesive 14-20 minute voiceover script (2100-3000 words, ~150 wpm), voiceover-only, no original audio/music, for the film using the context below.

RULES (must follow for monetization):
- Transformative: rewrite dialog, add critique/education (why scene matters), never verbatim long quotes.
- Cuts: script will be paired to sub-10s clips; indicate pacing hints [CUT] [HOLD] where needed.
- No shock gore: if violence/blood/nudity required, note [BLUR] and describe Educational context, not sensational.
- Cohesive narrative arc: Act1 setup, Act2 confrontation, Act3 resolution — include I Am Legend alternate ending.
- Voiceover-only, no [SFX] from original.

METADATA (TMDB/OMDb):
{meta_str}

BEATS (hierarchical VLM Stage3):
{beats_str}

AUDIO SCENES (with subs):
{scenes_str}

Output ONLY the script text, paragraph breaks, no JSON. Target ~2600 words.
"""


def generate_script_for_film(film_id: str, video_id: str | None = None) -> dict:
    from app.database import SessionLocal
    from app.models import Film
    from app.models import Video
    from app.s3 import VOLUME_ID
    from app.s3 import get_s3_client

    s3 = get_s3_client()
    bucket = VOLUME_ID
    db = SessionLocal()
    try:
        film = db.query(Film).filter(Film.id == film_id).first()
        if not film:
            raise ValueError(f"film {film_id} not found")
        # fetch beats
        beats = []
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
            s3.download_file(bucket, f"films/{film_id}/vlm/stage3.json", tmp.name)
            beats = json.loads(pathlib.Path(tmp.name).read_text()).get("beats", [])
        except Exception:
            beats = []
        audio_scenes = []
        try:
            tmp2 = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
            s3.download_file(bucket, f"films/{film_id}/audio_enrich.json", tmp2.name)
            audio_scenes = json.loads(pathlib.Path(tmp2.name).read_text()).get("scenes", [])
        except Exception:
            audio_scenes = []
        prompt = build_prompt(beats, film.metadata_json, audio_scenes)
        script = _openrouter_chat(prompt)
        h = hashlib.sha256(script.encode()).hexdigest()[:16]
        # find or create video row
        video = None
        if video_id:
            video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            video = (
                db.query(Video)
                .filter(Video.film_id == film_id)
                .order_by(Video.created_at.desc())
                .first()
            )
        if not video:
            video = Video(film_id=film_id, status="scripting")  # type: ignore
            db.add(video)
            db.flush()
        video.script = script  # type: ignore
        video.script_hash = h  # type: ignore
        # estimate duration at 150 wpm
        words = len(script.split())
        est_sec = int(words / 150 * 60)
        est_sec = max(720, min(1200, est_sec))
        video.target_duration_sec = est_sec  # type: ignore
        video.status = "scripting"  # type: ignore
        db.commit()
        db.refresh(video)
        # also upload script to S3 for TTS
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w") as tf:
            tf.write(script)
            tf.flush()
            s3.upload_file(tf.name, bucket, f"films/{film_id}/script.txt")
        return {
            "video_id": str(video.id),
            "film_id": film_id,
            "script_hash": h,
            "words": words,
            "target_duration_sec": est_sec,
            "script_preview": script[:500],
        }
    finally:
        db.close()
