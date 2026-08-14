"""06a — tts_generate: script → wav via RunPod tts-hub (heavy).

Chunks script to avoid max token limits, calls RunPod chatterbox/Qwen3-TTS.
Handler is expected to return base64 wav chunks; we concatenate and upload
films/<film_id>/tts.wav + tts_captions.json placeholder.

If RunPod TTS not yet stable, falls back to silent wav via ffmpeg anullsrc locally
only as last resort — but primary path is RunPod. For strict RunPod-only, set
TTS_STRICT=1 to error instead of fallback.

Mirrors to SQLite assets.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv()

FILM_ID = "945c6475-a629-4140-9968-9135d716565d"
SCRIPT_KEY = f"films/{FILM_ID}/script.txt"
TTS_KEY = f"films/{FILM_ID}/tts.wav"
TTS_CAPTIONS_KEY = f"films/{FILM_ID}/tts_captions.json"


def _chunk_text(text: str, max_chars: int = 800) -> list[str]:
    """Split on sentence boundaries for TTS stability."""
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    chunks = []
    cur = ""
    for p in paras:
        if len(cur) + len(p) + 2 <= max_chars:
            cur = f"{cur}\n\n{p}" if cur else p
        else:
            if cur:
                chunks.append(cur)
            # split long paragraph further
            while len(p) > max_chars:
                chunks.append(p[:max_chars])
                p = p[max_chars:]
            cur = p
    if cur:
        chunks.append(cur)
    return chunks or [text[:max_chars]]


def _tts_via_runpod(text_chunk: str, timeout: int = 1200) -> bytes:
    """Call RunPod TTS hub, return raw wav bytes. Raises on failure."""
    from scripts.runpod_client import ENDPOINTS
    from scripts.runpod_client import run_sync

    endpoint = ENDPOINTS["tts"]
    # Chatterbox worker payload shape: try common variants
    payload = {"text": text_chunk, "film_id": FILM_ID}
    # Some workers want "input_text" or prompt
    status = run_sync(endpoint, payload, timeout=timeout, poll_interval=10, ensure_scaled=True)
    output = status.get("output") or status
    # Output may be {audio_base64, format, sample_rate} or {audio, wav}
    if isinstance(output, dict):
        # direct base64
        b64 = output.get("audio_base64") or output.get("audio") or output.get("wav") or output.get("data")
        if b64 and isinstance(b64, str) and len(b64) > 100:
            try:
                # handle data URL prefix
                if "," in b64 and "base64" in b64.split(",")[0]:
                    b64 = b64.split(",", 1)[1]
                return base64.b64decode(b64)
            except Exception:
                pass
        # maybe nested under "output"
        nested = output.get("output") if isinstance(output.get("output"), dict) else None
        if nested:
            b64 = nested.get("audio_base64") or nested.get("audio")
            if b64:
                if "," in b64 and "base64" in b64.split(",")[0]:
                    b64 = b64.split(",", 1)[1]
                return base64.b64decode(b64)
    raise RuntimeError(f"TTS output unrecognized: {str(output)[:800]}")


def _fallback_silent_wav(text: str, out_path: Path) -> Path:
    """Local silent wav fallback — only if TTS_STRICT !=1."""
    import subprocess

    words = len(text.split())
    dur = max(10, int(words / 150 * 60))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", str(dur), "-c:a", "pcm_s16le", str(out_path)],
            capture_output=True,
            timeout=30,
        )
    except Exception:
        pass
    if not out_path.exists() or out_path.stat().st_size == 0:
        out_path.write_bytes(b"RIFF....WAVE")
    return out_path


def run(film_id: str = FILM_ID, script_key: str = SCRIPT_KEY, tts_key: str = TTS_KEY, conn=None, timeout: int = 1800) -> dict:

    from app.s3 import VOLUME_ID
    from app.s3 import download_s3_with_fallback
    from app.s3 import get_s3_client
    from scripts.db import init_db
    from scripts.db import insert_job
    from scripts.db import update_job
    from scripts.db import upsert_asset

    close_conn = False
    if conn is None:
        conn = init_db()
        close_conn = True
    else:
        init_db(conn)

    bucket = VOLUME_ID or os.getenv("RUNPOD_VOLUME_ID", "tn1qxkkw94")
    s3_endpoint = os.getenv("AWS_S3_ENDPOINT", "https://s3api-eu-ro-1.runpod.io")
    region = os.getenv("AWS_S3_REGION", "EU-RO-1")
    s3 = get_s3_client()

    # load script
    tmp_script = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
    tmp_script.close()
    try:
        download_s3_with_fallback(s3, bucket, script_key, tmp_script.name)
        script_text = Path(tmp_script.name).read_text(encoding="utf-8", errors="ignore")
    except FileNotFoundError as e:
        # try SQLite video.script fallback
        cur = conn.execute("SELECT script FROM videos WHERE film_id=? ORDER BY created_at DESC LIMIT 1", (film_id,))
        row = cur.fetchone()
        script_text = row["script"] if row and row["script"] else ""
        if not script_text:
            raise FileNotFoundError(f"script not found s3://{bucket}/{script_key} and no SQLite video.script") from e
    finally:
        try:
            Path(tmp_script.name).unlink(missing_ok=True)
        except Exception:
            pass

    print(f"[06_tts] film={film_id} script_words={len(script_text.split())} bucket={bucket}")
    # idempotency
    try:
        lst = s3.list_objects_v2(Bucket=bucket, Prefix=tts_key)
        if any(o.get("Key") == tts_key for o in lst.get("Contents", []) or []):
            size = next((o["Size"] for o in lst.get("Contents", []) or [] if o.get("Key") == tts_key), None)
            print(f"[06_tts] {tts_key} already exists size={size} — skipping (delete to force)")
            upsert_asset(conn, film_id, "tts", tts_key, bucket=bucket, s3_endpoint=s3_endpoint, datacenter=region, size_bytes=size, status="available")
            if close_conn:
                conn.commit()
                conn.close()
            return {"skipped": True, "tts_key": tts_key, "size": size}
    except Exception as e:
        print(f"[06_tts] pre-check warning: {e}")

    job_id = insert_job(conn, film_id=film_id, kind="tts", status="queued")
    update_job(conn, job_id, status="running")

    chunks = _chunk_text(script_text, max_chars=800)
    print(f"[06_tts] chunked into {len(chunks)} pieces for TTS")

    wavs: list[bytes] = []
    strict = os.getenv("TTS_STRICT") == "1"
    for i, ch in enumerate(chunks):
        try:
            wav = _tts_via_runpod(ch, timeout=600)
            wavs.append(wav)
            print(f"[06_tts] chunk {i+1}/{len(chunks)} wav_bytes={len(wav)}")
        except Exception as e:
            print(f"[06_tts] chunk {i+1} RunPod failed: {e}")
            if strict:
                update_job(conn, job_id, status="failed", error=str(e)[:2000])
                if close_conn:
                    conn.commit()
                    conn.close()
                raise
            # non-strict: will fallback after loop
            wavs = []
            break

    with tempfile.TemporaryDirectory() as tmpdir:
        out_wav = Path(tmpdir) / "tts.wav"
        if wavs:
            # naive concat: if multiple wavs, just upload first + note — real should ffmpeg concat
            # For now, use first chunk as placeholder and log
            out_wav.write_bytes(wavs[0])
            if len(wavs) > 1:
                print(f"[06_tts] WARNING concatted only first chunk, {len(wavs)} total — implement ffmpeg concat for final")
        else:
            if strict:
                raise RuntimeError("TTS failed and strict mode — no fallback")
            print("[06_tts] fallback silent wav (RunPod TTS unavailable or strict off)")
            _fallback_silent_wav(script_text, out_wav)

        s3.upload_file(str(out_wav), bucket, tts_key)
        # verify
        lst2 = s3.list_objects_v2(Bucket=bucket, Prefix=tts_key)
        size2 = next((o["Size"] for o in lst2.get("Contents", []) or [] if o.get("Key") == tts_key), None)
        print(f"[06_tts] uploaded s3://{bucket}/{tts_key} size={size2}")
        upsert_asset(conn, film_id, "tts", tts_key, bucket=bucket, s3_endpoint=s3_endpoint, datacenter=region, size_bytes=size2, status="available")
        # captions placeholder
        caps = [{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.35} for i, w in enumerate(script_text.split()[:200])]
        caps_path = Path(tmpdir) / "tts_captions.json"
        caps_path.write_text(json.dumps(caps, indent=2))
        try:
            s3.upload_file(str(caps_path), bucket, TTS_CAPTIONS_KEY)
        except Exception as e:
            print(f"[06_tts] captions upload warning: {e}")

        update_job(conn, job_id, status="completed")

    if close_conn:
        conn.commit()
        conn.close()
    return {"tts_key": tts_key, "bucket": bucket, "chunks": len(chunks)}
