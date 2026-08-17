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
import time
from typing import Any

import runpod
import PyNvVideoCodec as nvc
import boto3
from botocore.exceptions import ClientError
import logfire

# Add parent directory to path for lib imports
import sys
sys.path.insert(0, '/app')

# Configure Logfire with service name and system metrics
logfire.configure(
    service_name="splicer-proxy",
    console=False,  # Don't output to console, use Logfire UI
)
logfire.instrument_system_metrics()

logfire.info("Proxy handler initialized. PyNvVideoCodec loaded successfully.")


def get_s3_client():
    """Get configured S3 client for Runpod network volume."""
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("AWS_S3_ENDPOINT", "https://s3api-eu-ro-1.runpod.io"),
        region_name=os.getenv("AWS_S3_REGION", "EU-RO-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )


def download_from_s3(key: str, local_path: str) -> None:
    """Download file from S3 to local path."""
    bucket = os.getenv("RUNPOD_VOLUME_ID", "tn1qxkkw94")
    
    with logfire.span("s3_download", key=key, bucket=bucket) as span:
        start_time = time.perf_counter()
        
        s3_client = get_s3_client()
        pathlib.Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        
        try:
            response = s3_client.get_object(Bucket=bucket, Key=key)
            with open(local_path, "wb") as f:
                f.write(response["Body"].read())
            
            size_bytes = pathlib.Path(local_path).stat().st_size
            size_mb = size_bytes / (1024 * 1024)
            duration_sec = time.perf_counter() - start_time
            
            span.set_attributes({
                "size_bytes": size_bytes,
                "size_mb": round(size_mb, 2),
                "duration_sec": round(duration_sec, 2),
                "speed_mbps": round(size_mb / duration_sec, 2) if duration_sec > 0 else 0,
            })
            
            logfire.info(f"S3 download complete: {size_mb:.2f} MB in {duration_sec:.2f}s")
        except ClientError as e:
            duration_sec = time.perf_counter() - start_time
            span.set_attribute("error", str(e))
            span.set_attribute("duration_sec", round(duration_sec, 2))
            logfire.error(f"S3 download failed: {e}")
            raise


def upload_to_s3(local_path: str, key: str) -> int:
    """Upload file to S3, return size in bytes."""
    bucket = os.getenv("RUNPOD_VOLUME_ID", "tn1qxkkw94")
    size_bytes = pathlib.Path(local_path).stat().st_size
    size_mb = size_bytes / (1024 * 1024)
    
    with logfire.span("s3_upload", key=key, bucket=bucket, size_mb=round(size_mb, 2)) as span:
        start_time = time.perf_counter()
        
        s3_client = get_s3_client()
        
        try:
            s3_client.upload_file(str(local_path), bucket, key)
            duration_sec = time.perf_counter() - start_time
            
            span.set_attributes({
                "size_bytes": size_bytes,
                "duration_sec": round(duration_sec, 2),
                "speed_mbps": round(size_mb / duration_sec, 2) if duration_sec > 0 else 0,
            })
            
            logfire.info(f"S3 upload complete: {size_mb:.2f} MB in {duration_sec:.2f}s")
            return size_bytes
        except ClientError as e:
            duration_sec = time.perf_counter() - start_time
            span.set_attribute("error", str(e))
            span.set_attribute("duration_sec", round(duration_sec, 2))
            logfire.error(f"S3 upload failed: {e}")
            raise


def get_video_metadata(video_path: str) -> dict[str, Any]:
    """Get video metadata using PyNvVideoCodec decoder."""
    with logfire.span("get_metadata", video_path=video_path) as span:
        start_time = time.perf_counter()
        
        try:
            decoder = nvc.PyNvDecoder(video_path, gpuid=0)
            
            width = decoder.Width()
            height = decoder.Height()
            num_frames = decoder.Numframes()
            framerate = decoder.Framerate()
            
            duration_seconds = num_frames / framerate if framerate > 0 else 0.0
            probe_time = time.perf_counter() - start_time
            
            metadata = {
                "width": width,
                "height": height,
                "duration_seconds": round(duration_seconds, 2),
                "num_frames": num_frames,
                "framerate": round(framerate, 2),
            }
            
            span.set_attributes({
                "width": width,
                "height": height,
                "duration_seconds": round(duration_seconds, 2),
                "num_frames": num_frames,
                "framerate": round(framerate, 2),
                "probe_time_sec": round(probe_time, 3),
            })
            
            return metadata
        except Exception as e:
            span.set_attribute("error", str(e))
            logfire.error(f"Failed to probe video metadata: {e}")
            raise RuntimeError(f"Failed to probe video metadata: {e}")


def transcode_to_480p(input_path: str, output_path: str) -> dict[str, Any]:
    """Transcode video to 480p using PyNvVideoCodec hardware acceleration."""
    encode_config = {
        "codec": "h264",
        "s": "854x480",
        "preset": "P4",
        "rc": "vbr",
        "bitrate": "2M",
        "maxbitrate": "4M",
        "gop": "60",
        "bf": "0",
    }
    
    with logfire.span(
        "transcode",
        codec=encode_config["codec"],
        resolution=encode_config["s"],
        preset=encode_config["preset"],
        bitrate=encode_config["bitrate"],
    ) as span:
        start_time = time.perf_counter()
        
        try:
            transcoder = nvc.Transcoder(
                input_path,
                output_path,
                gpu_id=0,
                cuda_context=0,
                cuda_stream=0,
                **encode_config
            )
            
            transcoder.transcode_with_mux()
            transcode_time = time.perf_counter() - start_time
            
            # Get output metadata
            metadata = get_video_metadata(output_path)
            
            # Calculate transcoding speed
            total_frames = metadata["num_frames"]
            fps_achieved = total_frames / transcode_time if transcode_time > 0 else 0
            
            span.set_attributes({
                "duration_sec": round(transcode_time, 2),
                "output_frames": total_frames,
                "fps_achieved": round(fps_achieved, 1),
                "output_width": metadata["width"],
                "output_height": metadata["height"],
                "output_duration_sec": metadata["duration_seconds"],
            })
            
            logfire.info(
                f"Transcode complete: {metadata['width']}x{metadata['height']}, "
                f"{metadata['duration_seconds']:.2f}s, {total_frames} frames @ {fps_achieved:.1f} fps"
            )
            
            return {
                "width": metadata["width"],
                "height": metadata["height"],
                "duration_seconds": metadata["duration_seconds"],
            }
            
        except Exception as e:
            transcode_time = time.perf_counter() - start_time
            span.set_attribute("error", str(e))
            span.set_attribute("duration_sec", round(transcode_time, 2))
            logfire.error(f"PyNvVideoCodec transcode failed: {e}")
            raise RuntimeError(f"PyNvVideoCodec transcode failed: {e}")


def handler(job: dict) -> dict[str, Any]:
    """RunPod serverless handler for proxy generation."""
    request_id = job.get("id", "unknown")
    
    with logfire.span("proxy_generation", job_id=request_id) as main_span:
        logfire.info("Handler started")
        
        inp = job.get("input", {})
        s3_key = inp.get("s3_key")
        proxy_key = inp.get("proxy_key")

        if not s3_key:
            logfire.error("Missing s3_key in input")
            return {"error": "missing s3_key in input"}

        if not proxy_key:
            if s3_key.endswith("/source.mp4"):
                proxy_key = s3_key.replace("/source.mp4", "/proxy_480p.mp4")
            else:
                base = s3_key.rsplit(".", 1)[0]
                proxy_key = f"{base}_480p_proxy.mp4"
        
        main_span.set_attributes({
            "s3_key": s3_key,
            "proxy_key": proxy_key,
        })
        
        logfire.info(f"Input: s3_key={s3_key}, output: proxy_key={proxy_key}")

        try:
            job_start = time.perf_counter()
            
            with tempfile.TemporaryDirectory() as tmpdir:
                # Download source video
                input_path = os.path.join(tmpdir, "source.mp4")
                download_from_s3(s3_key, input_path)

                # Transcode to 480p
                output_path = os.path.join(tmpdir, "proxy_480p.mp4")
                metadata = transcode_to_480p(input_path, output_path)

                # Upload to S3
                size_bytes = upload_to_s3(output_path, proxy_key)

                total_time = time.perf_counter() - job_start
                
                result = {
                    "proxy_key": proxy_key,
                    "width": metadata["width"],
                    "height": metadata["height"],
                    "duration_seconds": metadata["duration_seconds"],
                    "size_bytes": size_bytes,
                }
                
                main_span.set_attributes({
                    "total_duration_sec": round(total_time, 2),
                    "output_size_bytes": size_bytes,
                    "output_size_mb": round(size_bytes / (1024 * 1024), 2),
                    "status": "completed",
                })
                
                logfire.info(f"Handler completed successfully in {total_time:.2f}s")
                return result
        
        except Exception as e:
            job_time = time.perf_counter() - job_start
            main_span.set_attributes({
                "error": str(e),
                "duration_sec": round(job_time, 2),
                "status": "failed",
            })
            logfire.error(f"Handler failed with error: {e}")
            return {"error": str(e)}


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
