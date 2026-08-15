"""Proxy transcode helper — 480p generation via NVDEC/NVENC or ffmpeg fallback.

- Primary: PyNvVideoCodec `segmented_transcode` (1072 FPS, GOP30, cached decoder) when available on RunPod ADA_24.
- Fallback: ffmpeg `hwaccel cuda scale=854:480 h264_nvenc -g 30` for pod/local dev.
- Works with RunPod Network Volume mounted at /runpod-volume (/workspace on Pods) and S3 API s3://tn1qxkkw94/films/<id>/.
"""

import pathlib
import subprocess
import tempfile

from app.s3 import VOLUME_ID
from app.s3 import download_s3_with_fallback
from app.s3 import get_s3_client

# Backwards-compat alias — centralized helper lives in app.s3
_download_s3_with_fallback = download_s3_with_fallback


def _volume_root() -> pathlib.Path:
    # Serverless: /runpod-volume, Pod: /workspace
    for p in ["/runpod-volume", "/workspace"]:
        if pathlib.Path(p).exists():
            return pathlib.Path(p)
    return pathlib.Path("/tmp")


def _s3_key_to_volume_path(s3_key: str) -> pathlib.Path:
    return _volume_root() / s3_key


def _ensure_volume_dir(path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def transcode_480p_local(src_path: str, dst_path: str) -> dict:
    """Transcode src_path (local file) to 480p dst_path using ffmpeg NVENC if available, else libx264.

    Returns dict with {src, dst, width, height, codec, fps, duration}.
    Requires ffmpeg in PATH. Falls back gracefully.
    """
    _ensure_volume_dir(pathlib.Path(dst_path))
    # Prefer NVENC, fallback to libx264
    tried_nvenc = True
    cmd_nvenc = [
        "ffmpeg",
        "-y",
        "-hwaccel",
        "cuda",
        "-hwaccel_output_format",
        "cuda",
        "-i",
        src_path,
        "-vf",
        "scale_npp=854:480",
        "-c:v",
        "h264_nvenc",
        "-rc",
        "vbr_hq",
        "-cq",
        "23",
        "-b:v",
        "2M",
        "-maxrate",
        "4M",
        "-g",
        "30",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        dst_path,
    ]
    cmd_x264 = [
        "ffmpeg",
        "-y",
        "-i",
        src_path,
        "-vf",
        "scale=854:480",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-g",
        "30",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        dst_path,
    ]
    try:
        # quick check if cuda available
        result = subprocess.run(cmd_nvenc, capture_output=True, text=True, timeout=600)
        if result.returncode != 0 and "cuda" in (result.stderr or "").lower():
            tried_nvenc = False
            result = subprocess.run(cmd_x264, capture_output=True, text=True, timeout=3600)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr[-2000:]}")
    except FileNotFoundError as e:
        raise RuntimeError("ffmpeg not found in PATH") from e
    # probe
    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,codec_name,avg_frame_rate,duration",
                "-of",
                "default=noprint_wrappers=1",
                dst_path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        info = probe.stdout
    except Exception:
        info = ""
    return {"src": src_path, "dst": dst_path, "probe": info, "nvenc": tried_nvenc}


def transcode_480p_s3(s3_key: str, proxy_key: str | None = None) -> dict:
    """Fetch s3_key from volume S3 to temp, transcode, upload proxy, return proxy_key.

    - s3_key: source e.g. films/<film_id>/I.Am.Legend.1080p.mp4
    - proxy_key: destination, defaults to s3_key with 1080p->480p_proxy
    """
    bucket = VOLUME_ID
    s3 = get_s3_client()
    if proxy_key is None:
        proxy_key = s3_key.replace("1080p", "480p_proxy")
        if proxy_key == s3_key:
            proxy_key = s3_key.rsplit(".", 1)[0] + "_480p_proxy.mp4"
    # try volume mount first
    src_vol = _s3_key_to_volume_path(s3_key)
    dst_vol = _s3_key_to_volume_path(proxy_key)
    if src_vol.exists():
        return transcode_480p_volume(src_vol, dst_vol, proxy_key, bucket)
    # fallback: download via S3 with 403 fallback
    with tempfile.TemporaryDirectory() as tmp:
        tmp_src = pathlib.Path(tmp) / "src.mp4"
        tmp_dst = pathlib.Path(tmp) / "dst.mp4"
        _download_s3_with_fallback(s3, bucket, s3_key, tmp_src)
        result = transcode_480p_local(str(tmp_src), str(tmp_dst))
        s3.upload_file(str(tmp_dst), bucket, proxy_key)
        result["s3_key"] = s3_key
        result["proxy_key"] = proxy_key
        result["bucket"] = bucket
        return result


def transcode_480p_volume(
    src_vol: pathlib.Path, dst_vol: pathlib.Path, proxy_key: str, bucket: str
) -> dict:
    _ensure_volume_dir(dst_vol)
    result = transcode_480p_local(str(src_vol), str(dst_vol))
    result["s3_key"] = str(src_vol)
    result["proxy_key"] = proxy_key
    result["bucket"] = bucket
    return result
