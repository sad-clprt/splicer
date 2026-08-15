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
import tempfile
import logging
from typing import Any

import runpod
import boto3
from botocore.client import Config
import PyNvVideoCodec as nvc


# Configure structured logging
def setup_logger(log_level=logging.INFO):
    """Configure logger for RunPod serverless worker."""
    log_format = logging.Formatter(
        '%(asctime)s - %(levelname)s - [Request: %(request_id)s] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    logger = logging.getLogger("splicer_proxy")
    logger.setLevel(log_level)

    # Console handler (RunPod captures stdout/stderr)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)

    if not logger.handlers:
        logger.addHandler(console_handler)

    return logger


# Initialize logger
logger = setup_logger(log_level=logging.INFO)
logger = logging.LoggerAdapter(logger, {"request_id": "N/A"})

logger.info("Proxy handler initialized. PyNvVideoCodec loaded successfully.")


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


def download_from_s3(s3_client, key: str, local_path: str, logger) -> None:
    """Download file from S3 to local path."""
    bucket = os.getenv("RUNPOD_VOLUME_ID", "tn1qxkkw94")
    logger.info(f"Starting download from S3: s3://{bucket}/{key}")
    try:
        s3_client.download_file(bucket, key, local_path)
        size_mb = pathlib.Path(local_path).stat().st_size / (1024 * 1024)
        logger.info(f"Download complete: {size_mb:.2f} MB")
    except Exception as e:
        logger.error(f"Download failed: {e}", exc_info=True)
        raise


def upload_to_s3(s3_client, local_path: str, key: str, logger) -> int:
    """Upload file to S3, return size in bytes."""
    bucket = os.getenv("RUNPOD_VOLUME_ID", "tn1qxkkw94")
    size_bytes = pathlib.Path(local_path).stat().st_size
    size_mb = size_bytes / (1024 * 1024)
    logger.info(f"Starting upload to S3: s3://{bucket}/{key} ({size_mb:.2f} MB)")
    try:
        s3_client.upload_file(local_path, bucket, key)
        logger.info(f"Upload complete: {key}")
        return size_bytes
    except Exception as e:
        logger.error(f"Upload failed: {e}", exc_info=True)
        raise


def get_video_metadata(video_path: str) -> dict[str, Any]:
    """Get video metadata using PyNvVideoCodec decoder."""
    try:
        # Create decoder to probe the video
        decoder = nvc.CreateDecoder(video_path, gpu_id=0)
        
        # Get stream info
        width = decoder.Width()
        height = decoder.Height()
        num_frames = decoder.Numframes()
        framerate = decoder.Framerate()
        
        # Calculate duration
        duration_seconds = num_frames / framerate if framerate > 0 else 0.0
        
        return {
            "width": width,
            "height": height,
            "duration_seconds": duration_seconds,
            "num_frames": num_frames,
            "framerate": framerate,
        }
    except Exception as e:
        raise RuntimeError(f"Failed to probe video metadata: {e}")


def transcode_to_480p(input_path: str, output_path: str, logger) -> dict[str, Any]:
    """Transcode video to 480p using PyNvVideoCodec hardware acceleration.
    
    Returns metadata about the output video.
    """
    # Encode configuration for 480p H.264
    encode_config = {
        "codec": "h264",           # H.264 codec
        "s": "854x480",            # 480p resolution
        "preset": "P4",            # Quality preset (P4 = balanced quality/speed)
        "rc": "vbr",               # Variable bitrate
        "bitrate": "2M",           # Average bitrate 2 Mbps
        "maxbitrate": "4M",        # Max bitrate 4 Mbps
        "gop": "60",               # GOP size (2 seconds at 30fps)
        "bf": "0",                 # No B-frames for faster seeking
    }
    
    try:
        logger.info(f"Starting transcode to 480p (preset: {encode_config['preset']}, bitrate: {encode_config['bitrate']})")
        
        # Create transcoder with muxing (handles demux, decode, encode, mux in one)
        transcoder = nvc.Transcoder(
            input_path,
            output_path,
            gpu_id=0,
            cuda_context=0,
            cuda_stream=0,
            **encode_config
        )
        
        # Run the full transcode with muxing
        transcoder.transcode_with_mux()
        
        # Get metadata from output file
        metadata = get_video_metadata(output_path)
        
        logger.info(
            f"Transcode complete: {metadata['width']}x{metadata['height']}, "
            f"{metadata['duration_seconds']:.2f}s, "
            f"{metadata['num_frames']} frames @ {metadata['framerate']:.2f} fps"
        )
        
        return {
            "width": metadata["width"],
            "height": metadata["height"],
            "duration_seconds": metadata["duration_seconds"],
        }
        
    except Exception as e:
        logger.error(f"PyNvVideoCodec transcode failed: {e}", exc_info=True)
        raise RuntimeError(f"PyNvVideoCodec transcode failed: {e}")


def handler(job: dict) -> dict[str, Any]:
    """RunPod serverless handler for proxy generation."""
    # Extract request_id from job for structured logging
    request_id = job.get("id", "unknown")
    
    # Create request-specific logger
    request_logger = logging.LoggerAdapter(
        logging.getLogger("splicer_proxy"),
        {"request_id": request_id}
    )
    
    request_logger.info("Handler started")
    
    inp = job.get("input", {})
    s3_key = inp.get("s3_key")
    proxy_key = inp.get("proxy_key")

    if not s3_key:
        request_logger.error("Missing s3_key in input")
        return {"error": "missing s3_key in input"}

    # Generate proxy key if not provided
    if not proxy_key:
        # Replace source.mp4 with proxy_480p.mp4
        if s3_key.endswith("/source.mp4"):
            proxy_key = s3_key.replace("/source.mp4", "/proxy_480p.mp4")
        else:
            base = s3_key.rsplit(".", 1)[0]
            proxy_key = f"{base}_480p_proxy.mp4"
    
    request_logger.info(f"Input: s3_key={s3_key}, output: proxy_key={proxy_key}")

    try:
        s3_client = get_s3_client()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Download source video
            input_path = os.path.join(tmpdir, "source.mp4")
            download_from_s3(s3_client, s3_key, input_path, request_logger)

            # Transcode to 480p using PyNvVideoCodec
            output_path = os.path.join(tmpdir, "proxy_480p.mp4")
            metadata = transcode_to_480p(input_path, output_path, request_logger)

            # Upload to S3
            size_bytes = upload_to_s3(s3_client, output_path, proxy_key, request_logger)

            result = {
                "proxy_key": proxy_key,
                "width": metadata["width"],
                "height": metadata["height"],
                "duration_seconds": metadata["duration_seconds"],
                "size_bytes": size_bytes,
            }
            
            request_logger.info(f"Handler completed successfully: {result}")
            return result
    
    except Exception as e:
        request_logger.error(f"Handler failed with error: {e}", exc_info=True)
        return {"error": str(e)}


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
