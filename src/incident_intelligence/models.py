"""Canonical, provider-neutral domain models.

These models intentionally keep ACL and event-time fields next to the evidence
record. Every downstream projection must preserve those fields or reject the
record; losing them would make safe retrieval impossible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, FrozenSet, Mapping, Optional, Sequence
from uuid import uuid4


UTC = timezone.utc


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Return a timezone-aware UTC datetime, or ``None``.

    Naive timestamps are accepted at the ingestion boundary and interpreted as
    UTC. Source adapters should preferably provide timezone-aware values.
    """

    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True)
class ACL:
    """Source permission state attached to one authorization unit."""

    tenant_id: str
    allowed_principals: FrozenSet[str] = frozenset()
    denied_principals: FrozenSet[str] = frozenset()
    public_within_tenant: bool = False
    source_policy_version: str = "unknown"
    resolved_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("ACL tenant_id is required")
        object.__setattr__(self, "resolved_at", as_utc(self.resolved_at))
        object.__setattr__(self, "expires_at", as_utc(self.expires_at))


@dataclass
class Evidence:
    """Canonical evidence object shared by all retrieval channels."""

    evidence_id: str
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
    ingested_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    source_url: Optional[str] = None
    service_ids: tuple[str, ...] = ()
    environment: Optional[str] = None
    entity_ids: tuple[str, ...] = ()
    content_hash: Optional[str] = None
    quality_score: float = 1.0
    superseded: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        required = {
            "evidence_id": self.evidence_id,
            "tenant_id": self.tenant_id,
            "source_type": self.source_type,
            "source_instance": self.source_instance,
            "source_object_id": self.source_object_id,
            "source_version": self.source_version,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"Missing required evidence fields: {', '.join(missing)}")
        if self.acl.tenant_id != self.tenant_id:
            raise ValueError("Evidence and ACL tenant_id must match")
        start = as_utc(self.event_time_start)
        end = as_utc(self.event_time_end)
        if start and end and start > end:
            raise ValueError("event_time_start must not be after event_time_end")
        self.event_time_start = start
        self.event_time_end = end
        self.source_updated_at = as_utc(self.source_updated_at)
        self.ingested_at = as_utc(self.ingested_at) or datetime.now(UTC)
        self.service_ids = tuple(sorted(set(self.service_ids)))
        self.entity_ids = tuple(sorted(set(self.entity_ids)))
        self.quality_score = max(0.0, min(1.0, float(self.quality_score)))

    @property
    def event_time(self) -> Optional[datetime]:
        """A stable event midpoint for ranking when a range is available."""

        if self.event_time_start and self.event_time_end:
            return self.event_time_start + (self.event_time_end - self.event_time_start) / 2
        return self.event_time_start or self.event_time_end


@dataclass(frozen=True)
class IdentityContext:
    """Identity and group context resolved from the trusted identity provider."""

    tenant_id: str
    user_id: str
    groups: FrozenSet[str] = frozenset()
    roles: FrozenSet[str] = frozenset()
    policy_versions: Mapping[str, str] = field(default_factory=dict)

    def principal_ids(self) -> FrozenSet[str]:
        """Return canonical and compatibility principal forms.

        Source adapters should emit canonical ``user:``, ``group:``, and
        ``role:`` IDs. Raw values are also included during the migration period
        so an adapter can be introduced without silently denying all users.
        """

        principals = {
            f"tenant:{self.tenant_id}",
            f"user:{self.user_id}",
            self.user_id,
        }
        for group in self.groups:
            principals.update({f"group:{group}", group})
        for role in self.roles:
            principals.update({f"role:{role}", role})
        return frozenset(principals)


@dataclass(frozen=True)
class QueryContext:
    """Normalized investigation query and incident context."""

    tenant_id: str
    text: str
    identity: IdentityContext
    target_time: Optional[datetime] = None
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    service_ids: FrozenSet[str] = frozenset()
    environment: Optional[str] = None
    source_types: FrozenSet[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("Query text is required")
        if self.identity.tenant_id != self.tenant_id:
            raise ValueError("Query and identity tenant_id must match")
        target = as_utc(self.target_time)
        start = as_utc(self.window_start)
        end = as_utc(self.window_end)
        if start and end and start > end:
            raise ValueError("window_start must not be after window_end")
        object.__setattr__(self, "target_time", target)
        object.__setattr__(self, "window_start", start)
        object.__setattr__(self, "window_end", end)


@dataclass(frozen=True)
class RetrievalResult:
    evidence: Evidence
    score: float
    channel_scores: Mapping[str, float]
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Claim:
    claim_id: str
    text: str
    citation_ids: tuple[str, ...] = ()
    claim_type: str = "observed"
    material: bool = True


@dataclass(frozen=True)
class AnswerDraft:
    answer_id: str
    claims: Sequence[Claim]
    summary: str = ""


@dataclass(frozen=True)
class CitationValidationResult:
    valid: bool
    issues: tuple[str, ...] = ()
    accepted_claim_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class FeedbackRecord:
    """User feedback kept separate from evidence content."""

    tenant_id: str
    user_id: str
    answer_id: str
    kind: str
    claim_id: Optional[str] = None
    comment: Optional[str] = None
    feedback_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        allowed = {"useful", "incorrect", "outdated", "unsupported", "access_sensitive"}
        if self.kind not in allowed:
            raise ValueError(f"feedback kind must be one of: {', '.join(sorted(allowed))}")
        if not self.tenant_id or not self.user_id or not self.answer_id:
            raise ValueError("feedback tenant_id, user_id, and answer_id are required")
        object.__setattr__(self, "created_at", as_utc(self.created_at) or datetime.now(UTC))
