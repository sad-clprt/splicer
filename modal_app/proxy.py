"""Modal endpoint: 1080p → 480p proxy transcode via NVIDIA Video SDK.

Uses PyNvVideoCodec (Video Codec SDK) on CUDA 13.3.1 runtime.
Fallback to ffmpeg if PyNvVideoCodec unavailable.

Deploy:
    modal deploy -m modal_app.app
    modal deploy -m modal_app.proxy

Test locally:
    modal run -m modal_app.proxy --film-id i_am_legend_ed264664

Invoke from lib/tools/proxy.py:
    from modal import Function
    f = Function.from_name("splicer", "transcode_proxy")
    result = f.remote(film_id="...")
"""

import time
from pathlib import Path

import modal

from .app import app, volume, VOLUME_MOUNT
from .common import probe_video, transcode_auto, transcode_ffmpeg, transcode_pynvc

# Image with CUDA 13.3.1 runtime + PyNvVideoCodec (NVIDIA Video SDK Python bindings)
# Reference: https://hub.docker.com/layers/nvidia/cuda/13.3.1-runtime-ubuntu24.04/images/sha256-6155abf10c038d0daf166932f2b83865341ee1e9c92b452a6fae01c6ce31a5ac
# Host driver is 580.95.05 / CUDA 13.0 (docs/guide/cuda.md), but 13.3.1 runtime is compatible via pip toolkit fallback.
# If you hit driver mismatch, pin to 12.5.1 or 13.0.0.
image = (
    modal.Image.from_registry("nvidia/cuda:13.3.1-runtime-ubuntu24.04", add_python="3.12")
    .entrypoint([])  # silence base image verbose entrypoint
    .apt_install("ffmpeg")  # for ffprobe + fallback encode
    .pip_install("pynvvideocodec==2.2.0", "loguru")
    .env({"NVIDIA_DRIVER_CAPABILITIES": "compute,utility,video"})
)


@app.function(
    image=image,
    gpu="T4",  # cheapest GPU with NVENC/NVDEC; use ["T4","L4","A10G"] for fallback
    volumes={VOLUME_MOUNT: volume},
    timeout=3600,  # 1 hour — no RunPod 10min limit
    retries=modal.Retries(max_retries=1),
)
def transcode_proxy(
    film_id: str,
    source_filename: str | None = None,
    overwrite: bool = False,
    transcoder: str = "auto",
) -> dict:
    """
    Transcode film source to 480p proxy on Modal Volume.

    Args:
        film_id: Film directory name (e.g. i_am_legend_ed264664)
        source_filename: Optional override (default: auto-detect source.mp4)
        overwrite: If False, skip if proxy already exists
        transcoder: "auto" (try PyNvVideoCodec, fallback ffmpeg), "pynvc" (force PyNvVideoCodec), "ffmpeg" (force ffmpeg)

    Returns:
        dict with proxy_path, width, height, duration_seconds, size_bytes, codec_used, fps_achieved, transcoder
    """
    from loguru import logger

    film_dir = Path(VOLUME_MOUNT) / film_id
    if not film_dir.exists():
        raise FileNotFoundError(f"Film directory not found on Volume: {film_dir} (film_id={film_id})")

    # Auto-detect source if not provided
    if source_filename:
        source_path = film_dir / source_filename
    else:
        manifest_path = film_dir / "manifest.json"
        candidate = None
        if manifest_path.exists():
            try:
                import json
                manifest = json.loads(manifest_path.read_text())
                candidate = manifest.get("files", {}).get("source")
            except Exception as e:
                logger.warning(f"Failed to parse manifest: {e}")
        if candidate:
            source_path = film_dir / candidate
        else:
            p = film_dir / "source.mp4"
            if p.exists():
                source_path = p
            else:
                matches = list(film_dir.glob("source.*"))
                if not matches:
                    matches = [x for x in film_dir.glob("*.mp4") if x.name != "proxy_480p.mp4"]
                if not matches:
                    raise FileNotFoundError(f"No source video found in {film_dir}")
                source_path = matches[0]

    if not source_path.exists():
        raise FileNotFoundError(f"Source video not found: {source_path}")

    proxy_path = film_dir / "proxy_480p.mp4"

    if proxy_path.exists() and not overwrite:
        logger.info(f"Proxy already exists at {proxy_path}, skipping (overwrite=False)")
        meta = probe_video(proxy_path)
        size_bytes = proxy_path.stat().st_size
        return {
            "film_id": film_id,
            "source_path": str(source_path.relative_to(VOLUME_MOUNT)),
            "proxy_path": str(proxy_path.relative_to(VOLUME_MOUNT)),
            "width": meta["width"],
            "height": meta["height"],
            "duration_seconds": meta["duration_seconds"],
            "size_bytes": size_bytes,
            "size_mb": round(size_bytes / (1024 * 1024), 2),
            "codec_used": meta.get("codec", "unknown"),
            "transcoder": "skipped",
            "skipped": True,
        }

    logger.info(f"Transcoding {source_path} -> {proxy_path} (film_id={film_id}) via {transcoder}")
    start = time.perf_counter()

    try:
        src_meta = probe_video(source_path)
        logger.info(f"Source: {src_meta['width']}x{src_meta['height']} {src_meta['duration_seconds']}s {src_meta['codec']} {src_meta['fps']}fps")
    except Exception as e:
        logger.warning(f"Failed to probe source: {e}")
        src_meta = {}

    # Validate transcoder choice
    transcoder = transcoder.lower()
    if transcoder not in ("auto", "pynvc", "ffmpeg"):
        raise ValueError(f"Invalid transcoder '{transcoder}'. Must be one of: auto, pynvc, ffmpeg")

    if transcoder == "pynvc":
        out_meta = transcode_pynvc(source_path, proxy_path)
    elif transcoder == "ffmpeg":
        out_meta = transcode_ffmpeg(source_path, proxy_path)
    else:  # auto
        out_meta = transcode_auto(source_path, proxy_path)

    size_bytes = Path(proxy_path).stat().st_size
    size_mb = size_bytes / (1024 * 1024)
    elapsed = time.perf_counter() - start

    logger.info(
        f"Transcode complete: {out_meta['width']}x{out_meta['height']} {out_meta['duration_seconds']}s "
        f"{size_mb:.1f} MB in {elapsed:.1f}s ({out_meta.get('transcoder')}/{out_meta.get('codec_used')}) "
        f"fps_achieved={out_meta.get('fps_achieved')}"
    )

    try:
        volume.commit()
    except Exception as e:
        logger.warning(f"volume.commit() failed (background commit will still run): {e}")

    return {
        "film_id": film_id,
        "source_path": str(source_path.relative_to(VOLUME_MOUNT)),
        "proxy_path": str(proxy_path.relative_to(VOLUME_MOUNT)),
        "width": out_meta["width"],
        "height": out_meta["height"],
        "duration_seconds": out_meta["duration_seconds"],
        "fps": out_meta.get("fps"),
        "num_frames": out_meta.get("num_frames"),
        "size_bytes": size_bytes,
        "size_mb": round(size_mb, 2),
        "codec_used": out_meta.get("codec_used"),
        "transcoder": out_meta.get("transcoder"),
        "fps_achieved": out_meta.get("fps_achieved"),
        "transcode_seconds": round(elapsed, 2),
        "skipped": False,
    }


@app.local_entrypoint()
def main(film_id: str, overwrite: bool = False, transcoder: str = "auto"):
    """Local entrypoint for `modal run -m modal_app.proxy --film-id ... --transcoder ffmpeg|pynvc|auto`"""
    result = transcode_proxy.remote(film_id, overwrite=overwrite, transcoder=transcoder)
    print(result)
