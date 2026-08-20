"""Shared helpers for Modal functions."""

import json
import subprocess
import time
from pathlib import Path


def probe_video(video_path: str | Path) -> dict:
    """Probe video metadata via ffprobe. Returns width, height, duration, fps, num_frames."""
    video_path = str(video_path)
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration,r_frame_rate,nb_frames,codec_name",
        "-show_entries", "format=duration",
        "-of", "json",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")

    data = json.loads(result.stdout)
    stream = (data.get("streams") or [{}])[0]
    fmt = data.get("format", {})

    width = int(stream.get("width", 0))
    height = int(stream.get("height", 0))

    dur = stream.get("duration") or fmt.get("duration") or 0
    try:
        duration = float(dur)
    except Exception:
        duration = 0.0

    fps_str = stream.get("r_frame_rate", "0/1")
    try:
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) != 0 else 0
    except Exception:
        fps = 0

    nb_frames = stream.get("nb_frames")
    try:
        num_frames = int(nb_frames) if nb_frames and nb_frames != "N/A" else int(duration * fps) if fps else 0
    except Exception:
        num_frames = 0

    return {
        "width": width,
        "height": height,
        "duration_seconds": round(duration, 2),
        "fps": round(fps, 2),
        "num_frames": num_frames,
        "codec": stream.get("codec_name"),
    }


def compute_proxy_resolution(src_w: int, src_h: int, max_w: int = 854, max_h: int = 480) -> tuple[int, int]:
    """Compute proxy resolution preserving DAR, fitting within max_w x max_h (even dimensions)."""
    if src_w == 0 or src_h == 0:
        return max_w, max_h
    scale = min(max_w / src_w, max_h / src_h)
    # Don't upscale — if source smaller than max, keep source size
    if scale > 1:
        scale = 1
    tgt_w = int(round(src_w * scale / 2) * 2)
    tgt_h = int(round(src_h * scale / 2) * 2)
    # Ensure even and at least 2
    tgt_w = max(2, tgt_w if tgt_w % 2 == 0 else tgt_w - 1)
    tgt_h = max(2, tgt_h if tgt_h % 2 == 0 else tgt_h - 1)
    return tgt_w, tgt_h


def transcode_pynvc(input_path: str | Path, output_path: str | Path, width: int | None = None, height: int | None = None) -> dict:
    """
    Transcode via NVIDIA PyNvVideoCodec (NVDEC/NVENC hardware).
    Preserves aspect ratio and source FPS; targets ~900k-1M bitrate for ~3x smaller proxy.

    Uses Transcoder class which does demux + decode + encode + mux in one go.
    Requires pynvvideocodec==2.2.0 and CUDA 13.3.1 runtime.

    See:
      - https://docs.nvidia.com/video-technologies/pynvvideocodec/pynvc-api-reference/transcoder.html
      - https://docs.nvidia.com/video-technologies/pynvvideocodec/pynvc-api-prog-guide/using_pynvvideocodec_apis.html
    """
    try:
        import PyNvVideoCodec as nvc
    except ImportError as e:
        raise RuntimeError("PyNvVideoCodec not installed in image. Install via pip install pynvvideocodec==2.2.0") from e

    input_path = str(input_path)
    output_path = str(output_path)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Auto-compute target preserving DAR if not explicitly provided
    if width is None or height is None:
        try:
            src_meta = probe_video(input_path)
            width, height = compute_proxy_resolution(src_meta["width"], src_meta["height"])
        except Exception:
            width, height = 854, 480  # fallback

    # Bitrate: scale with pixel ratio but floor at 800k for quality
    # Source 1920x800 ~1.5M pixels, 854x356 ~0.3M pixels (20% pixels) -> ~800k is good for 480p 23.98fps 103min (~600MB)
    encode_config = {
        "codec": "h264",
        "s": f"{width}x{height}",
        "preset": "P4",  # P1 (fastest) .. P7 (slowest/high quality); P4 balanced
        "rc": "vbr",
        "bitrate": "900k",
        "maxbitrate": "1200k",
        "gop": "60",
        "bf": "0",
        # fps not set -> preserves source fps (24000/1001)
    }

    start = time.perf_counter()
    # Transcoder does demux->decode->encode->mux preserving audio
    # Signature: Transcoder(enc_file_path, muxed_file_path, gpu_id, cuda_context, cuda_stream, **kwargs)
    # Note: Modal GPUs expose single device gpu_id=0
    transcoder = nvc.Transcoder(
        input_path,
        output_path,
        gpu_id=0,
        cuda_context=0,
        cuda_stream=0,
        **encode_config,
    )
    # Full file transcode (preserves audio)
    transcoder.transcode_with_mux()

    elapsed = time.perf_counter() - start
    meta = probe_video(output_path)
    meta["transcode_seconds"] = round(elapsed, 2)
    meta["codec_used"] = "h264_nvenc_pynvc"
    meta["transcoder"] = "PyNvVideoCodec"
    if elapsed > 0 and meta["num_frames"]:
        meta["fps_achieved"] = round(meta["num_frames"] / elapsed, 1)
    return meta


def transcode_ffmpeg(input_path: str | Path, output_path: str | Path, width: int | None = None, height: int | None = None) -> dict:
    """Fallback transcode via ffmpeg (h264_nvenc if GPU available, else libx264). Preserves aspect."""
    input_path = str(input_path)
    output_path = str(output_path)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    if width is None or height is None:
        try:
            src_meta = probe_video(input_path)
            width, height = compute_proxy_resolution(src_meta["width"], src_meta["height"])
        except Exception:
            width, height = 854, 480

    def try_cmd(codec: str) -> bool:
        if codec == "h264_nvenc":
            cmd = [
                "ffmpeg", "-y",
                "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
                "-i", input_path,
                "-vf", f"scale_cuda={width}:{height}",
                "-c:v", codec,
                "-preset", "p4",
                "-b:v", "900k",
                "-maxrate", "1200k",
                "-g", "60",
                "-bf", "0",
                "-c:a", "aac", "-b:a", "128k",
                output_path,
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", input_path,
                "-vf", f"scale={width}:{height}",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "26",
                "-g", "60",
                "-bf", "0",
                "-c:a", "aac", "-b:a", "128k",
                output_path,
            ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        return result.returncode == 0

    start = time.perf_counter()
    if not try_cmd("h264_nvenc"):
        if not try_cmd("libx264"):
            raise RuntimeError("ffmpeg transcode failed with both nvenc and libx264")
        codec_used = "libx264"
    else:
        codec_used = "h264_nvenc"

    elapsed = time.perf_counter() - start
    meta = probe_video(output_path)
    meta["transcode_seconds"] = round(elapsed, 2)
    meta["codec_used"] = codec_used
    meta["transcoder"] = "ffmpeg"
    if elapsed > 0 and meta["num_frames"]:
        meta["fps_achieved"] = round(meta["num_frames"] / elapsed, 1)
    return meta


def transcode_auto(input_path: str | Path, output_path: str | Path, width: int | None = None, height: int | None = None) -> dict:
    """Try PyNvVideoCodec first, fallback to ffmpeg if unavailable/failed. Auto aspect if width/height None."""
    try:
        return transcode_pynvc(input_path, output_path, width=width, height=height)
    except Exception as e:
        print(f"PyNvVideoCodec failed ({e}), falling back to ffmpeg...")
        return transcode_ffmpeg(input_path, output_path, width=width, height=height)
