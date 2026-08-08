from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from incident_intelligence import (  # noqa: E402
    ACL,
    AnswerDraft,
    AuthorizedContextBuilder,
    Claim,
    EvaluationCase,
    EvaluationDataset,
    EvaluationGate,
    EvaluationRunner,
    FeedbackRecord,
    GroundedTriageService,
    GenerationConfig,
    HybridRetriever,
    IdentityContext,
    InMemoryEvidenceStore,
    IngestionPipeline,
    ModelBackedAnswerer,
    OpenAICompatibleGateway,
    PolicyEnforcer,
    QueryContext,
    SQLiteEvidenceStore,
    SourceRecord,
)
from incident_intelligence.citations import CitationValidator  # noqa: E402
from incident_intelligence.graph import GraphIndex, GraphRelation  # noqa: E402
from connectors import HttpJsonConnector, IngestionCoordinator, JsonlConnector  # noqa: E402


UTC = timezone.utc


def acl(tenant: str, *principals: str, version: str = "v1") -> ACL:
    return ACL(tenant_id=tenant, allowed_principals=frozenset(principals), source_policy_version=version)


def record(
    object_id: str,
    content: str,
    item_acl: ACL,
    *,
    source_type: str = "deployment",
    service: str = "payments",
    event_time: datetime | None = None,
    environment: str = "prod",
) -> SourceRecord:
    event_time = event_time or datetime.now(UTC)
    return SourceRecord(
        tenant_id=item_acl.tenant_id,
        source_type=source_type,
        source_instance="fixture",
        source_object_id=object_id,
        source_version="1",
        title=object_id,
        content=content,
        acl=item_acl,
        event_time_start=event_time,
        event_time_end=event_time,
        service_ids=(service,),
        environment=environment,
    )


class FoundationTests(unittest.TestCase):
    def test_acl_is_deny_by_default_and_deny_wins(self) -> None:
        policy = PolicyEnforcer()
        item = record("deploy-1", "payment deploy", acl("t1", "group:oncall"))
        allowed = IdentityContext("t1", "u1", groups=frozenset({"oncall"}))
        self.assertTrue(policy.authorize(item_to_evidence(item), allowed).allowed)

        denied_item = item_to_evidence(
            SourceRecord(**{**item.__dict__, "acl": ACL("t1", frozenset({"group:oncall"}), frozenset({"group:oncall"}))})
        )
        self.assertFalse(policy.authorize(denied_item, allowed).allowed)
        outsider = IdentityContext("t1", "u2")
        self.assertFalse(policy.authorize(denied_item, outsider).allowed)

    def test_stale_policy_and_tenant_isolation_fail_closed(self) -> None:
        policy = PolicyEnforcer({"fixture": "v2"})
        item = item_to_evidence(record("deploy-1", "payment deploy", acl("t1", "user:u1")))
        self.assertEqual(policy.authorize(item, IdentityContext("t1", "u1")).reason, "stale_policy")
        other_tenant = item_to_evidence(record("deploy-2", "other", acl("t2", "user:u1")))
        self.assertFalse(policy.authorize(other_tenant, IdentityContext("t1", "u1")).allowed)

    def test_ingestion_redacts_and_tombstones(self) -> None:
        store = InMemoryEvidenceStore()
        pipeline = IngestionPipeline(store)
        item = pipeline.ingest(record("deploy-1", "token=super-secret deploy", acl("t1", "user:u1")))
        self.assertIn("[REDACTED]", item.content)
        self.assertNotIn("super-secret", item.content)
        self.assertEqual(len(item.content_hash or ""), 64)
        pipeline.tombstone("fixture", "deploy-1", "1")
        self.assertIsNone(store.get(item.evidence_id))
        self.assertTrue(store.is_tombstoned(item.evidence_id))

    def test_hybrid_retrieval_filters_acl_and_prefers_incident_window(self) -> None:
        store = InMemoryEvidenceStore()
        pipeline = IngestionPipeline(store)
        incident_time = datetime(2026, 1, 1, 12, tzinfo=UTC)
        near = pipeline.ingest(record("deploy-near", "payments latency deploy version 42", acl("t1", "user:u1"), event_time=incident_time - timedelta(hours=1)))
        pipeline.ingest(record("deploy-far", "payments latency deploy version 7", acl("t1", "user:u1"), event_time=incident_time - timedelta(days=30)))
        pipeline.ingest(record("private", "payments latency version 42", acl("t1", "user:u2"), event_time=incident_time))
        identity = IdentityContext("t1", "u1")
        query = QueryContext("t1", "what changed payments latency", identity, target_time=incident_time, service_ids=frozenset({"payments"}))
        results = HybridRetriever(store, PolicyEnforcer()).search(query)
        self.assertEqual(results[0].evidence.evidence_id, near.evidence_id)
        self.assertNotIn("fixture:private:1", {result.evidence.evidence_id for result in results})

    def test_graph_neighbor_contributes_to_retrieval(self) -> None:
        store = InMemoryEvidenceStore()
        pipeline = IngestionPipeline(store)
        item = pipeline.ingest(record("deploy-orders", "orders dependency changed", acl("t1", "user:u1"), service="orders"))
        graph = GraphIndex()
        graph.add_relation(GraphRelation("payments", "orders", "DEPENDS_ON"))
        graph.add_evidence(item)
        query = QueryContext("t1", "dependency changed", IdentityContext("t1", "u1"), service_ids=frozenset({"payments"}))
        results = HybridRetriever(store, PolicyEnforcer(), graph).search(query)
        self.assertEqual(results[0].evidence.evidence_id, item.evidence_id)
        self.assertTrue(any("graph-neighbor" in reason for reason in results[0].reasons))

    def test_citation_validator_rejects_missing_unauthorized_and_unsupported_claims(self) -> None:
        store = InMemoryEvidenceStore()
        pipeline = IngestionPipeline(store)
        visible = pipeline.ingest(record("deploy-1", "payments deployed version 42", acl("t1", "user:u1")))
        hidden = pipeline.ingest(record("secret", "payments deployed version 99", acl("t1", "user:u2")))
        identity = IdentityContext("t1", "u1")
        query = QueryContext("t1", "what changed", identity)
        validator = CitationValidator(PolicyEnforcer())
        valid = validator.validate(
            AnswerDraft("a1", (Claim("c1", "payments deployed version 42", (visible.evidence_id,)),)),
            {visible.evidence_id: visible},
            query,
        )
        self.assertTrue(valid.valid)
        invalid = validator.validate(
            AnswerDraft(
                "a2",
                (
                    Claim("c1", "payments deployed version 99", (hidden.evidence_id,)),
                    Claim("c2", "there was a rollback", ()),
                ),
            ),
            {visible.evidence_id: visible, hidden.evidence_id: hidden},
            query,
        )
        self.assertFalse(invalid.valid)
        self.assertTrue(any("unauthorized" in issue for issue in invalid.issues))
        self.assertTrue(any("no citation" in issue for issue in invalid.issues))

    def test_sqlite_store_survives_restart_and_records_projection_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.db"
            store = SQLiteEvidenceStore(path)
            pipeline = IngestionPipeline(store)
            item = pipeline.ingest(record("deploy-1", "payments deploy 42", acl("t1", "user:u1")))
            self.assertEqual(len(store.pending_outbox()), 1)
            self.assertEqual(store.pending_outbox()[0]["event_type"], "upsert")
            store.close()

            reopened = SQLiteEvidenceStore(path)
            loaded = reopened.get(item.evidence_id)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.content, item.content)
            self.assertEqual(loaded.acl.allowed_principals, item.acl.allowed_principals)
            IngestionPipeline(reopened).tombstone("fixture", "deploy-1", "1")
            reopened.close()

            after_delete = SQLiteEvidenceStore(path)
            self.assertIsNone(after_delete.get(item.evidence_id))
            self.assertTrue(after_delete.is_tombstoned(item.evidence_id))
            self.assertEqual(after_delete.pending_outbox()[-1]["event_type"], "delete")
            feedback = FeedbackRecord("t1", "u1", "answer-1", "useful", claim_id="c1", comment="Helpful")
            after_delete.record_feedback(feedback)
            after_delete.close()

            feedback_store = SQLiteEvidenceStore(path)
            self.assertEqual(feedback_store.list_feedback("t1")[0].kind, "useful")
            feedback_store.close()
            after_delete.close()

    def test_jsonl_connector_resumes_from_durable_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = Path(directory) / "changes.jsonl"
            payload = {
                "tenant_id": "t1",
                "source_type": "deployment",
                "source_instance": "jsonl-fixture",
                "source_object_id": "deploy-1",
                "source_version": "1",
                "title": "Payments deploy",
                "content": "payments deploy version 42",
                "acl": {"tenant_id": "t1", "allowed_principals": ["user:u1"], "source_policy_version": "v1"},
                "service_ids": ["payments"],
            }
            delete = {"kind": "delete", "source_object_id": "deploy-1", "source_version": "1"}
            fixture_path.write_text("\n".join((json.dumps(payload), json.dumps(delete))), encoding="utf-8")
            store = SQLiteEvidenceStore(Path(directory) / "registry.db")
            pipeline = IngestionPipeline(store)
            coordinator = IngestionCoordinator(pipeline, store)
            connector = JsonlConnector(fixture_path, "jsonl-fixture")

            first = coordinator.run_once(connector, limit=1)
            self.assertEqual((first.processed, first.upserts, first.deletes), (1, 1, 0))
            self.assertIsNotNone(store.get("jsonl-fixture:deploy-1:1"))
            second = coordinator.run_once(connector, limit=1)
            self.assertEqual((second.processed, second.upserts, second.deletes), (1, 0, 1))
            self.assertIsNone(store.get("jsonl-fixture:deploy-1:1"))
            self.assertEqual(store.load_checkpoint("jsonl-fixture")["cursor"], "2")
            store.close()

    def test_http_json_connector_normalizes_poll_changes_and_retries(self) -> None:
        source_payload = {
            "tenant_id": "t1",
            "source_type": "deployment",
            "source_instance": "http-fixture",
            "source_object_id": "deploy-1",
            "source_version": "1",
            "title": "Payments deploy",
            "content": "payments deploy version 42",
            "acl": {"tenant_id": "t1", "allowed_principals": ["user:u1"], "source_policy_version": "v1"},
            "service_ids": ["payments"],
        }

        class FakeResponse:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(self.body).encode("utf-8")

        payload = {"items": [{"record": source_payload}, {"kind": "delete", "source_object_id": "old", "source_version": "2"}], "next_cursor": "2", "has_more": False}
        connector = HttpJsonConnector("http://connector.local/events", "http-fixture", max_retries=1)
        with patch("urllib.request.urlopen", side_effect=[urllib.error.URLError("temporary"), FakeResponse(payload)]) as request:
            batch = connector.poll(None, limit=10)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(batch.next_cursor, "2")
        self.assertEqual((batch.changes[0].kind, batch.changes[1].kind), ("upsert", "delete"))
        self.assertEqual(batch.changes[0].record.source_instance, "http-fixture")

    def test_grounded_triage_returns_structured_claims_and_evidence_cards(self) -> None:
        store = InMemoryEvidenceStore()
        item = IngestionPipeline(store).ingest(
            record("deploy-1", "payments deployed version 42 before latency increased", acl("t1", "user:u1"))
        )
        policy = PolicyEnforcer()
        query = QueryContext("t1", "what changed payments latency", IdentityContext("t1", "u1"))
        response = GroundedTriageService(
            HybridRetriever(store, policy),
            CitationValidator(policy),
        ).investigate(query)
        self.assertEqual(response.status, "grounded")
        self.assertTrue(response.claims)
        self.assertEqual(response.claims[0].citation_ids, ("E1",))
        self.assertEqual(response.evidence[0].evidence_id, item.evidence_id)
        self.assertEqual(response.limitations, ())

    def test_grounded_triage_omits_unsupported_claims_and_abstains(self) -> None:
        store = InMemoryEvidenceStore()
        IngestionPipeline(store).ingest(record("deploy-1", "payments deployed version 42", acl("t1", "user:u1")))
        policy = PolicyEnforcer()

        class UnsafeAnswerer:
            def generate(self, context):
                return AnswerDraft("unsafe", (Claim("c1", "database was deleted", ("E1",)),))

        query = QueryContext("t1", "what changed", IdentityContext("t1", "u1"))
        response = GroundedTriageService(
            HybridRetriever(store, policy),
            CitationValidator(policy),
            answerer=UnsafeAnswerer(),
        ).investigate(query)
        self.assertEqual(response.status, "evidence_only")
        self.assertEqual(response.claims, ())
        self.assertTrue(any("support" in issue for issue in response.limitations))

        no_access = QueryContext("t1", "what changed", IdentityContext("t1", "u2"))
        empty = GroundedTriageService(
            HybridRetriever(store, policy),
            CitationValidator(policy),
        ).investigate(no_access)
        self.assertEqual(empty.status, "insufficient_evidence")

    def test_evaluation_runner_reports_metrics_and_passes_persona_gate(self) -> None:
        store = InMemoryEvidenceStore()
        item = IngestionPipeline(store).ingest(
            record("deploy-1", "payments deployed version 42", acl("t1", "user:u1"))
        )
        policy = PolicyEnforcer()
        service = GroundedTriageService(HybridRetriever(store, policy), CitationValidator(policy))
        authorized = QueryContext("t1", "what changed payments", IdentityContext("t1", "u1"))
        forbidden = QueryContext("t1", "what changed payments", IdentityContext("t1", "u2"))
        dataset = EvaluationDataset(
            version="test-v1",
            cases=(
                EvaluationCase(
                    "visible",
                    authorized,
                    relevant_evidence_ids=frozenset({item.evidence_id}),
                    expected_claim_terms=("version 42",),
                ),
                EvaluationCase(
                    "hidden",
                    forbidden,
                    forbidden_evidence_ids=frozenset({item.evidence_id}),
                    must_abstain=True,
                ),
            ),
        )
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
        self.assertTrue(report.passed, report.gate_failures)
        self.assertEqual(report.metrics["forbidden_evidence_rate"], 0.0)
        self.assertEqual(report.metrics["recall_at_k"], 1.0)

    def test_evaluation_gate_fails_on_forbidden_evidence(self) -> None:
        store = InMemoryEvidenceStore()
        item = IngestionPipeline(store).ingest(record("deploy-1", "payments deploy", acl("t1", "user:u1")))
        policy = PolicyEnforcer()
        service = GroundedTriageService(HybridRetriever(store, policy), CitationValidator(policy))
        query = QueryContext("t1", "payments deploy", IdentityContext("t1", "u1"))
        dataset = EvaluationDataset(
            version="unsafe-v1",
            cases=(EvaluationCase("unsafe", query, forbidden_evidence_ids=frozenset({item.evidence_id})),),
        )
        report = EvaluationRunner(
            service,
            EvaluationGate(
                min_grounded_response_rate=0.0,
                min_citation_coverage=0.0,
                min_abstention_accuracy=0.0,
                max_forbidden_evidence_rate=0.0,
            ),
        ).run(dataset)
        self.assertFalse(report.passed)
        self.assertTrue(any("forbidden_evidence_rate" in failure for failure in report.gate_failures))

    def test_model_gateway_output_still_passes_through_grounding_validation(self) -> None:
        store = InMemoryEvidenceStore()
        IngestionPipeline(store).ingest(record("deploy-1", "payments deployed version 42", acl("t1", "user:u1")))
        policy = PolicyEnforcer()
        query = QueryContext("t1", "what changed payments", IdentityContext("t1", "u1"))

        class ValidGateway:
            def generate(self, context, config):
                return AnswerDraft(
                    "provider-answer",
                    (Claim("provider-c1", "payments deployed version 42", ("E1",), "source_asserted"),),
                    "Provider-backed grounded summary.",
                )

        valid = GroundedTriageService(
            HybridRetriever(store, policy),
            CitationValidator(policy),
            answerer=ModelBackedAnswerer(ValidGateway()),
        ).investigate(query)
        self.assertEqual(valid.status, "grounded")
        self.assertEqual(valid.answer_id, "provider-answer")

        class UnsafeGateway:
            def generate(self, context, config):
                return AnswerDraft("unsafe-provider", (Claim("provider-c1", "database was deleted", ("E1",)),))

        unsafe = GroundedTriageService(
            HybridRetriever(store, policy),
            CitationValidator(policy),
            answerer=ModelBackedAnswerer(UnsafeGateway()),
        ).investigate(query)
        self.assertEqual(unsafe.status, "evidence_only")

        class FailingGateway:
            def generate(self, context, config):
                raise RuntimeError("provider unavailable")

        fallback = GroundedTriageService(
            HybridRetriever(store, policy),
            CitationValidator(policy),
            answerer=ModelBackedAnswerer(FailingGateway()),
        ).investigate(query)
        self.assertEqual(fallback.status, "grounded")

    def test_openai_compatible_gateway_parses_structured_json_without_network(self) -> None:
        store = InMemoryEvidenceStore()
        IngestionPipeline(store).ingest(record("deploy-1", "payments deployed version 42", acl("t1", "user:u1")))
        policy = PolicyEnforcer()
        query = QueryContext("t1", "what changed payments", IdentityContext("t1", "u1"))
        results = HybridRetriever(store, policy).search(query)
        context = AuthorizedContextBuilder(policy).build(query, results)

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                content = "```json\n" + json.dumps(
                    {
                        "summary": "grounded",
                        "claims": [
                            {
                                "claim_id": "c1",
                                "text": "payments deployed version 42",
                                "claim_type": "source_asserted",
                                "material": True,
                                "citation_ids": ["E1"],
                            }
                        ],
                    }
                ) + "\n```"
                return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")

        with patch("urllib.request.urlopen", return_value=FakeResponse()) as request:
            draft = OpenAICompatibleGateway("http://model.local/v1/chat/completions").generate(
                context, GenerationConfig(model="test-model")
            )
        self.assertEqual(draft.summary, "grounded")
        self.assertEqual(draft.claims[0].citation_ids, ("E1",))
        self.assertEqual(request.call_count, 1)


def item_to_evidence(item: SourceRecord):
    store = InMemoryEvidenceStore()
    return IngestionPipeline(store).ingest(item)


if __name__ == "__main__":
    unittest.main()
