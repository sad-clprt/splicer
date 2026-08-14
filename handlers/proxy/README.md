# Splicer Proxy Handler

Transcodes 1080p source videos to 480p proxies for faster editing.

## Build & Deploy

```bash
# Build image
cd handlers/proxy
docker build --platform linux/amd64 -t <dockerhub-username>/splicer-proxy:v1 .

# Push to Docker Hub
docker push <dockerhub-username>/splicer-proxy:v1

# Update RunPod endpoint
# Go to RunPod console → Serverless → splicer-proxy
# Update template image to: <dockerhub-username>/splicer-proxy:v1
```

## Environment Variables

Set these in the RunPod endpoint configuration:

```
AWS_ACCESS_KEY_ID=user_30hSgon3u92BEzzXGYKLcuSxPun
AWS_SECRET_ACCESS_KEY=rps_CCV7L1IW2IA54IS71IFYNHK482HZ441U774LZSM61oi7au
AWS_S3_ENDPOINT=https://s3api-eu-ro-1.runpod.io
AWS_S3_REGION=EU-RO-1
RUNPOD_VOLUME_ID=tn1qxkkw94
```

## Input

```json
{
  "s3_key": "films/<film_id>/source_1080p.mp4",
  "proxy_key": "films/<film_id>/proxy_480p.mp4"  // optional
}
```

## Output

```json
{
  "proxy_key": "films/<film_id>/proxy_480p.mp4",
  "width": 854,
  "height": 480,
  "duration_seconds": 123.45,
  "size_bytes": 12345678
}
```

## GPU Usage

- Uses `h264_nvenc` for GPU-accelerated encoding on ADA_24
- Falls back to `libx264` CPU encoding if NVENC unavailable
- Target: 854x480 @ 2Mbps VBR, GOP=30, CRF=23
