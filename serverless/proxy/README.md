# Splicer Proxy — RunPod Serverless `splicer-proxy` (ADA_24, tn1qxkkw94)

## Build & push (once, from repo root)

```bash
# 1. Build locally (or via RunPod GitHub integration)
docker build -f serverless/proxy/Dockerfile -t ghcr.io/<your-gh>/splicer-proxy:latest .

# 2. Push to GHCR (or DockerHub)
echo $GHCR_PAT | docker login ghcr.io -u <your-gh> --password-stdin
docker push ghcr.io/<your-gh>/splicer-proxy:latest

# 3. Update RunPod endpoint to new image
# via MCP:
# printf '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"update-endpoint","arguments":{"endpointId":"2dmz605z5wxjo1","imageName":"ghcr.io/<your-gh>/splicer-proxy:latest"}}}' | RUNPOD_API_KEY=... npx -y @runpod/mcp-server@latest

# Or via console: Serverless → splicer-proxy → Manage → Edit → Image → ghcr.io/<your-gh>/splicer-proxy:latest
```

## Run (queue)

```bash
curl -s -X POST https://api.runpod.ai/v2/2dmz605z5wxjo1/run \
  -H "Authorization: Bearer $RUNPOD_API_KEY" -H "Content-Type: application/json" \
  -d '{"input":{"s3_key":"films/945c6475-a629-4140-9968-9135d716565d/I.Am.Legend.1080p.mp4"}}' | jq .

curl -s https://api.runpod.ai/v2/2dmz605z5wxjo1/status/<job_id> -H "Authorization: Bearer $RUNPOD_API_KEY" | jq .

# Verify
aws s3 ls --endpoint-url https://s3api-eu-ro-1.runpod.io --region EU-RO-1 s3://tn1qxkkw94/films/945c6475-a629-4140-9968-9135d716565d/ | grep 480p
ffprobe ... # 854×480 h264 24000/1001

# Inngest path (no direct RunPod call): POST /api/uploads/{id}/complete already fires film/proxy.requested (concurrency 3) with s3_key
```

## Handler contract

Input: `{"s3_key": "films/<id>/I.Am.Legend.1080p.mp4", "proxy_key": "films/<id>/480p_proxy.mp4" (optional), "film_id": "945c..." }`
Output: `{"s3_key","proxy_key","result":{"probe":...}}` or `{"error":...}` — also mirrors Job/Asset to Neon if `DATABASE_URL` present.

## Notes

- Base `runpod/base:0.6.2-cuda12.1.0` already has `ffmpeg n9.0` with `nvdec/nvenc` + `cuda`; handler tries `scale_npp=854:480 h264_nvenc vbr_hq cq23 g30` then falls back `libx264`.
- Volume `tn1qxkkw94` mounted at `/runpod-volume` (Serverless) — handler checks there first, else S3 streaming fallback `_download_s3_with_fallback` (fixes `HeadObject 403` via `list`+`get_object`).
- For local dev without RunPod, `app/proxy.py` fallback `libx264` was validated 30s `3619024` bytes `854×480` sample.
