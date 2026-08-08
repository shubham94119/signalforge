"""Replayable connector and checkpoint contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from incident_intelligence.ingestion import IngestionPipeline, SourceRecord
from incident_intelligence.models import ACL


@dataclass(frozen=True)
class SourceChange:
    kind: str
    source_object_id: str
    source_version: str
    record: Optional[SourceRecord] = None

    def __post_init__(self) -> None:
        if self.kind not in {"upsert", "delete"}:
            raise ValueError("SourceChange kind must be upsert or delete")
        if self.kind == "upsert" and self.record is None:
            raise ValueError("upsert changes require a source record")
        if self.kind == "delete" and self.record is not None:
            raise ValueError("delete changes cannot include a source record")


@dataclass(frozen=True)
class ConnectorBatch:
    changes: tuple[SourceChange, ...]
    next_cursor: Optional[str]
    has_more: bool = False


@dataclass(frozen=True)
class ConnectorHealth:
    source_instance: str
    status: str
    cursor_lag: Optional[int] = None
    message: Optional[str] = None


@dataclass(frozen=True)
class ConnectorCheckpoint:
    source_instance: str
    cursor: Optional[str]
    status: str = "ok"
    error: Optional[str] = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class ConnectorRunStats:
    source_instance: str
    processed: int
    upserts: int
    deletes: int
    failed: int
    next_cursor: Optional[str]


class SourceConnector(Protocol):
    source_instance: str

    def discover(self) -> tuple[tuple[dict[str, Any], ...], Optional[str]]: ...

    def fetch(self, source_object_id: str, source_version: str) -> dict[str, Any]: ...

    def fetch_acl(self, source_object_id: str, source_version: str) -> ACL: ...

    def normalize(self, source_object: dict[str, Any]) -> SourceRecord: ...

    def poll(self, cursor: Optional[str], limit: int = 100) -> ConnectorBatch: ...

    def health(self) -> ConnectorHealth: ...


class CheckpointStore(Protocol):
    def load_checkpoint(self, source_instance: str) -> Optional[dict[str, object]]: ...

    def save_checkpoint(
        self,
        source_instance: str,
        cursor: Optional[str],
        status: str = "ok",
        error: Optional[str] = None,
    ) -> None: ...


class InMemoryCheckpointStore:
    def __init__(self) -> None:
        self._checkpoints: dict[str, dict[str, object]] = {}

    def load_checkpoint(self, source_instance: str) -> Optional[dict[str, object]]:
        return self._checkpoints.get(source_instance)

    def save_checkpoint(
        self,
        source_instance: str,
        cursor: Optional[str],
        status: str = "ok",
        error: Optional[str] = None,
    ) -> None:
        self._checkpoints[source_instance] = {
            "source_instance": source_instance,
            "cursor": cursor,
            "status": status,
            "error": error,
        }


class IngestionCoordinator:
    """Apply connector changes and advance a checkpoint only after success."""

    def __init__(
        self,
        pipeline: IngestionPipeline,
        checkpoints: CheckpointStore,
    ) -> None:
        self.pipeline = pipeline
        self.checkpoints = checkpoints

    def run_once(self, connector: SourceConnector, limit: int = 100) -> ConnectorRunStats:
        existing = self.checkpoints.load_checkpoint(connector.source_instance)
        cursor = existing.get("cursor") if existing else None
        batch = connector.poll(cursor if isinstance(cursor, str) else None, limit=limit)
        processed = upserts = deletes = failed = 0
        for change in batch.changes:
            try:
                if change.kind == "upsert":
                    assert change.record is not None
                    if change.record.source_instance != connector.source_instance:
                        raise ValueError("source record instance does not match connector")
                    self.pipeline.ingest(change.record)
                    upserts += 1
                else:
                    self.pipeline.tombstone(
                        connector.source_instance,
                        change.source_object_id,
                        change.source_version,
                    )
                    deletes += 1
                processed += 1
            except Exception as exc:  # noqa: BLE001 - checkpoint must remain at last safe event
                failed += 1
                self.checkpoints.save_checkpoint(
                    connector.source_instance,
                    cursor if isinstance(cursor, str) else None,
                    status="error",
                    error=str(exc),
                )
                break
        if failed == 0:
            self.checkpoints.save_checkpoint(connector.source_instance, batch.next_cursor, status="ok")
        return ConnectorRunStats(
            source_instance=connector.source_instance,
            processed=processed,
            upserts=upserts,
            deletes=deletes,
            failed=failed,
            next_cursor=batch.next_cursor if failed == 0 else (cursor if isinstance(cursor, str) else None),
        )
