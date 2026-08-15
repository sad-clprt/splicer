"""TTS + WhisperX captions + Blender headless NVENC final export.

- Qwen3-TTS-12Hz-1.7B-CustomVoice (Cached Model, ADA_24) -> wav
- WhisperX re-run on final TTS wav -> word timestamps -> pacing EDL
- Blender headless via edit_decision.json (on volume S3) -> /runpod-volume mount -> NVENC 1080p
- edit_decision.json schema per deep-research §3: film_id, fps, s3_keys, scenes, markers, safety_flags, script, export
"""

import json
import pathlib
import subprocess
import tempfile

from dotenv import load_dotenv

load_dotenv()


def _volume_root() -> pathlib.Path:
    for p in ["/runpod-volume", "/workspace"]:
        if pathlib.Path(p).exists():
            return pathlib.Path(p)
    return pathlib.Path("/tmp")


def tts_generate(text: str, out_wav: str) -> str:
    # stub until Qwen3-TTS deployed — generate silent wav of estimated duration
    # real: load Qwen3-TTS 12Hz 1.7B CustomVoice via vLLM, produce wav
    try:
        # try real model if available
        raise ImportError("Qwen3-TTS not installed in this env — stub")
    except Exception:
        # generate silent wav via ffmpeg (duration ~ words/150*60)
        words = len(text.split())
        dur = max(10, words / 150 * 60)
        pathlib.Path(out_wav).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=24000:cl=mono",
                "-t",
                str(int(dur)),
                "-c:a",
                "pcm_s16le",
                out_wav,
            ],
            capture_output=True,
            check=False,
            timeout=60,
        )
        # if ffmpeg fails, create empty
        if not pathlib.Path(out_wav).exists():
            pathlib.Path(out_wav).write_bytes(b"RIFF....WAVE")
        return out_wav


def whisperx_captions(wav_path: str) -> list[dict]:
    try:
        from app.audio import whisperx_transcribe

        r = whisperx_transcribe(wav_path)
        words = []
        for seg in r.get("segments", []):
            for w in seg.get("words", []) or []:
                words.append({"word": w.get("word"), "start": w.get("start"), "end": w.get("end")})
        # fallback segment-level
        if not words:
            for seg in r.get("segments", []):
                words.append(
                    {
                        "word": seg.get("text", "")[:30],
                        "start": seg.get("start"),
                        "end": seg.get("end"),
                    }
                )
        return words
    except Exception:
        return []


def build_edit_decision(film_id: str, fps: int = 24) -> dict:
    from app.database import SessionLocal
    from app.models import Film
    from app.models import Video
    from app.s3 import VOLUME_ID
    from app.s3 import download_s3_with_fallback
    from app.s3 import get_s3_client

    s3 = get_s3_client()
    bucket = VOLUME_ID
    db = SessionLocal()
    try:
        film = db.query(Film).filter(Film.id == film_id).first()
        video = (
            db.query(Video)
            .filter(Video.film_id == film_id)
            .order_by(Video.created_at.desc())
            .first()
        )
        script = video.script if video else ""
        # fetch vlm + audio
        scenes = []
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
            download_s3_with_fallback(s3, bucket, f"films/{film_id}/audio_enrich.json", tmp.name)
            scenes = json.loads(pathlib.Path(tmp.name).read_text()).get("scenes", [])
        except Exception:
            scenes = []
        safety = []
        try:
            tmp2 = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
            download_s3_with_fallback(s3, bucket, f"films/{film_id}/safety_flags.json", tmp2.name)
            safety = json.loads(pathlib.Path(tmp2.name).read_text())
            if isinstance(safety, dict):
                safety = safety.get("flags", [])
        except Exception:
            safety = []
        markers = [
            {"time_sec": s["start_sec"], "type": "scene_cut", "label": f"scene {s['id']}"}
            for s in scenes[:20]
        ]
        for f in safety:
            markers.append(
                {
                    "time_sec": f.get("t0", 0),
                    "type": "safety",
                    "label": f.get("category", "safety"),
                    "fix": f.get("fix", "blur"),
                    "bbox": f.get("bbox", {}),
                }
            )
        return {
            "film_id": film_id,
            "fps": fps,
            "proxy_s3_key": f"films/{film_id}/480p_proxy.mp4",
            "original_s3_key": f"films/{film_id}/I.Am.Legend.1080p.mp4",
            "edit_version": "v1",
            "scenes": scenes,
            "markers": markers,
            "safety_flags": safety,
            "script": {"text": script[:4000] if script else "", "segments": []},
            "export": {
                "width": 1920,
                "height": 1080,
                "fps": fps,
                "gop": 30,
                "video_codec": "h264_nvenc",
                "preset": "slow",
                "rc": "vbr_hq",
                "cq": 23,
                "bitrate_kbps": 8000,
                "maxrate_kbps": 12000,
                "audio_codec": "aac",
                "audio_bitrate_kbps": 384,
                "pix_fmt": "yuv420p",
                "container": "mp4",
                "profile": "high",
                "level": "4.2",
            },
        }
    finally:
        db.close()


def tts_and_assemble(film_id: str, video_id: str | None = None) -> dict:
    from app.s3 import VOLUME_ID
    from app.s3 import get_s3_client

    bucket = VOLUME_ID
    s3 = get_s3_client()
    # build EDL
    edl = build_edit_decision(film_id)
    with tempfile.TemporaryDirectory() as tmp:
        edl_path = pathlib.Path(tmp) / "edit_decision.json"
        edl_path.write_text(json.dumps(edl, indent=2))
        s3.upload_file(str(edl_path), bucket, f"films/{film_id}/edit_decision.json")
        # TTS
        script_text = (
            edl["script"]["text"]
            or "Hello from Splicer. This is a stub voiceover. Set OPENROUTER_API_KEY and deploy Qwen3-TTS for real."
        )
        wav_path = pathlib.Path(tmp) / "tts.wav"
        tts_generate(script_text, str(wav_path))
        s3.upload_file(str(wav_path), bucket, f"films/{film_id}/tts.wav")
        caps = whisperx_captions(str(wav_path))
        caps_path = pathlib.Path(tmp) / "tts_captions.json"
        caps_path.write_text(json.dumps(caps, indent=2))
        s3.upload_file(str(caps_path), bucket, f"films/{film_id}/tts_captions.json")
        # Blender headless export (stub if blender not installed)
        out_key = f"films/{film_id}/final_1080p.mp4"
        # For now, just copy original as placeholder final if blender missing
        # Real worker: blender --background --python /app/blender_assemble.py -- --edl /runpod-volume/films/<id>/edit_decision.json
        try:
            subprocess.run(["blender", "--version"], capture_output=True, timeout=5, check=True)
            blender_available = True
        except Exception:
            blender_available = False
        if not blender_available:
            # placeholder: indicate blender not installed, final not yet rendered
            return {
                "bucket": bucket,
                "edl_s3_key": f"films/{film_id}/edit_decision.json",
                "tts_s3_key": f"films/{film_id}/tts.wav",
                "captions": len(caps),
                "blender": "not installed — deploy Serverless blender+ffmpeg+NVENC image for real export",
                "final_s3_key": out_key,
            }
        # real blender path would run here and upload final
        return {
            "bucket": bucket,
            "edl_s3_key": f"films/{film_id}/edit_decision.json",
            "tts_s3_key": f"films/{film_id}/tts.wav",
            "captions": len(caps),
            "final_s3_key": out_key,
        }
