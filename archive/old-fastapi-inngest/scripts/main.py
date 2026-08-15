"""scripts/main.py — consecutive pipeline orchestrator (RunPod-only heavy, SQLite, no ORM).

Single file to reason about the full chain. Calls each phase's `run()` in order;
each phase handles its own S3 idempotency + SQLite mirror.

Usage:
  uv run python scripts/main.py
  uv run python scripts/main.py --film-id 945c6475-a629-4140-9968-9135d716565d
  uv run python scripts/main.py --from-step proxy_generate --to-step safety_run
  uv run python scripts/main.py --skip tts_generate,assemble

All heavy steps (proxy, audio, vlm, tts, assemble, safety) go through RunPod
via scripts/runpod_client. Light steps (kb, script, verify) are local HTTP/SQLite.

SQLite: scripts/application.db (raw sqlite3 via scripts/db.py, WAL, FK on).
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv()

FILM_ID = "945c6475-a629-4140-9968-9135d716565d"

# Ordered pipeline steps: (name, module, func_name)
STEPS = [
    ("check_source", "scripts.check_source", "run"),
    ("proxy_generate", "scripts.proxy_generate", "run"),
    ("proxy_download", "scripts.proxy_download", "run"),
    ("kb_enrich", "scripts.kb_enrich", "run"),
    ("audio_enrich", "scripts.audio_enrich", "run"),
    ("vlm_generate", "scripts.vlm_generate", "run"),
    ("script_generate", "scripts.script_generate", "run"),
    ("tts_generate", "scripts.tts_generate", "run"),
    ("assemble", "scripts.assemble", "run"),
    ("safety_run", "scripts.safety_run", "run"),
    ("verify_final", "scripts.verify_final", "run"),
]


def _import_run(mod: str, func: str):
    import importlib

    m = importlib.import_module(mod)
    return getattr(m, func)


def main() -> None:
    parser = argparse.ArgumentParser(description="Splicer consecutive pipeline (RunPod heavy + SQLite)")
    parser.add_argument("--film-id", default=FILM_ID, help="Canary film UUID")
    parser.add_argument("--from-step", default=None, choices=[s[0] for s in STEPS], help="Start from step (inclusive)")
    parser.add_argument("--to-step", default=None, choices=[s[0] for s in STEPS], help="Stop at step (inclusive)")
    parser.add_argument("--skip", default="", help="Comma-separated steps to skip, e.g. proxy_download,tts_generate")
    parser.add_argument("--proxy-timeout", type=int, default=1800, help="RunPod proxy timeout secs")
    args = parser.parse_args()

    skip_set = {s.strip() for s in args.skip.split(",") if s.strip()}
    names = [s[0] for s in STEPS]
    from_idx = names.index(args.from_step) if args.from_step else 0
    to_idx = names.index(args.to_step) if args.to_step else len(STEPS) - 1

    # init DB once — shared connection for whole run (serial, no concurrency)
    from scripts.db import init_db

    conn = init_db()
    print(f"[main] DB initialized at scripts/application.db film={args.film_id} steps {names[from_idx]}..{names[to_idx]} skip={skip_set or 'none'}")

    failed = None
    for idx in range(from_idx, to_idx + 1):
        name, mod, func = STEPS[idx]
        if name in skip_set:
            print(f"\n[main] SKIP {idx+1}/{len(STEPS)} {name}")
            continue
        print(f"\n[main] === {idx+1}/{len(STEPS)} {name} ({mod}.{func}) ===")
        try:
            fn = _import_run(mod, func)
            # proxy_generate supports timeout kwarg; pass if needed
            if name == "proxy_generate":
                out = fn(film_id=args.film_id, conn=conn, timeout=args.proxy_timeout)
            else:
                # most steps accept (film_id, conn) — try that, fallback to (film_id)
                try:
                    out = fn(film_id=args.film_id, conn=conn)
                except TypeError as e:
                    if "conn" in str(e):
                        out = fn(film_id=args.film_id)
                    else:
                        raise
            # brief preview
            preview = str(out)
            if len(preview) > 800:
                preview = preview[:800] + "..."
            print(f"[main] {name} OK → {preview}")
        except KeyboardInterrupt:
            print(f"\n[main] interrupted at {name}")
            failed = name
            break
        except Exception as e:
            print(f"[main] {name} FAILED: {e}")
            traceback.print_exc()
            failed = name
            # stop consecutive chain on failure — user can --from-step next
            break

    # final state summary via verify if we reached it or not
    if failed:
        print(f"\n[main] pipeline stopped at {failed}. Resume with: uv run python scripts/main.py --film-id {args.film_id} --from-step {failed}")
    else:
        print("\n[main] pipeline complete — verify summary above.")

    try:
        conn.commit()
        conn.close()
    except Exception:
        pass

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
