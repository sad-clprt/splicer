"""Splicer proxy handler for RunPod Serverless.

Input: {
    "s3_key": "films/<film_id>/source.mp4",
    "proxy_key": "films/<film_id>/proxy_480p.mp4" (optional)
}

Output: {
    "proxy_key": "films/<film_id>/proxy_480p.mp4",
    "width": 854,
    "height": 480,
    "duration_seconds": 123.45,
    "size_bytes": 12345678
}
"""

import os
import pathlib
import subprocess
import json
import tempfile
from typing import Any

import runpod
import boto3
from botocore.client import Config


def get_s3_client():
    """Create S3 client for RunPod network volume storage."""
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("AWS_S3_ENDPOINT", "https://s3api-eu-ro-1.runpod.io"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_S3_REGION", "EU-RO-1"),
        config=Config(signature_version="s3v4"),
    )


def download_from_s3(s3_client, key: str, local_path: str) -> None:
    """Download file from S3 to local path."""
    bucket = os.getenv("RUNPOD_VOLUME_ID", "tn1qxkkw94")
    s3_client.download_file(bucket, key, local_path)


def upload_to_s3(s3_client, local_path: str, key: str) -> int:
    """Upload file to S3, return size in bytes."""
    bucket = os.getenv("RUNPOD_VOLUME_ID", "tn1qxkkw94")
    s3_client.upload_file(local_path, bucket, key)
    return pathlib.Path(local_path).stat().st_size


def probe_video(video_path: str) -> dict[str, Any]:
    """Get video metadata using ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration,codec_name,avg_frame_rate",
        "-show_entries", "format=duration",
        "-of", "json",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")

    data = json.loads(result.stdout)
    stream = data.get("streams", [{}])[0]
    format_data = data.get("format", {})

    return {
        "width": stream.get("width"),
        "height": stream.get("height"),
        "codec": stream.get("codec_name"),
        "duration_seconds": float(format_data.get("duration", 0)),
    }


def transcode_to_480p(input_path: str, output_path: str) -> None:
    """Transcode video to 480p using hardware acceleration."""
    # Try NVENC first (GPU encoding)
    cmd_nvenc = [
        "ffmpeg", "-y",
        "-hwaccel", "cuda",
        "-hwaccel_output_format", "cuda",
        "-i", input_path,
        "-vf", "scale_cuda=854:480",
        "-c:v", "h264_nvenc",
        "-preset", "p4",  # quality preset
        "-rc", "vbr",
        "-cq", "23",
        "-b:v", "2M",
        "-maxrate", "4M",
        "-g", "30",  # GOP size
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        output_path,
    ]

    result = subprocess.run(cmd_nvenc, capture_output=True, text=True, timeout=600)

    # Fallback to CPU encoding if NVENC fails
    if result.returncode != 0 and "cuda" in result.stderr.lower():
        print(f"NVENC failed, falling back to libx264: {result.stderr[:500]}")
        cmd_cpu = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vf", "scale=854:480",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-g", "30",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            output_path,
        ]
        result = subprocess.run(cmd_cpu, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-2000:]}")


def handler(job: dict) -> dict[str, Any]:
    """RunPod serverless handler for proxy generation."""
    inp = job.get("input", {})
    s3_key = inp.get("s3_key")
    proxy_key = inp.get("proxy_key")

    if not s3_key:
        return {"error": "missing s3_key in input"}

    # Generate proxy key if not provided
    if not proxy_key:
        if "1080p" in s3_key:
            proxy_key = s3_key.replace("1080p", "480p_proxy")
        else:
            base = s3_key.rsplit(".", 1)[0]
            proxy_key = f"{base}_480p_proxy.mp4"

    s3_client = get_s3_client()

    with tempfile.TemporaryDirectory() as tmpdir:
        # Download source video
        input_path = os.path.join(tmpdir, "source.mp4")
        print(f"Downloading {s3_key}...")
        download_from_s3(s3_client, s3_key, input_path)

        # Transcode to 480p
        output_path = os.path.join(tmpdir, "proxy_480p.mp4")
        print(f"Transcoding to 480p...")
        transcode_to_480p(input_path, output_path)

        # Probe output video
        print(f"Probing output video...")
        metadata = probe_video(output_path)

        # Upload to S3
        print(f"Uploading to {proxy_key}...")
        size_bytes = upload_to_s3(s3_client, output_path, proxy_key)

        return {
            "proxy_key": proxy_key,
            "width": metadata["width"],
            "height": metadata["height"],
            "duration_seconds": metadata["duration_seconds"],
            "size_bytes": size_bytes,
        }


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
