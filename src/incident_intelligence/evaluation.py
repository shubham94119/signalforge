"""Versioned evaluation datasets, metrics, and promotion gates.

The runner evaluates the complete local pipeline for a particular persona. It
does not assume that a high aggregate score is safe: forbidden evidence and
abstention failures remain explicit hard-gate metrics.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .answering import GroundedResponse, GroundedTriageService
from .models import IdentityContext, QueryContext


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    query: QueryContext
    relevant_evidence_ids: frozenset[str] = frozenset()
    forbidden_evidence_ids: frozenset[str] = frozenset()
    must_abstain: bool = False
    expected_claim_terms: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationDataset:
    version: str
    cases: tuple[EvaluationCase, ...]
    split: str = "test"

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "EvaluationDataset":
        cases: list[EvaluationCase] = []
        for item in payload.get("cases", []):
            query_payload = item["query"]
            identity = IdentityContext(
                tenant_id=query_payload["tenant_id"],
                user_id=query_payload["user_id"],
                groups=frozenset(query_payload.get("groups", [])),
                roles=frozenset(query_payload.get("roles", [])),
                policy_versions=query_payload.get("policy_versions", {}),
            )
            query = QueryContext(
                tenant_id=query_payload["tenant_id"],
                text=query_payload["text"],
                identity=identity,
                target_time=_dt(query_payload.get("target_time")),
                window_start=_dt(query_payload.get("window_start")),
                window_end=_dt(query_payload.get("window_end")),
                service_ids=frozenset(query_payload.get("service_ids", [])),
                environment=query_payload.get("environment"),
                source_types=frozenset(query_payload.get("source_types", [])),
            )
            cases.append(
                EvaluationCase(
                    case_id=item["case_id"],
                    query=query,
                    relevant_evidence_ids=frozenset(item.get("relevant_evidence_ids", [])),
                    forbidden_evidence_ids=frozenset(item.get("forbidden_evidence_ids", [])),
                    must_abstain=bool(item.get("must_abstain", False)),
                    expected_claim_terms=tuple(item.get("expected_claim_terms", [])),
                    metadata=item.get("metadata", {}),
                )
            )
        if not cases:
            raise ValueError("Evaluation dataset must contain at least one case")
        return cls(version=str(payload.get("version", "unversioned")), cases=tuple(cases), split=payload.get("split", "test"))

    @classmethod
    def from_json(cls, path: str | Path) -> "EvaluationDataset":
        return cls.from_mapping(json.loads(Path(path).read_text(encoding="utf-8")))

    def to_mapping(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "split": self.split,
            "cases": [
                {
                    "case_id": case.case_id,
                    "query": {
                        "tenant_id": case.query.tenant_id,
                        "user_id": case.query.identity.user_id,
                        "groups": sorted(case.query.identity.groups),
                        "roles": sorted(case.query.identity.roles),
                        "policy_versions": dict(case.query.identity.policy_versions),
                        "text": case.query.text,
                        "target_time": case.query.target_time.isoformat() if case.query.target_time else None,
                        "window_start": case.query.window_start.isoformat() if case.query.window_start else None,
                        "window_end": case.query.window_end.isoformat() if case.query.window_end else None,
                        "service_ids": sorted(case.query.service_ids),
                        "environment": case.query.environment,
                        "source_types": sorted(case.query.source_types),
                    },
                    "relevant_evidence_ids": sorted(case.relevant_evidence_ids),
                    "forbidden_evidence_ids": sorted(case.forbidden_evidence_ids),
                    "must_abstain": case.must_abstain,
                    "expected_claim_terms": list(case.expected_claim_terms),
                    "metadata": dict(case.metadata),
                }
                for case in self.cases
            ],
        }


@dataclass(frozen=True)
class EvaluationCaseResult:
    case_id: str
    status: str
    retrieved_evidence_ids: tuple[str, ...]
    recall_at_k: float | None
    reciprocal_rank: float | None
    citation_coverage: float
    expected_claim_coverage: float
    forbidden_evidence_ids: tuple[str, ...]
    abstention_correct: bool
    latency_ms: float
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvaluationGate:
    """Thresholds for a safe promotion decision."""

    min_recall_at_k: float = 0.85
    min_mrr: float = 0.75
    min_grounded_response_rate: float = 0.95
    min_citation_coverage: float = 0.95
    min_expected_claim_coverage: float = 0.0
    min_abstention_accuracy: float = 0.95
    max_forbidden_evidence_rate: float = 0.0
    max_p95_latency_ms: float = 12_000.0

    def evaluate(self, metrics: Mapping[str, float]) -> tuple[bool, tuple[str, ...]]:
        checks = (
            ("recall_at_k", metrics.get("recall_at_k", 0.0), ">=", self.min_recall_at_k),
            ("mrr", metrics.get("mrr", 0.0), ">=", self.min_mrr),
            ("grounded_response_rate", metrics.get("grounded_response_rate", 0.0), ">=", self.min_grounded_response_rate),
            ("citation_coverage", metrics.get("citation_coverage", 0.0), ">=", self.min_citation_coverage),
            ("expected_claim_coverage", metrics.get("expected_claim_coverage", 0.0), ">=", self.min_expected_claim_coverage),
            ("abstention_accuracy", metrics.get("abstention_accuracy", 0.0), ">=", self.min_abstention_accuracy),
            ("forbidden_evidence_rate", metrics.get("forbidden_evidence_rate", 0.0), "<=", self.max_forbidden_evidence_rate),
            ("p95_latency_ms", metrics.get("p95_latency_ms", float("inf")), "<=", self.max_p95_latency_ms),
        )
        failures: list[str] = []
        for name, actual, operator, target in checks:
            passed = actual >= target if operator == ">=" else actual <= target
            if not passed:
                failures.append(f"{name}={actual:.4f} fails {operator} {target:.4f}")
        return not failures, tuple(failures)


@dataclass(frozen=True)
class EvaluationReport:
    dataset_version: str
    split: str
    case_results: tuple[EvaluationCaseResult, ...]
    metrics: Mapping[str, float]
    passed: bool
    gate_failures: tuple[str, ...]
    generated_at: datetime

    def to_mapping(self) -> dict[str, Any]:
        return {
            "dataset_version": self.dataset_version,
            "split": self.split,
            "generated_at": self.generated_at.isoformat(),
            "passed": self.passed,
            "gate_failures": list(self.gate_failures),
            "metrics": dict(self.metrics),
            "cases": [
                {
                    "case_id": result.case_id,
                    "status": result.status,
                    "retrieved_evidence_ids": list(result.retrieved_evidence_ids),
                    "recall_at_k": result.recall_at_k,
                    "reciprocal_rank": result.reciprocal_rank,
                    "citation_coverage": result.citation_coverage,
                    "expected_claim_coverage": result.expected_claim_coverage,
                    "forbidden_evidence_ids": list(result.forbidden_evidence_ids),
                    "abstention_correct": result.abstention_correct,
                    "latency_ms": result.latency_ms,
                    "issues": list(result.issues),
                }
                for result in self.case_results
            ],
        }


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


class EvaluationRunner:
    def __init__(self, service: GroundedTriageService, gate: EvaluationGate | None = None) -> None:
        self.service = service
        self.gate = gate or EvaluationGate()

    def run(self, dataset: EvaluationDataset, limit: int = 10) -> EvaluationReport:
        results: list[EvaluationCaseResult] = []
        for case in dataset.cases:
            started = time.perf_counter()
            response: GroundedResponse = self.service.investigate(case.query, limit=limit)
            latency_ms = (time.perf_counter() - started) * 1000
            retrieved = tuple(card.evidence_id for card in response.evidence)
            relevant_ranked = [item for item in retrieved if item in case.relevant_evidence_ids]
            recall = None
            reciprocal_rank = None
            if case.relevant_evidence_ids:
                recall = len(set(relevant_ranked)) / len(case.relevant_evidence_ids)
                reciprocal_rank = 1.0 / (retrieved.index(relevant_ranked[0]) + 1) if relevant_ranked else 0.0

            material_claims = [claim for claim in response.claims if claim.material]
            citation_coverage = (
                len([claim for claim in material_claims if claim.citation_ids]) / len(material_claims)
                if material_claims
                else (1.0 if case.must_abstain else 0.0)
            )
            expected_covered = sum(
                1
                for term in case.expected_claim_terms
                if any(term.lower() in claim.text.lower() for claim in response.claims)
            )
            expected_coverage = expected_covered / len(case.expected_claim_terms) if case.expected_claim_terms else 1.0
            forbidden = tuple(sorted(set(retrieved).intersection(case.forbidden_evidence_ids)))
            abstained = response.status in {"insufficient_evidence", "evidence_only"}
            abstention_correct = abstained if case.must_abstain else not abstained
            issues: list[str] = []
            if forbidden:
                issues.append("forbidden evidence was returned")
            if case.must_abstain and not abstained:
                issues.append("case required abstention")
            if not case.must_abstain and abstained and case.relevant_evidence_ids:
                issues.append("case abstained despite expected evidence")
            if expected_coverage < 1.0:
                issues.append("expected claim terms were not all present")
            results.append(
                EvaluationCaseResult(
                    case_id=case.case_id,
                    status=response.status,
                    retrieved_evidence_ids=retrieved,
                    recall_at_k=recall,
                    reciprocal_rank=reciprocal_rank,
                    citation_coverage=citation_coverage,
                    expected_claim_coverage=expected_coverage,
                    forbidden_evidence_ids=forbidden,
                    abstention_correct=abstention_correct,
                    latency_ms=latency_ms,
                    issues=tuple(issues),
                )
            )

        retrieval_cases = [result for result in results if result.recall_at_k is not None]
        non_abstain_cases = [result for result in results if result.case_id and result.status != "insufficient_evidence"]
        grounded_cases = [result for result in results if result.status == "grounded"]
        forbidden_count = sum(bool(result.forbidden_evidence_ids) for result in results)
        latencies = sorted(result.latency_ms for result in results)
        p95_index = min(len(latencies) - 1, max(0, int(len(latencies) * 0.95) - 1)) if latencies else 0
        metrics = {
            "recall_at_k": _mean([result.recall_at_k for result in retrieval_cases if result.recall_at_k is not None]),
            "mrr": _mean([result.reciprocal_rank for result in retrieval_cases if result.reciprocal_rank is not None]),
            "grounded_response_rate": len(grounded_cases) / len(non_abstain_cases) if non_abstain_cases else 1.0,
            "citation_coverage": _mean([result.citation_coverage for result in results]),
            "expected_claim_coverage": _mean([result.expected_claim_coverage for result in results]),
            "abstention_accuracy": _mean([1.0 if result.abstention_correct else 0.0 for result in results]),
            "forbidden_evidence_rate": forbidden_count / len(results) if results else 0.0,
            "p95_latency_ms": latencies[p95_index] if latencies else 0.0,
        }
        passed, failures = self.gate.evaluate(metrics)
        return EvaluationReport(
            dataset_version=dataset.version,
            split=dataset.split,
            case_results=tuple(results),
            metrics=metrics,
            passed=passed,
            gate_failures=failures,
            generated_at=datetime.now(timezone.utc),
        )
