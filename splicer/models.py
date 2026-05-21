import json
from datetime import UTC
from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class LogEntry(Base):
    __tablename__ = "logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    level = Column(String, nullable=False)
    logger = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    context = Column(Text, nullable=False, default="{}")
    project = Column(String, nullable=False)
    env = Column(String, nullable=False)
    trace_id = Column(String, nullable=True)
    span_id = Column(String, nullable=True)
    request_id = Column(String, nullable=True)

    @classmethod
    def from_record(cls, record: dict) -> LogEntry:
        context = record.get("context", {})
        if not isinstance(context, str):
            context = json.dumps(context, default=str)
        return cls(
            timestamp=record.get("timestamp", datetime.now(UTC)),
            level=record["level"],
            logger=record.get("logger", "root"),
            message=record.get("message", ""),
            context=context,
            project=record.get("project", ""),
            env=record.get("env", ""),
            trace_id=record.get("trace_id"),
            span_id=record.get("span_id"),
            request_id=record.get("request_id"),
        )
