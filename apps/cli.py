"""Small local demo for the foundation slice.

Run with ``PYTHONPATH=src python -m apps.cli demo`` after installing the
package, or use the equivalent PowerShell environment variable.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from incident_intelligence import (
    ACL,
    CitationValidator,
    EvaluationDataset,
    EvaluationGate,
    EvaluationRunner,
    GroundedTriageService,
    HybridRetriever,
    HybridRetriever,
    IdentityContext,
    InMemoryEvidenceStore,
    IngestionPipeline,
    PolicyEnforcer,
    QueryContext,
    SourceRecord,
)


def run_demo() -> None:
    now = datetime.now(timezone.utc)
    store = InMemoryEvidenceStore()
    pipeline = IngestionPipeline(store)
    pipeline.ingest(
        SourceRecord(
            tenant_id="demo",
            source_type="deployment",
            source_instance="demo-source",
            source_object_id="deploy-42",
            source_version="1",
            title="Payments deployment 42",
            content="Payments deployed version 42 before latency increased.",
            acl=ACL("demo", frozenset({"user:alice"}), source_policy_version="v1"),
            event_time_start=now,
            event_time_end=now,
            service_ids=("payments",),
            environment="prod",
        )
    )


def run_demo_evaluation() -> None:
    now = datetime.now(timezone.utc)
    store = InMemoryEvidenceStore()
    IngestionPipeline(store).ingest(
        SourceRecord(
            tenant_id="demo",
            source_type="deployment",
            source_instance="demo-source",
            source_object_id="deploy-42",
            source_version="1",
            title="Payments deployment 42",
            content="Payments deployed version 42 before latency increased.",
            acl=ACL("demo", frozenset({"user:alice"}), source_policy_version="v1"),
            event_time_start=now,
            event_time_end=now,
            service_ids=("payments",),
            environment="prod",
        )
    )
    policy = PolicyEnforcer()
    service = GroundedTriageService(
        HybridRetriever(store, policy),
        CitationValidator(policy),
    )
    dataset = EvaluationDataset.from_json(Path(__file__).parents[1] / "evals" / "datasets" / "smoke.json")
    report = EvaluationRunner(
        service,
        EvaluationGate(
            min_recall_at_k=1.0,
            min_mrr=1.0,
            min_grounded_response_rate=1.0,
            min_citation_coverage=1.0,
            min_expected_claim_coverage=1.0,
            min_abstention_accuracy=1.0,
            max_forbidden_evidence_rate=0.0,
        ),
    ).run(dataset)
    print(json.dumps(report.to_mapping(), indent=2, default=str))
    if not report.passed:
        raise SystemExit(1)
    query = QueryContext(
        tenant_id="demo",
        text="what changed before payments latency increased",
        identity=IdentityContext("demo", "alice"),
        target_time=now,
        service_ids=frozenset({"payments"}),
    )
    results = HybridRetriever(store, PolicyEnforcer()).search(query)
    print(
        json.dumps(
            [
                {
                    "evidence_id": result.evidence.evidence_id,
                    "score": round(result.score, 4),
                    "reasons": result.reasons,
                }
                for result in results
            ],
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="SignalForge local incident-intelligence tools")
    parser.add_argument("command", choices=("demo", "demo-eval"))
    args = parser.parse_args()
    if args.command == "demo":
        run_demo()
    elif args.command == "demo-eval":
        run_demo_evaluation()


if __name__ == "__main__":
    main()
