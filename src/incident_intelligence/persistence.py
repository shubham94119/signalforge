"""SQLite evidence registry used for local durable development.

The production plan calls for PostgreSQL and object storage. SQLite provides a
zero-service implementation of the same lifecycle for the next phase: records
survive process restarts, tombstones are durable, checkpoints can resume a
connector, and an outbox records projection work.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from .ingestion import EvidenceStore
from .models import ACL, Evidence, FeedbackRecord, as_utc


def _timestamp(value: Optional[datetime]) -> Optional[str]:
    return as_utc(value).isoformat() if value else None


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


def _acl_json(acl: ACL) -> str:
    return json.dumps(
        {
            "tenant_id": acl.tenant_id,
            "allowed_principals": sorted(acl.allowed_principals),
            "denied_principals": sorted(acl.denied_principals),
            "public_within_tenant": acl.public_within_tenant,
            "source_policy_version": acl.source_policy_version,
            "resolved_at": _timestamp(acl.resolved_at),
            "expires_at": _timestamp(acl.expires_at),
        },
        sort_keys=True,
    )


def _acl_from_json(payload: str) -> ACL:
    value = json.loads(payload)
    return ACL(
        tenant_id=value["tenant_id"],
        allowed_principals=frozenset(value.get("allowed_principals", [])),
        denied_principals=frozenset(value.get("denied_principals", [])),
        public_within_tenant=bool(value.get("public_within_tenant", False)),
        source_policy_version=value.get("source_policy_version", "unknown"),
        resolved_at=_parse_timestamp(value.get("resolved_at")),
        expires_at=_parse_timestamp(value.get("expires_at")),
    )


class SQLiteEvidenceStore(EvidenceStore):
    """Transactional SQLite registry with checkpoints and an outbox."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._create_schema()

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS evidence (
                    evidence_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_instance TEXT NOT NULL,
                    source_object_id TEXT NOT NULL,
                    source_version TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    acl_json TEXT NOT NULL,
                    event_time_start TEXT,
                    event_time_end TEXT,
                    source_updated_at TEXT,
                    ingested_at TEXT NOT NULL,
                    source_url TEXT,
                    service_ids_json TEXT NOT NULL,
                    environment TEXT,
                    entity_ids_json TEXT NOT NULL,
                    content_hash TEXT,
                    quality_score REAL NOT NULL,
                    superseded INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_evidence_tenant ON evidence (tenant_id);
                CREATE INDEX IF NOT EXISTS idx_evidence_source ON evidence (source_instance, source_object_id);
                CREATE TABLE IF NOT EXISTS tombstones (
                    evidence_id TEXT PRIMARY KEY,
                    deleted_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS connector_checkpoints (
                    source_instance TEXT PRIMARY KEY,
                    cursor TEXT,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS outbox (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    acknowledged_at TEXT
                );
                CREATE TABLE IF NOT EXISTS feedback (
                    feedback_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    answer_id TEXT NOT NULL,
                    claim_id TEXT,
                    kind TEXT NOT NULL,
                    comment TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_feedback_tenant ON feedback (tenant_id, created_at);
                """
            )

    @staticmethod
    def _row_to_evidence(row: sqlite3.Row) -> Evidence:
        return Evidence(
            evidence_id=row["evidence_id"],
            tenant_id=row["tenant_id"],
            source_type=row["source_type"],
            source_instance=row["source_instance"],
            source_object_id=row["source_object_id"],
            source_version=row["source_version"],
            title=row["title"],
            content=row["content"],
            acl=_acl_from_json(row["acl_json"]),
            event_time_start=_parse_timestamp(row["event_time_start"]),
            event_time_end=_parse_timestamp(row["event_time_end"]),
            source_updated_at=_parse_timestamp(row["source_updated_at"]),
            ingested_at=_parse_timestamp(row["ingested_at"]),
            source_url=row["source_url"],
            service_ids=tuple(json.loads(row["service_ids_json"])),
            environment=row["environment"],
            entity_ids=tuple(json.loads(row["entity_ids_json"])),
            content_hash=row["content_hash"],
            quality_score=row["quality_score"],
            superseded=bool(row["superseded"]),
            metadata=json.loads(row["metadata_json"]),
        )

    @staticmethod
    def _evidence_values(evidence: Evidence) -> tuple[Any, ...]:
        return (
            evidence.evidence_id,
            evidence.tenant_id,
            evidence.source_type,
            evidence.source_instance,
            evidence.source_object_id,
            evidence.source_version,
            evidence.title,
            evidence.content,
            _acl_json(evidence.acl),
            _timestamp(evidence.event_time_start),
            _timestamp(evidence.event_time_end),
            _timestamp(evidence.source_updated_at),
            _timestamp(evidence.ingested_at),
            evidence.source_url,
            json.dumps(evidence.service_ids),
            evidence.environment,
            json.dumps(evidence.entity_ids),
            evidence.content_hash,
            evidence.quality_score,
            int(evidence.superseded),
            json.dumps(dict(evidence.metadata), sort_keys=True),
        )

    def upsert(self, evidence: Evidence) -> Evidence:
        values = self._evidence_values(evidence)
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM tombstones WHERE evidence_id = ?", (evidence.evidence_id,))
            self._connection.execute(
                """
                INSERT INTO evidence (
                    evidence_id, tenant_id, source_type, source_instance, source_object_id,
                    source_version, title, content, acl_json, event_time_start, event_time_end,
                    source_updated_at, ingested_at, source_url, service_ids_json, environment,
                    entity_ids_json, content_hash, quality_score, superseded, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(evidence_id) DO UPDATE SET
                    tenant_id=excluded.tenant_id, source_type=excluded.source_type,
                    source_instance=excluded.source_instance, source_object_id=excluded.source_object_id,
                    source_version=excluded.source_version, title=excluded.title, content=excluded.content,
                    acl_json=excluded.acl_json, event_time_start=excluded.event_time_start,
                    event_time_end=excluded.event_time_end, source_updated_at=excluded.source_updated_at,
                    ingested_at=excluded.ingested_at, source_url=excluded.source_url,
                    service_ids_json=excluded.service_ids_json, environment=excluded.environment,
                    entity_ids_json=excluded.entity_ids_json, content_hash=excluded.content_hash,
                    quality_score=excluded.quality_score, superseded=excluded.superseded,
                    metadata_json=excluded.metadata_json
                """,
                values,
            )
            self._connection.execute(
                "INSERT INTO outbox(event_type, evidence_id, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (
                    "upsert",
                    evidence.evidence_id,
                    json.dumps({"content_hash": evidence.content_hash}),
                    _timestamp(datetime.now(timezone.utc)),
                ),
            )
        return evidence

    def get(self, evidence_id: str) -> Optional[Evidence]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM evidence WHERE evidence_id = ?", (evidence_id,)).fetchone()
        return self._row_to_evidence(row) if row else None

    def all(self) -> tuple[Evidence, ...]:
        with self._lock:
            rows = self._connection.execute("SELECT * FROM evidence ORDER BY evidence_id").fetchall()
        return tuple(self._row_to_evidence(row) for row in rows)

    def delete(self, evidence_id: str) -> None:
        now = _timestamp(datetime.now(timezone.utc))
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM evidence WHERE evidence_id = ?", (evidence_id,))
            self._connection.execute(
                "INSERT OR REPLACE INTO tombstones(evidence_id, deleted_at) VALUES (?, ?)",
                (evidence_id, now),
            )
            self._connection.execute(
                "INSERT INTO outbox(event_type, evidence_id, payload_json, created_at) VALUES (?, ?, ?, ?)",
                ("delete", evidence_id, "{}", now),
            )

    def is_tombstoned(self, evidence_id: str) -> bool:
        with self._lock:
            row = self._connection.execute("SELECT 1 FROM tombstones WHERE evidence_id = ?", (evidence_id,)).fetchone()
        return row is not None

    def load_checkpoint(self, source_instance: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._connection.execute(
                "SELECT source_instance, cursor, updated_at, status, error FROM connector_checkpoints WHERE source_instance = ?",
                (source_instance,),
            ).fetchone()
        return dict(row) if row else None

    def save_checkpoint(self, source_instance: str, cursor: Optional[str], status: str = "ok", error: Optional[str] = None) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO connector_checkpoints(source_instance, cursor, updated_at, status, error)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_instance) DO UPDATE SET
                    cursor=excluded.cursor, updated_at=excluded.updated_at,
                    status=excluded.status, error=excluded.error
                """,
                (source_instance, cursor, _timestamp(datetime.utcnow()), status, error),
            )

    def pending_outbox(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT sequence, event_type, evidence_id, payload_json, created_at FROM outbox WHERE acknowledged_at IS NULL ORDER BY sequence LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "sequence": row["sequence"],
                "event_type": row["event_type"],
                "evidence_id": row["evidence_id"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def acknowledge_outbox(self, sequence: int) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE outbox SET acknowledged_at = ? WHERE sequence = ?",
                (_timestamp(datetime.now(timezone.utc)), sequence),
            )

    def record_feedback(self, feedback: FeedbackRecord) -> FeedbackRecord:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO feedback(feedback_id, tenant_id, user_id, answer_id, claim_id, kind, comment, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback.feedback_id,
                    feedback.tenant_id,
                    feedback.user_id,
                    feedback.answer_id,
                    feedback.claim_id,
                    feedback.kind,
                    feedback.comment,
                    _timestamp(feedback.created_at),
                ),
            )
        return feedback

    def list_feedback(self, tenant_id: str, limit: int = 100) -> tuple[FeedbackRecord, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM feedback WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
                (tenant_id, limit),
            ).fetchall()
        return tuple(
            FeedbackRecord(
                feedback_id=row["feedback_id"],
                tenant_id=row["tenant_id"],
                user_id=row["user_id"],
                answer_id=row["answer_id"],
                claim_id=row["claim_id"],
                kind=row["kind"],
                comment=row["comment"],
                created_at=_parse_timestamp(row["created_at"]),
            )
            for row in rows
        )

    def close(self) -> None:
        with self._lock:
            self._connection.close()
