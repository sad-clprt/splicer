import json
import sys
import tomllib
from datetime import UTC
from pathlib import Path

from loguru import logger
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from splicer.models import LogEntry


def _load_project_config() -> dict:
    config_path = Path("project.toml")
    if config_path.exists():
        with open(config_path, "rb") as f:
            return tomllib.load(f)
    return {}


def _get_db_path() -> str:
    config = _load_project_config()
    db_path = config.get("logging", {}).get("logs_db", ".logs/app.db")
    return str(Path(db_path).resolve())


def _write_to_db(engine, record: dict):
    entry = LogEntry.from_record(record)
    with Session(engine) as session:
        session.add(entry)
        session.commit()


def setup_logging():
    config = _load_project_config()
    project_name = config.get("project", {}).get("name", "splicer")
    env_name = config.get("env", {}).get("name", "dev")
    db_path = _get_db_path()

    engine = create_engine(f"sqlite:///{db_path}", echo=False)

    logger.remove()

    logger.add(
        sys.stderr,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        level="DEBUG",
        colorize=True,
    )

    def db_sink(message):
        record = message.record
        extra = record.get("extra", {})
        db_record = {
            "timestamp": record["time"].astimezone(UTC),
            "level": record["level"].name,
            "logger": record["name"],
            "message": record["message"],
            "context": json.dumps(extra, default=str),
            "project": project_name,
            "env": env_name,
            "trace_id": extra.get("trace_id"),
            "span_id": extra.get("span_id"),
            "request_id": extra.get("request_id"),
        }
        _write_to_db(engine, db_record)

    logger.add(db_sink, level="DEBUG", serialize=False)

    logger.info("Logging initialized", project=project_name, env=env_name)
    return logger
