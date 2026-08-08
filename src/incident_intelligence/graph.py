"""Bounded, provider-neutral graph index used by the retrieval baseline."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Iterable, Mapping

from .models import Evidence


@dataclass(frozen=True)
class GraphRelation:
    source_service: str
    target_service: str
    relation: str
    confidence: float = 1.0


class GraphIndex:
    """A small in-memory projection of typed service relationships.

    It is deliberately bounded and does not infer causality. A graph database
    adapter can implement the same ``score`` contract once the ontology and
    ACL-aware traversal tests are in place.
    """

    def __init__(self) -> None:
        self._adjacency: dict[str, list[GraphRelation]] = defaultdict(list)
        self._evidence_by_service: dict[str, set[str]] = defaultdict(set)

    def add_relation(self, relation: GraphRelation) -> None:
        if relation.source_service and relation.target_service:
            self._adjacency[relation.source_service].append(relation)
            self._adjacency[relation.target_service].append(
                GraphRelation(
                    relation.target_service,
                    relation.source_service,
                    relation.relation,
                    relation.confidence,
                )
            )

    def add_evidence(self, evidence: Evidence) -> None:
        for service_id in evidence.service_ids:
            self._evidence_by_service[service_id].add(evidence.evidence_id)

    def _service_distances(self, services: Iterable[str], max_depth: int = 1) -> Mapping[str, float]:
        distances: dict[str, float] = {}
        queue: deque[tuple[str, int, float]] = deque((service, 0, 1.0) for service in services)
        while queue:
            service, depth, confidence = queue.popleft()
            if service in distances and distances[service] >= confidence:
                continue
            distances[service] = confidence
            if depth >= max_depth:
                continue
            for relation in self._adjacency.get(service, ()):
                next_confidence = confidence * max(0.0, min(1.0, relation.confidence)) * 0.7
                queue.append((relation.target_service, depth + 1, next_confidence))
        return distances

    def score(self, evidence: Evidence, query_services: Iterable[str], max_depth: int = 1) -> tuple[float, str | None]:
        distances = self._service_distances(query_services, max_depth=max_depth)
        matched = [(service, distances[service]) for service in evidence.service_ids if service in distances]
        if not matched:
            return 0.0, None
        service, score = max(matched, key=lambda item: item[1])
        if score >= 0.99:
            return 1.0, f"direct service match: {service}"
        return score, f"graph-neighbor service match: {service}"
