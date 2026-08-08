"""Optional FastAPI adapter for the local foundation.

Install the API extra to run this module. The domain package remains usable
without FastAPI for ingestion, evaluation, and command-line workflows.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4
from typing import Any

from incident_intelligence import (
    ACL,
    CitationValidator,
    FeedbackRecord,
    GroundedTriageService,
    HybridRetriever,
    IdentityContext,
    InMemoryEvidenceStore,
    IngestionPipeline,
    GenerationConfig,
    ModelBackedAnswerer,
    OpenAICompatibleGateway,
    PolicyEnforcer,
    QueryContext,
    SQLiteEvidenceStore,
    SourceRecord,
)


def create_app(store: Any | None = None) -> Any:
    try:
        from fastapi import FastAPI, Header, HTTPException
        from fastapi.middleware.cors import CORSMiddleware
    except ImportError as exc:  # pragma: no cover - exercised when API extra is absent
        raise RuntimeError("Install the api extra: pip install -e .[api]") from exc

    app = FastAPI(title="Incident Intelligence", version="0.1.0")
    runtime_environment = os.getenv("APP_ENV", "development").lower()
    database_path = os.getenv("INCIDENT_DB_PATH")
    if runtime_environment == "production":
        if os.getenv("DEMO_SEED", "0") == "1":
            raise RuntimeError("DEMO_SEED cannot be enabled in production")
        if not database_path:
            raise RuntimeError("INCIDENT_DB_PATH is required in production")
        if os.getenv("AUTH_MODE", "local") != "oidc":
            raise RuntimeError("AUTH_MODE=oidc is required in production")

    @app.middleware("http")
    async def security_headers(request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response
    allowed_origins = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        os.getenv("UI_ORIGIN", "").strip(),
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin for origin in allowed_origins if origin],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Tenant-ID", "X-User-ID", "X-Groups"],
    )
    if store is None:
        store = SQLiteEvidenceStore(database_path) if database_path else InMemoryEvidenceStore()
    pipeline = IngestionPipeline(store)
    policy = PolicyEnforcer()
    configured_answerer = None
    model_endpoint = os.getenv("MODEL_ENDPOINT", "").strip()
    if model_endpoint:
        configured_answerer = ModelBackedAnswerer(
            OpenAICompatibleGateway(model_endpoint, os.getenv("MODEL_API_KEY")),
            config=GenerationConfig(
                model=os.getenv("MODEL_NAME", "llama3.2:3b"),
                temperature=float(os.getenv("MODEL_TEMPERATURE", "0")),
                max_tokens=int(os.getenv("MODEL_MAX_TOKENS", "900")),
                timeout_seconds=float(os.getenv("MODEL_TIMEOUT_SECONDS", "15")),
            ),
        )

    if os.getenv("DEMO_SEED", "0") == "1" and not store.all():
        now = datetime.now(timezone.utc)
        demo_acl = ACL(
            tenant_id="demo",
            allowed_principals=frozenset({"user:alice", "group:oncall"}),
            source_policy_version="v1",
        )
        seed_records = (
            SourceRecord(
                tenant_id="demo",
                source_type="deployment",
                source_instance="demo-source",
                source_object_id="deploy-42",
                source_version="1",
                title="Payments deployment 42",
                content="checkout-api deployed v2026.08.06-3 before latency increased.",
                acl=demo_acl,
                event_time_start=now - timedelta(minutes=11),
                event_time_end=now - timedelta(minutes=11),
                source_url="https://deployments.local/checkout-api/42",
                service_ids=("checkout-api",),
                environment="prod",
                metadata={"incident_id": "INC-2048", "deployment_id": "deploy-42"},
            ),
            SourceRecord(
                tenant_id="demo",
                source_type="observability",
                source_instance="demo-source",
                source_object_id="checkout-latency-high",
                source_version="1",
                title="checkout-latency-high alert",
                content="p95 latency crossed 2s for 5 consecutive minutes and reached 4.8s.",
                acl=demo_acl,
                event_time_start=now - timedelta(minutes=1),
                event_time_end=now - timedelta(minutes=1),
                source_url="https://observability.local/alerts/checkout-latency-high",
                service_ids=("checkout-api",),
                environment="prod",
                metadata={"incident_id": "INC-2048", "alert_id": "checkout-latency-high"},
            ),
            SourceRecord(
                tenant_id="demo",
                source_type="knowledge",
                source_instance="demo-source",
                source_object_id="checkout-provider-runbook",
                source_version="1",
                title="Checkout provider timeout runbook",
                content="The provider timeout checklist covers retry amplification and safe rollback steps.",
                acl=demo_acl,
                event_time_start=now - timedelta(minutes=45),
                event_time_end=now - timedelta(minutes=45),
                source_url="https://knowledge.local/runbooks/checkout-provider",
                service_ids=("checkout-api",),
                environment="prod",
                metadata={"incident_id": "INC-2048", "document_id": "checkout-provider-runbook"},
            ),
        )
        for seed in seed_records:
            pipeline.ingest(seed)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, Any]:
        return {
            "status": "ready",
            "environment": runtime_environment,
            "evidence_count": len(store.all()),
            "model_provider_configured": bool(configured_answerer),
        }

    @app.post("/v1/evidence")
    def ingest(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            acl_payload = payload["acl"]
            acl = ACL(
                tenant_id=acl_payload["tenant_id"],
                allowed_principals=frozenset(acl_payload.get("allowed_principals", [])),
                denied_principals=frozenset(acl_payload.get("denied_principals", [])),
                public_within_tenant=bool(acl_payload.get("public_within_tenant", False)),
                source_policy_version=acl_payload.get("source_policy_version", "unknown"),
            )
            record = SourceRecord(
                tenant_id=payload["tenant_id"],
                source_type=payload["source_type"],
                source_instance=payload["source_instance"],
                source_object_id=payload["source_object_id"],
                source_version=payload["source_version"],
                title=payload.get("title", ""),
                content=payload["content"],
                acl=acl,
                event_time_start=datetime.fromisoformat(payload["event_time_start"]) if payload.get("event_time_start") else None,
                event_time_end=datetime.fromisoformat(payload["event_time_end"]) if payload.get("event_time_end") else None,
                source_url=payload.get("source_url"),
                service_ids=tuple(payload.get("service_ids", [])),
                environment=payload.get("environment"),
            )
            item = pipeline.ingest(record)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"evidence_id": item.evidence_id, "content_hash": item.content_hash}

    @app.get("/v1/evidence")
    def list_evidence(
        q: str,
        x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
        x_user_id: str = Header(..., alias="X-User-ID"),
        x_groups: str = Header("", alias="X-Groups"),
    ) -> list[dict[str, Any]]:
        from incident_intelligence.retrieval import HybridRetriever

        groups = frozenset(group.strip() for group in x_groups.split(",") if group.strip())
        identity = IdentityContext(tenant_id=x_tenant_id, user_id=x_user_id, groups=groups)
        query = QueryContext(tenant_id=x_tenant_id, text=q, identity=identity)
        results = HybridRetriever(store, policy).search(query)
        return [
            {
                "evidence_id": result.evidence.evidence_id,
                "title": result.evidence.title,
                "score": result.score,
                "reasons": result.reasons,
                "source_url": result.evidence.source_url,
            }
            for result in results
        ]

    @app.post("/v1/triage")
    def triage(
        payload: dict[str, Any],
        x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
        x_user_id: str = Header(..., alias="X-User-ID"),
        x_groups: str = Header("", alias="X-Groups"),
    ) -> dict[str, Any]:
        """Run the local evidence-first triage pipeline.

        The deterministic answerer is intentionally used here. A production
        deployment should inject a model gateway only after the same context
        and citation validation contract is retained.
        """

        try:
            groups = frozenset(group.strip() for group in x_groups.split(",") if group.strip())
            identity = IdentityContext(tenant_id=x_tenant_id, user_id=x_user_id, groups=groups)
            query = QueryContext(
                tenant_id=x_tenant_id,
                text=payload["text"],
                identity=identity,
                target_time=datetime.fromisoformat(payload["target_time"]) if payload.get("target_time") else None,
                window_start=datetime.fromisoformat(payload["window_start"]) if payload.get("window_start") else None,
                window_end=datetime.fromisoformat(payload["window_end"]) if payload.get("window_end") else None,
                service_ids=frozenset(payload.get("service_ids", [])),
                environment=payload.get("environment"),
                source_types=frozenset(payload.get("source_types", [])),
            )
            service = GroundedTriageService(
                HybridRetriever(store, policy),
                CitationValidator(policy),
                answerer=configured_answerer,
            )
            response = service.investigate(query, limit=int(payload.get("limit", 8)))
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "answer_id": response.answer_id,
            "status": response.status,
            "summary": response.summary,
            "claims": [
                {
                    "claim_id": claim.claim_id,
                    "text": claim.text,
                    "citation_ids": claim.citation_ids,
                    "claim_type": claim.claim_type,
                }
                for claim in response.claims
            ],
            "evidence": [
                {
                    "citation_id": card.citation_id,
                    "evidence_id": card.evidence_id,
                    "title": card.title,
                    "snippet": card.snippet,
                    "source_type": card.source_type,
                    "source_url": card.source_url,
                    "event_time": card.event_time,
                    "score": card.score,
                    "reasons": card.reasons,
                }
                for card in response.evidence
            ],
            "limitations": response.limitations,
        }

    @app.get("/v1/incidents/{incident_id}/timeline")
    def incident_timeline(
        incident_id: str,
        x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
        x_user_id: str = Header(..., alias="X-User-ID"),
        x_groups: str = Header("", alias="X-Groups"),
    ) -> list[dict[str, Any]]:
        groups = frozenset(group.strip() for group in x_groups.split(",") if group.strip())
        identity = IdentityContext(tenant_id=x_tenant_id, user_id=x_user_id, groups=groups)
        events = []
        for item in store.all():
            if str(item.metadata.get("incident_id", "")) != incident_id:
                continue
            if not policy.authorize(item, identity).allowed:
                continue
            events.append(
                {
                    "evidence_id": item.evidence_id,
                    "source_type": item.source_type,
                    "title": item.title,
                    "snippet": " ".join(item.content.split())[:320],
                    "event_time": item.event_time,
                    "source_url": item.source_url,
                    "service_ids": item.service_ids,
                }
            )
        events.sort(key=lambda event: event["event_time"] or datetime.min.replace(tzinfo=timezone.utc))
        return events

    @app.post("/v1/feedback")
    def feedback(
        payload: dict[str, Any],
        x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
        x_user_id: str = Header(..., alias="X-User-ID"),
    ) -> dict[str, str]:
        try:
            item = FeedbackRecord(
                tenant_id=x_tenant_id,
                user_id=x_user_id,
                answer_id=payload["answer_id"],
                claim_id=payload.get("claim_id"),
                kind=payload["kind"],
                comment=str(payload.get("comment", ""))[:1000] or None,
            )
            store.record_feedback(item)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"feedback_id": item.feedback_id, "status": "recorded"}

    @app.get("/v1/admin/connectors")
    def connector_status() -> list[dict[str, Any]]:
        by_source: dict[str, list[Any]] = {}
        for item in store.all():
            by_source.setdefault(item.source_instance, []).append(item)
        result = []
        for source_instance, items in sorted(by_source.items()):
            result.append(
                {
                    "source_instance": source_instance,
                    "status": "ok",
                    "evidence_count": len(items),
                    "latest_ingested_at": max(item.ingested_at for item in items),
                    "policy_versions": sorted({item.acl.source_policy_version for item in items}),
                }
            )
        return result

    return app


app = None
try:  # Keep import-safe for environments that have not installed the API extra.
    app = create_app()
except RuntimeError:
    pass
