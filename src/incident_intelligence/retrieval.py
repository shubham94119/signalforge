"""Hybrid, ACL-aware, incident-relative temporal retrieval baseline."""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Iterable, Mapping, Sequence

from .graph import GraphIndex
from .ingestion import EvidenceStore
from .models import Evidence, QueryContext, RetrievalResult
from .policy import PolicyEnforcer


_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.:/-]*")
_STOPWORDS = frozenset(
    "a an and are as at be by for from how in is it of on or that the to was what when why with".split()
)


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(token for token in _TOKEN_RE.findall(text.lower()) if token not in _STOPWORDS)


def _overlap_score(query: Sequence[str], text: Sequence[str]) -> float:
    if not query or not text:
        return 0.0
    query_counts = Counter(query)
    text_counts = Counter(text)
    overlap = sum(min(count, text_counts[token]) for token, count in query_counts.items())
    return min(1.0, overlap / max(1, sum(query_counts.values())))


def lexical_score(query: str, evidence: Evidence) -> float:
    query_tokens = _tokens(query)
    body = _overlap_score(query_tokens, _tokens(evidence.content))
    title = _overlap_score(query_tokens, _tokens(evidence.title))
    return min(1.0, body * 0.75 + title * 0.25)


def semantic_baseline_score(query: str, evidence: Evidence) -> float:
    """Deterministic semantic proxy; replace with an embedding adapter later."""

    query_tokens = set(_tokens(query))
    evidence_tokens = set(_tokens(f"{evidence.title} {evidence.content}"))
    if not query_tokens or not evidence_tokens:
        return 0.0
    return len(query_tokens.intersection(evidence_tokens)) / len(query_tokens.union(evidence_tokens))


def temporal_score(query: QueryContext, evidence: Evidence) -> float:
    """Score evidence by incident-relative event time, never ingest time alone."""

    event_time = evidence.event_time
    if event_time is None:
        return 0.25 if query.target_time is None else 0.0
    if query.window_start and query.window_end:
        if evidence.event_time_end and evidence.event_time_start:
            if evidence.event_time_end >= query.window_start and evidence.event_time_start <= query.window_end:
                return 1.0
        elif query.window_start <= event_time <= query.window_end:
            return 1.0
    if query.target_time is None:
        return 0.5
    distance_hours = abs((event_time - query.target_time).total_seconds()) / 3600
    # Deployments and incidents remain useful over a wider window than alerts.
    tau_hours = 168.0 if evidence.source_type in {"incident", "postmortem"} else 72.0
    return math.exp(-distance_hours / tau_hours)


class HybridRetriever:
    """Reference retriever with hard authorization filtering before ranking."""

    def __init__(
        self,
        store: EvidenceStore,
        policy: PolicyEnforcer,
        graph: GraphIndex | None = None,
    ) -> None:
        self.store = store
        self.policy = policy
        self.graph = graph

    def _candidate_filter(self, evidence: Evidence, query: QueryContext) -> bool:
        if evidence.tenant_id != query.tenant_id:
            return False
        if query.environment and evidence.environment and evidence.environment != query.environment:
            return False
        if query.source_types and evidence.source_type not in query.source_types:
            return False
        if query.service_ids and evidence.service_ids and not query.service_ids.intersection(evidence.service_ids):
            # Graph expansion may recover dependencies; leave those candidates in
            # only when a graph index is available.
            if self.graph is None:
                return False
        return self.policy.authorize(evidence, query.identity).allowed

    def search(self, query: QueryContext, limit: int = 10) -> list[RetrievalResult]:
        if limit < 1:
            raise ValueError("limit must be positive")
        candidates = [item for item in self.store.all() if self._candidate_filter(item, query)]
        ranked: list[RetrievalResult] = []
        for evidence in candidates:
            lexical = lexical_score(query.text, evidence)
            semantic = semantic_baseline_score(query.text, evidence)
            graph_score = 0.0
            graph_reason: str | None = None
            if self.graph is not None:
                graph_score, graph_reason = self.graph.score(evidence, query.service_ids)
            temporal = temporal_score(query, evidence)
            quality = evidence.quality_score * (0.5 if evidence.superseded else 1.0)
            final = (
                0.30 * lexical
                + 0.25 * semantic
                + 0.15 * graph_score
                + 0.20 * temporal
                + 0.10 * quality
            )
            reasons: list[str] = []
            if lexical > 0:
                reasons.append("lexical match")
            if semantic > 0:
                reasons.append("semantic overlap")
            if graph_reason:
                reasons.append(graph_reason)
            if temporal >= 0.8:
                reasons.append("inside or near incident window")
            if evidence.superseded:
                reasons.append("superseded evidence penalty")
            ranked.append(
                RetrievalResult(
                    evidence=evidence,
                    score=final,
                    channel_scores={
                        "lexical": lexical,
                        "semantic": semantic,
                        "graph": graph_score,
                        "temporal": temporal,
                        "quality": quality,
                    },
                    reasons=tuple(reasons),
                )
            )
        ranked.sort(key=lambda item: (-item.score, item.evidence.evidence_id))
        return ranked[:limit]
