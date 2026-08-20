"""
Modal Volume helpers — upload/download/list for splicer-films.

Replaces previous S3 storage (lib/tools/storage.py).
Volumes are persisted, shared across all Functions/Apps in workspace,
and mounted at /films in containers.

CLI equivalents:
    modal volume create splicer-films
    modal volume ls splicer-films /i_am_legend...
    modal volume put splicer-films films/i_am_legend.../source.mp4 /i_am_legend.../source.mp4 -f
    modal volume get splicer-films /i_am_legend.../proxy_480p.mp4 ./films/.../proxy_480p.mp4

SDK:
    vol = modal.Volume.from_name("splicer-films", create_if_missing=True)
    vol.batch_upload() / vol.read_file() / vol.listdir()
"""

from pathlib import Path
from typing import List, Dict, Any

from ..film_manager import get_film_dir, get_manifest

VOLUME_NAME = "splicer-films"
VOLUME_MOUNT = "/films"


def get_volume():
    """Get Modal Volume handle (lazy, create if missing)."""
    try:
        import modal
    except ImportError as e:
        raise ImportError("modal is required. Install with `pip install modal`") from e
    return modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)


def ensure_volume() -> Any:
    """Ensure volume exists and return handle."""
    vol = get_volume()
    # Hydrate by listing (forces creation check)
    try:
        vol.listdir("/")
    except Exception:
        pass
    return vol


def list_volume(path: str = "/") -> List[Dict[str, Any]]:
    """List files under path on Volume. Returns list of FileEntry dicts."""
    vol = get_volume()
    try:
        entries = vol.listdir(path)
        return [{"path": e.path, "type": e.type, "size": e.size} for e in entries]
    except Exception as e:
        return [{"error": str(e)}]


def volume_exists(volume_path: str) -> bool:
    """Check if file/dir exists on Volume."""
    vol = get_volume()
    # Normalize to absolute
    if not volume_path.startswith("/"):
        volume_path = f"/{volume_path}"
    try:
        entries = vol.listdir(volume_path)
        return len(entries) > 0
    except Exception:
        # Try parent listing
        try:
            parent = "/".join(volume_path.split("/")[:-1]) or "/"
            name = volume_path.split("/")[-1]
            entries = vol.listdir(parent)
            return any(name in e.path for e in entries)
        except Exception:
            return False


def upload_file(local_path: str | Path, volume_path: str, force: bool = True) -> Dict[str, Any]:
    """
    Upload single file to Volume.

    Args:
        local_path: Local file path
        volume_path: Destination path inside Volume (e.g. "i_am_legend_ed264664/source.mp4" or "/i_am_legend.../source.mp4")
        force: Overwrite if exists

    Returns:
        dict with volume_path, size
    """
    local_path = Path(local_path)
    if not local_path.exists():
        raise FileNotFoundError(f"Local file not found: {local_path}")
    if not local_path.is_file():
        raise ValueError(f"Not a file: {local_path}")

    if not volume_path.startswith("/"):
        volume_path = f"/{volume_path}"

    vol = get_volume()
    # Use batch_upload for single file
    with vol.batch_upload(force=force) as batch:
        batch.put_file(str(local_path), volume_path)

    size_bytes = local_path.stat().st_size
    return {"volume_path": volume_path, "size_bytes": size_bytes, "size_mb": round(size_bytes / (1024 * 1024), 2)}


def upload_directory(local_dir: str | Path, volume_prefix: str = "/", force: bool = True) -> Dict[str, Any]:
    """
    Upload directory recursively to Volume.

    Args:
        local_dir: Local directory path
        volume_prefix: Prefix inside Volume (e.g. "/i_am_legend...")
        force: Overwrite

    Returns:
        dict with count, total_bytes
    """
    local_dir = Path(local_dir)
    if not local_dir.exists() or not local_dir.is_dir():
        raise ValueError(f"Not a directory: {local_dir}")
    if not volume_prefix.startswith("/"):
        volume_prefix = f"/{volume_prefix}"
    if not volume_prefix.endswith("/"):
        volume_prefix += "/"

    vol = get_volume()
    count = 0
    total = 0
    with vol.batch_upload(force=force) as batch:
        # batch.put_directory uploads recursively
        batch.put_directory(str(local_dir), volume_prefix)
        # Count for return (approx)
        for p in local_dir.rglob("*"):
            if p.is_file():
                count += 1
                total += p.stat().st_size
    return {"volume_prefix": volume_prefix, "count": count, "total_bytes": total}


def upload_film(film_id: str, files: List[str] | None = None, force: bool = True) -> Dict[str, Any]:
    """
    Upload film source and metadata to Volume.

    By default uploads:
      - source.mp4 (or manifest files.source)
      - manifest.json
    Optionally upload full film dir if files is None and you call upload_directory.

    Args:
        film_id: Film identifier
        files: List of filenames relative to film_dir to upload (e.g. ["source.mp4", "manifest.json"]). If None, auto-detects.
        force: Overwrite

    Returns:
        dict with uploaded keys
    """
    film_dir = get_film_dir(film_id)
    if not film_dir.exists():
        raise FileNotFoundError(f"Film dir not found: {film_dir}")

    vol = get_volume()
    uploaded = []

    if files is None:
        # Auto: source + manifest
        manifest = get_manifest(film_id)
        source_file = manifest.get("files", {}).get("source") or "source.mp4"
        files = [source_file, "manifest.json"]
        # Only keep existing files
        files = [f for f in files if (film_dir / f).exists()]

    with vol.batch_upload(force=force) as batch:
        for fname in files:
            local = film_dir / fname
            if not local.exists():
                continue
            remote = f"/{film_id}/{fname}"
            batch.put_file(str(local), remote)
            uploaded.append({"local": str(local), "remote": remote, "size": local.stat().st_size})

    return {"film_id": film_id, "uploaded": uploaded, "volume": VOLUME_NAME}


def upload_canary(force: bool = True) -> Dict[str, Any]:
    """Upload the 1.6GB canary film i_am_legend_ed264664/source.mp4 to Volume."""
    # Auto-detect canary film dir
    canary = Path("films/i_am_legend_ed264664")
    if not canary.exists():
        # Try via film_manager list
        from ..film_manager import list_films
        films = list_films()
        if films:
            film_id = films[0]["film_id"]
        else:
            raise FileNotFoundError("No films found in films/ index")
    else:
        film_id = "i_am_legend_ed264664"
    return upload_film(film_id, force=force)


def download_file(volume_path: str, local_path: str | Path) -> Dict[str, Any]:
    """
    Download file from Volume to local path.

    Args:
        volume_path: Path inside Volume (e.g. "/i_am_legend.../proxy_480p.mp4")
        local_path: Local destination

    Returns:
        dict with local_path, size_bytes
    """
    if not volume_path.startswith("/"):
        volume_path = f"/{volume_path}"
    local_path = Path(local_path)
    local_path.parent.mkdir(parents=True, exist_ok=True)

    vol = get_volume()
    with open(local_path, "wb") as f:
        for chunk in vol.read_file(volume_path):
            f.write(chunk)

    size_bytes = local_path.stat().st_size
    return {"volume_path": volume_path, "local_path": str(local_path), "size_bytes": size_bytes}


def download_film_file(film_id: str, filename: str, dest: str | Path | None = None) -> Path:
    """
    Download single film file from Volume to local film_dir.

    Args:
        film_id: Film identifier
        filename: File name inside film dir (e.g. "proxy_480p.mp4")
        dest: Optional local destination override

    Returns:
        Local path
    """
    volume_path = f"/{film_id}/{filename}"
    if dest is None:
        dest = get_film_dir(film_id) / filename
    result = download_file(volume_path, dest)
    return Path(result["local_path"])


def sync_manifest_to_volume(film_id: str) -> Dict[str, Any]:
    """Sync local manifest.json to Volume after updates (so Modal functions see latest)."""
    film_dir = get_film_dir(film_id)
    manifest_path = film_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    return upload_file(manifest_path, f"/{film_id}/manifest.json")
