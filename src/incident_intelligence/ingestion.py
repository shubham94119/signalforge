"""Source normalization and an in-memory evidence registry for the pilot.

The registry mirrors the lifecycle contract needed by a durable store:
idempotent upsert, tombstones, content hashes, and permission-bearing records.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping, Optional, Protocol

from .models import ACL, Evidence, FeedbackRecord, as_utc


class IngestionError(ValueError):
    """Raised when a source record cannot be normalized safely."""


class EvidenceStore(Protocol):
    """Storage contract required by ingestion and retrieval projections."""

    def upsert(self, evidence: Evidence) -> Evidence: ...

    def get(self, evidence_id: str) -> Optional[Evidence]: ...

    def all(self) -> tuple[Evidence, ...]: ...

    def delete(self, evidence_id: str) -> None: ...

    def is_tombstoned(self, evidence_id: str) -> bool: ...

    def record_feedback(self, feedback: FeedbackRecord) -> FeedbackRecord: ...

    def list_feedback(self, tenant_id: str, limit: int = 100) -> tuple[FeedbackRecord, ...]: ...


@dataclass(frozen=True)
class SourceRecord:
    tenant_id: str
    source_type: str
    source_instance: str
    source_object_id: str
    source_version: str
    title: str
    content: str
    acl: ACL
    event_time_start: Optional[datetime] = None
    event_time_end: Optional[datetime] = None
    source_updated_at: Optional[datetime] = None
    source_url: Optional[str] = None
    service_ids: tuple[str, ...] = ()
    environment: Optional[str] = None
    entity_ids: tuple[str, ...] = ()
    quality_score: float = 1.0
    metadata: Mapping[str, Any] = field(default_factory=dict)


_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)((?:api[_-]?key|secret|token|password)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)


def redact_sensitive_content(content: str) -> str:
    """Remove common credential-shaped values before indexing.

    This is a baseline defense, not a replacement for source-specific DLP.
    Connectors should add redaction rules for their own payload formats.
    """

    redacted = content
    for pattern in _SECRET_PATTERNS:
        if pattern.pattern.startswith("\\bAKIA"):
            redacted = pattern.sub("[REDACTED_AWS_KEY]", redacted)
        else:
            redacted = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]", redacted)
    return redacted


class InMemoryEvidenceStore:
    """Thread-unsafe reference store used for local development and tests."""

    def __init__(self) -> None:
        self._items: dict[str, Evidence] = {}
        self._tombstones: set[str] = set()
        self._feedback: list[FeedbackRecord] = []

    def upsert(self, evidence: Evidence) -> Evidence:
        if evidence.evidence_id in self._tombstones:
            self._tombstones.remove(evidence.evidence_id)
        self._items[evidence.evidence_id] = evidence
        return evidence

    def get(self, evidence_id: str) -> Optional[Evidence]:
        return self._items.get(evidence_id)

    def all(self) -> tuple[Evidence, ...]:
        return tuple(self._items.values())

    def delete(self, evidence_id: str) -> None:
        self._items.pop(evidence_id, None)
        self._tombstones.add(evidence_id)

    def is_tombstoned(self, evidence_id: str) -> bool:
        return evidence_id in self._tombstones

    def record_feedback(self, feedback: FeedbackRecord) -> FeedbackRecord:
        self._feedback.append(feedback)
        return feedback

    def list_feedback(self, tenant_id: str, limit: int = 100) -> tuple[FeedbackRecord, ...]:
        return tuple(item for item in self._feedback if item.tenant_id == tenant_id)[-limit:]


class IngestionPipeline:
    """Normalize source records and write canonical evidence."""

    def __init__(self, store: EvidenceStore) -> None:
        self.store = store

    def ingest(self, record: SourceRecord) -> Evidence:
        if record.acl.tenant_id != record.tenant_id:
            raise IngestionError("source record and ACL tenants must match")
        if not record.content.strip():
            raise IngestionError("source content is required")

        content = redact_sensitive_content(record.content)
        evidence_id = ":".join(
            (record.source_instance, record.source_object_id, record.source_version)
        )
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        evidence = Evidence(
            evidence_id=evidence_id,
            tenant_id=record.tenant_id,
            source_type=record.source_type,
            source_instance=record.source_instance,
            source_object_id=record.source_object_id,
            source_version=record.source_version,
            title=record.title.strip(),
            content=content,
            acl=record.acl,
            event_time_start=as_utc(record.event_time_start),
            event_time_end=as_utc(record.event_time_end),
            source_updated_at=as_utc(record.source_updated_at),
            source_url=record.source_url,
            service_ids=record.service_ids,
            environment=record.environment,
            entity_ids=record.entity_ids,
            content_hash=content_hash,
            quality_score=record.quality_score,
            metadata=record.metadata,
        )
        return self.store.upsert(evidence)

    def tombstone(self, source_instance: str, source_object_id: str, source_version: str) -> None:
        self.store.delete(":".join((source_instance, source_object_id, source_version)))
