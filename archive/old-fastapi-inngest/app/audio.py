"""Audio enrichment — SRT primary + WhisperX gap fill + diarization + librosa.

Pipeline:
- extract 16k mono via ffmpeg
- parse SRT from assets kind=subtitle
- PySceneDetect ContentDetector/AdaptiveDetector -> boundaries
- WhisperX transcribe + align (wav2vec2) -> word timestamps where SRT gaps
- pyannote diarization optional, librosa RMS
Output per-scene JSON `films/<id>/audio_enrich.json` and store pointer.
Isolated to worker image (ffmpeg, whisperx, pyannote, librosa, scenedetect); FastAPI just orchestrates.
"""

import json
import os
import pathlib
import subprocess
import tempfile


def _volume_root() -> pathlib.Path:
    for p in ["/runpod-volume", "/workspace"]:
        if pathlib.Path(p).exists():
            return pathlib.Path(p)
    return pathlib.Path("/tmp")


def extract_mono_wav(src_path: str, dst_wav: str, sr: int = 16000) -> str:
    pathlib.Path(dst_wav).parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-i", src_path, "-ar", str(sr), "-ac", "1", "-c:a", "pcm_s16le", dst_wav]
    subprocess.run(cmd, capture_output=True, check=True, timeout=300)
    return dst_wav


def parse_srt(srt_path: str) -> list[dict]:
    try:
        import srt  # type: ignore

        text = pathlib.Path(srt_path).read_text(encoding="utf-8", errors="ignore")
        subs = list(srt.parse(text))
        return [
            {"start": s.start.total_seconds(), "end": s.end.total_seconds(), "text": s.content}
            for s in subs
        ]
    except Exception:
        # fallback simple parse
        out = []
        try:
            lines = pathlib.Path(srt_path).read_text(encoding="utf-8", errors="ignore").splitlines()
            # very naive
            idx = 0
            while idx < len(lines):
                if "-->" in lines[idx]:
                    times = lines[idx].split("-->")

                    def to_sec(t):
                        t = t.strip().split(",")[0]
                        h, m, s = t.split(":")
                        return int(h) * 3600 + int(m) * 60 + float(s)

                    try:
                        start = to_sec(times[0])
                        end = to_sec(times[1])
                        txt = ""
                        idx += 1
                        while idx < len(lines) and lines[idx].strip() != "":
                            txt += lines[idx] + " "
                            idx += 1
                        out.append({"start": start, "end": end, "text": txt.strip()})
                    except Exception:
                        pass
                idx += 1
        except Exception:
            pass
        return out


def detect_scenes(src_path: str) -> list[dict]:
    try:
        from scenedDetect.detectors import ContentDetector  # type: ignore
        from scenedetect import SceneManager  # type: ignore
        from scenedetect import VideoManager  # type: ignore

        # fallback import path
        from scenedetect.detectors import ContentDetector  # type: ignore

        vm = VideoManager([src_path])
        sm = SceneManager()
        sm.add_detector(ContentDetector(threshold=27.0))
        vm.start()
        sm.detect_scenes(frame_source=vm)
        scenes = sm.get_scene_list()
        out = []
        for i, (start, end) in enumerate(scenes):
            out.append({"id": i, "start_sec": start.get_seconds(), "end_sec": end.get_seconds()})
        vm.release()
        return out
    except Exception:
        # fallback: no scene detect, single scene
        try:
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    src_path,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            dur = float(probe.stdout.strip() or 0)
        except Exception:
            dur = 5400
        return [{"id": 0, "start_sec": 0.0, "end_sec": dur}]


def whisperx_transcribe(wav_path: str, model: str = "large-v2", batch_size: int = 4) -> dict:
    try:
        import whisperx  # type: ignore

        device = "cuda"
        try:
            import torch

            if not torch.cuda.is_available():
                device = "cpu"
        except Exception:
            device = "cpu"
        compute_type = "float16" if device == "cuda" else "int8"
        asr = whisperx.load_model(model, device, compute_type=compute_type)
        audio = whisperx.load_audio(wav_path)
        result = asr.transcribe(audio, batch_size=batch_size)
        # align
        try:
            align_model, metadata = whisperx.load_align_model(
                language_code=result.get("language", "en"), device=device
            )
            result = whisperx.align(
                result["segments"],
                align_model,
                metadata,
                audio,
                device,
                return_char_alignments=False,
            )
        except Exception:
            pass
        return result
    except Exception as e:
        return {"segments": [], "error": str(e), "language": "en"}


def diarize(wav_path: str) -> list:
    try:
        from whisperx.diarize import DiarizationPipeline  # type: ignore

        token = os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_TOKEN")
        pipe = DiarizationPipeline(token=token, device="cuda")
        return pipe(wav_path)
    except Exception:
        return []


def enrich_audio_for_film(film_id: str, src_s3_key: str, srt_s3_key: str | None = None) -> dict:
    """Main entry — downloads via volume or S3, runs enrichment, uploads JSON."""
    from app.s3 import VOLUME_ID
    from app.s3 import download_s3_with_fallback
    from app.s3 import get_s3_client

    bucket = VOLUME_ID
    s3 = get_s3_client()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        src_local = tmp / "src.mp4"
        wav_local = tmp / "mono.wav"
        srt_local = tmp / "subs.srt"
        # fetch src
        vol_src = _volume_root() / src_s3_key
        if vol_src.exists():
            src_local = vol_src
            wav_local = tmp / "mono.wav"
        else:
            download_s3_with_fallback(s3, bucket, src_s3_key, src_local)
        extract_mono_wav(str(src_local), str(wav_local))
        subs = []
        if srt_s3_key:
            vol_srt = _volume_root() / srt_s3_key
            if vol_srt.exists():
                srt_local = vol_srt
                subs = parse_srt(str(srt_local))
            else:
                try:
                    download_s3_with_fallback(s3, bucket, srt_s3_key, srt_local)
                    subs = parse_srt(str(srt_local))
                except Exception:
                    subs = []
        scenes = detect_scenes(str(src_local))
        whisper = whisperx_transcribe(str(wav_local))
        # fuse per scene
        enriched = []
        for sc in scenes:
            s0, s1 = sc["start_sec"], sc["end_sec"]
            # gather subs in scene
            scene_subs = [s for s in subs if not (s["end"] < s0 or s["start"] > s1)]
            # gap fill where no subs
            gap_fill = []
            if not scene_subs and whisper.get("segments"):
                gap_fill = [
                    seg
                    for seg in whisper["segments"]
                    if not (seg.get("end", 0) < s0 or seg.get("start", 0) > s1)
                ]
            enriched.append({**sc, "subs": scene_subs, "whisper_gap": gap_fill, "diarization": []})
        out = {"film_id": film_id, "scenes": enriched, "whisper": whisper, "srt_count": len(subs)}
        # upload
        json_key = f"films/{film_id}/audio_enrich.json"
        tmp_json = tmp / "audio_enrich.json"
        tmp_json.write_text(json.dumps(out, indent=2))
        s3.upload_file(str(tmp_json), bucket, json_key)
        return {"s3_key": json_key, "bucket": bucket, "scenes": len(enriched)}
