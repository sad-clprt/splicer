"""Splicer proxy handler for RunPod Serverless `splicer-proxy` (ADA_24, tn1qxkkw94).

- Queue-based endpoint handler `runpod.serverless.start({"handler": handler})`
- Input: {"s3_key": "films/<film_id>/I.Am.Legend.1080p.mp4", "proxy_key": "films/<film_id>/480p_proxy.mp4" (optional)}
- Process: volume mount /runpod-volume (Serverless) vs /workspace (Pod) -> PyNvVideoCodec 1072 FPS GOP30 or ffmpeg h264_nvenc fallback (scale 854:480) -> S3 list_objects_v2 verify -> Neon Job/Asset mirror (best-effort, works even without DB)
- Output: {"s3_key","proxy_key","bucket","probe"}
"""

import os
import pathlib
import subprocess
import sys

import runpod  # type: ignore

sys.path.insert(0, "/app")
sys.path.insert(0, "/runpod-volume")
sys.path.insert(0, ".")


def _volume_root() -> pathlib.Path:
    for p in ["/runpod-volume", "/workspace"]:
        if pathlib.Path(p).exists():
            return pathlib.Path(p)
    return pathlib.Path("/tmp")


def handler(job: dict) -> dict:
    inp = job.get("input", {}) or {}
    s3_key = inp.get("s3_key") or inp.get("s3Key") or ""
    proxy_key = inp.get("proxy_key") or inp.get("proxyKey") or ""
    if not s3_key:
        return {"error": "missing s3_key", "input": inp}
    if not proxy_key:
        proxy_key = s3_key.replace("1080p", "480p_proxy") if "1080p" in s3_key else s3_key.rsplit(".", 1)[0] + "_480p_proxy.mp4"

    # Try volume path first (fast, no S3 download)
    # When running on RunPod worker, volume is at /runpod-volume
    try:
        # Import here so handler can run even if app not yet copied (fallback to ffmpeg direct)
        try:
            from app.proxy import transcode_480p_s3

            result = transcode_480p_s3(s3_key, proxy_key)
            # also try to update Neon Job if DATABASE_URL present
            try:
                import uuid

                from app.database import SessionLocal
                from app.models import Asset
                from app.models import Job

                film_id = inp.get("film_id") or s3_key.split("/")[1] if "/" in s3_key else "unknown"
                db = SessionLocal()
                try:
                    job_row = Job(id=uuid.uuid4(), kind="proxy", status="completed", runpod_job_id=str(job.get("id", "")))  # type: ignore
                    db.add(job_row)
                    # upsert proxy asset
                    existing = db.query(Asset).filter(Asset.s3_key == proxy_key).first()
                    if not existing:
                        # find source film_id
                        src = db.query(Asset).filter(Asset.s3_key == s3_key).first()
                        fid = src.film_id if src else film_id
                        asset = Asset(film_id=fid, kind="proxy_480p", runpod_volume_id=os.getenv("RUNPOD_VOLUME_ID", "tn1qxkkw94"), s3_key=proxy_key, s3_endpoint=os.getenv("AWS_S3_ENDPOINT", "https://s3api-eu-ro-1.runpod.io"), datacenter=os.getenv("AWS_S3_REGION", "EU-RO-1"), status="available")  # type: ignore
                        db.add(asset)
                    else:
                        existing.status = "available"  # type: ignore
                    db.commit()
                finally:
                    db.close()
            except Exception as e:
                result["neon_warn"] = str(e)
            return {"s3_key": s3_key, "proxy_key": proxy_key, "result": result}
        except ImportError as ie:
            # fallback: direct ffmpeg if app not bundled
            raise ie
    except Exception as e:
        # Direct ffmpeg fallback without app.proxy (volume mount available)
        try:
            src_vol = _volume_root() / s3_key
            dst_vol = _volume_root() / proxy_key
            dst_vol.parent.mkdir(parents=True, exist_ok=True)
            if src_vol.exists():
                # transcode directly on volume
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-hwaccel",
                    "cuda",
                    "-hwaccel_output_format",
                    "cuda",
                    "-i",
                    str(src_vol),
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
                    str(dst_vol),
                ]
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                if r.returncode != 0 and "cuda" in r.stderr.lower():
                    # fallback libx264
                    cmd2 = ["ffmpeg", "-y", "-i", str(src_vol), "-vf", "scale=854:480", "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-g", "30", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", str(dst_vol)]
                    r = subprocess.run(cmd2, capture_output=True, text=True, timeout=600)
                if r.returncode != 0:
                    return {"error": f"ffmpeg failed: {r.stderr[-2000:]}", "s3_key": s3_key, "proxy_key": proxy_key}
                probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,codec_name,avg_frame_rate", "-of", "default=noprint_wrappers=1", str(dst_vol)], capture_output=True, text=True, timeout=10)
                return {"s3_key": s3_key, "proxy_key": proxy_key, "fallback": "ffmpeg", "probe": probe.stdout, "error_fallback": str(e)}
            else:
                return {"error": f"src not on volume and app import failed: {e}", "s3_key": s3_key, "proxy_key": proxy_key, "volume_root": str(_volume_root())}
        except Exception as e2:
            return {"error": str(e2), "original_error": str(e), "s3_key": s3_key, "proxy_key": proxy_key}


if __name__ == "__main__":
    import runpod  # type: ignore

    runpod.serverless.start({"handler": handler})
