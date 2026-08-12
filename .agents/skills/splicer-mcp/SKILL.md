---
name: splicer-mcp
description: Bridge .pi/mcp.json MCPs (runpod, neon, logfire, inngest, runpod-docs) to Muse via bash wrappers
---

# Splicer MCP Bridge

Use when you need live RunPod, Neon, Logfire, Inngest, or RunPod Docs context. Muse has no native MCP client, so call MCPs through bash wrappers and treat `.pi/mcp.json` as the single source of truth.

## Source of Truth

- Config: `.pi/mcp.json` (`mcpServers`: `runpod` stdio, `runpod-docs`/`inngest`/`neon`/`logfire` HTTP, `lifecycle: lazy`).
- Do not duplicate keys in skill files. Read secrets from `.env` at runtime (`RUNPOD_API_KEY`, `DATABASE_URL`, `LOGFIRE_TOKEN`, `INNGEST_*`, `TMDB_*`, etc.). If `.env` lacks a key, fail and ask the user — do not hallucinate.
- `.pi/mcp.json` contains real secrets (`rpa_...`) and is not gitignored — remind to `echo ".pi/" >> .gitignore` before push if not already.

## When to Use

- Before any code that touches RunPod volumes/GPUs, Neon SQL, Logfire traces, Inngest events, or RunPod docs — prefer a live MCP probe over guessing.
- For pipeline steps: proxy 480p, KB enrichment, VLM/TTS workers, health checks.

## How to Call (Muse's MCP Client)

Muse invokes MCPs via `muse.bash` only — no host MCP socket.

### 1. Stdio: `runpod` (`npx -y @runpod/mcp-server@latest`)

Use a JSON-RPC stdio bridge. Example pattern — adapt `method`/`params` to the server's tool list:

```bash
# list tools
printf '{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n' | RUNPOD_API_KEY="$(grep RUNPOD_API_KEY .env | cut -d= -f2-)" npx -y @runpod/mcp-server@latest 2>/dev/null | head -n 200

# call a tool (replace method/params with listing output)
printf '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"<tool_name>","arguments":{}}}\n' | RUNPOD_API_KEY="$RUNPOD_API_KEY" npx -y @runpod/mcp-server@latest
```

For one-off uses, prefer the project's `scripts/` thins (`scripts/upload_srt.py` style) that wrap `boto3` with `RUNPOD_API_KEY` from `.env`.

### 2. HTTP Streamable: `neon`, `logfire`, `runpod-docs`, `inngest`

All are HTTP MCP with `lifecycle: lazy` — start the upstream only when needed.

```bash
# Neon (requires Bearer from .env or .pi/mcp.json — prefer .env)
curl -s -H "Authorization: Bearer $NEON_API_KEY" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' https://mcp.neon.tech/mcp | jq .

# Logfire
curl -s -H "Authorization: Bearer $LOGFIRE_API_KEY" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' https://logfire-us.pydantic.dev/mcp | jq .

# RunPod Docs
curl -s -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' https://docs.runpod.io/mcp | jq .

# Inngest — requires `inngest dev -u http://localhost:8000/api/inngest` running
curl -s -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' http://127.0.0.1:8288/mcp | jq . || echo "start inngest dev first"
```

Tool calls use `tools/call` with the same JSON shape:

```bash
curl -s -H "Authorization: Bearer $NEON_API_KEY" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"<tool>","arguments":{}}}' \
  https://mcp.neon.tech/mcp | jq .
```

## Lazy Lifecycle

- `lazy` means servers are not running until first `tools/list`/`tools/call`. Do not pre-start them.
- `inngest` returns `ECONNREFUSED` until `inngest dev` is up — treat as expected and instruct `inngest dev -u http://localhost:8000/api/inngest` in another terminal.
- Restart Muse after editing `.pi/mcp.json`.

## Hallucination Reduction

- Always verify volume `tn1qxkkw94` exists via `runpod` or `boto3 list_objects_v2` before claiming proxy paths.
- Verify Neon state via `neon` MCP or `psql $DATABASE_URL -c "select count(*) from films"` — do not invent IDs. Canary is `945c6475-a629-4140-9968-9135d716565d`.
- Verify Logfire ingestion via `logfire` MCP before claiming traces.
- Prefer `.codegraph` for code search before any MCP.

## Fallbacks Without MCP

If an MCP host is down, use direct APIs already in repo: `boto3` for RunPod S3 (`app/s3.py`), `psycopg`/`SQLAlchemy` for Neon (`app/database.py`), `logfire` SDK for traces, and plain `curl` to Inngest `http://localhost:8000/api/inngest`.
