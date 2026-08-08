"""JSONL fixture connector for replaying source changes locally."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from incident_intelligence.models import ACL
from incident_intelligence.ingestion import SourceRecord

from .base import ConnectorBatch, ConnectorHealth, SourceChange


def _dt(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


def source_record_from_mapping(payload: dict[str, Any]) -> SourceRecord:
    acl_payload = payload["acl"]
    acl = ACL(
        tenant_id=acl_payload["tenant_id"],
        allowed_principals=frozenset(acl_payload.get("allowed_principals", [])),
        denied_principals=frozenset(acl_payload.get("denied_principals", [])),
        public_within_tenant=bool(acl_payload.get("public_within_tenant", False)),
        source_policy_version=acl_payload.get("source_policy_version", "unknown"),
        resolved_at=_dt(acl_payload.get("resolved_at")),
        expires_at=_dt(acl_payload.get("expires_at")),
    )
    return SourceRecord(
        tenant_id=payload["tenant_id"],
        source_type=payload["source_type"],
        source_instance=payload["source_instance"],
        source_object_id=payload["source_object_id"],
        source_version=payload["source_version"],
        title=payload.get("title", ""),
        content=payload["content"],
        acl=acl,
        event_time_start=_dt(payload.get("event_time_start")),
        event_time_end=_dt(payload.get("event_time_end")),
        source_updated_at=_dt(payload.get("source_updated_at")),
        source_url=payload.get("source_url"),
        service_ids=tuple(payload.get("service_ids", [])),
        environment=payload.get("environment"),
        entity_ids=tuple(payload.get("entity_ids", [])),
        quality_score=float(payload.get("quality_score", 1.0)),
        metadata=payload.get("metadata", {}),
    )


class JsonlConnector:
    """Read one JSON object per line; cursor is the next line offset."""

    def __init__(self, path: str | Path, source_instance: str) -> None:
        self.path = Path(path)
        self.source_instance = source_instance

    def _lines(self) -> list[str]:
        return self.path.read_text(encoding="utf-8").splitlines()

    def discover(self) -> tuple[tuple[dict[str, Any], ...], Optional[str]]:
        """Return source payloads and the initial cursor for a backfill."""

        return tuple(json.loads(line) for line in self._lines()), "0"

    def fetch(self, source_object_id: str, source_version: str) -> dict[str, Any]:
        for line in self._lines():
            payload = json.loads(line)
            candidate = payload.get("record", payload)
            if (
                candidate.get("source_object_id") == source_object_id
                and candidate.get("source_version") == source_version
            ):
                return candidate
        raise KeyError(f"source object not found: {source_object_id}:{source_version}")

    def fetch_acl(self, source_object_id: str, source_version: str) -> ACL:
        return self.normalize(self.fetch(source_object_id, source_version)).acl

    def normalize(self, source_object: dict[str, Any]) -> SourceRecord:
        return source_record_from_mapping(source_object)

    def poll(self, cursor: Optional[str], limit: int = 100) -> ConnectorBatch:
        lines = self._lines()
        start = int(cursor or "0")
        selected = lines[start : start + limit]
        changes: list[SourceChange] = []
        for line in selected:
            payload = json.loads(line)
            kind = payload.get("kind", "upsert")
            if kind == "delete":
                changes.append(
                    SourceChange(
                        kind="delete",
                        source_object_id=payload["source_object_id"],
                        source_version=payload["source_version"],
                    )
                )
            else:
                record_payload = payload.get("record", payload)
                record = self.normalize(record_payload)
                changes.append(
                    SourceChange(
                        kind="upsert",
                        source_object_id=record.source_object_id,
                        source_version=record.source_version,
                        record=record,
                    )
                )
        next_offset = start + len(selected)
        return ConnectorBatch(tuple(changes), str(next_offset), next_offset < len(lines))

    def health(self) -> ConnectorHealth:
        if not self.path.exists():
            return ConnectorHealth(self.source_instance, "error", message="fixture not found")
        return ConnectorHealth(self.source_instance, "ok", cursor_lag=0)
