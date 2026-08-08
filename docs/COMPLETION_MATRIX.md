# Implementation Completion Matrix

This matrix distinguishes what is implemented and validated in this repository from work that requires organization-specific systems, credentials, or approvals.

| Phase | Local implementation | Validation | External handoff still required |
|---|---|---|---|
| 0 — Discovery | BRD, architecture, threat assumptions, decision list | Documents reviewed | Select vendors, pilot teams, residency, retention, and final SLOs |
| 1 — Foundation | Canonical schemas, package, API, CI workflow, safe logging headers, health/readiness | Compile and unit suite | OIDC provider and production secret/key management |
| 2 — Ingestion | SQLite registry, tombstones, outbox, checkpoints, JSONL connector, retrying HTTP JSON connector | Restart, replay, deletion, retry tests | Vendor-specific source adapters and read-only credentials |
| 3 — Retrieval | Lexical/semantic baseline, metadata filters, ACL filtering, temporal scoring, evidence-only API | Persona and tenant isolation tests | Production lexical/vector capacity benchmark |
| 4 — Graph/time | Bounded graph index, provenance-shaped relations, graph neighbor scoring | Graph retrieval and temporal tests | Production graph store, entity registry, curator workflow |
| 5 — Grounded generation | Context builder, Ollama/OpenAI-compatible gateway, structured parsing, fallback, citation validator | Provider mock tests and live local Ollama triage | Approved provider terms, model evaluation, prompt/model review |
| 6 — Experience/workflow | Responsive UI, triage, timeline endpoint, feedback endpoint, connector admin status | UI HTTP check, API checks, feedback persistence tests | Incident-system embed/deep link, accessibility review, responder UAT |
| 7 — Hardening | Security headers, production startup guards, Dockerfile, Compose, CI, evaluation gates | 15 automated tests, compile, smoke evaluation | Pen test, load/soak/DR exercises, SRE approval |
| 8 — Pilot | Local seed, smoke dataset, repeatable startup scripts, outcome metrics schema | Grounded smoke gate passes | Real pilot data, responders, 4-week observation, go/no-go approval |

## Explicit production blockers

The repository cannot safely self-select these values:

1. Authoritative deployment, incident, documentation, observability, and service-catalog vendors.
2. Source-specific ACL semantics and read-only credentials.
3. OIDC issuer, audience, JWKS/claims mapping, and group synchronization.
4. Production database/object/index/graph services and data residency.
5. Retention, deletion, legal hold, model-provider, and privacy approvals.
6. Pilot incident set, expert labels, baseline MTTT, and final quality/cost gates.
7. Production traffic limits, on-call ownership, disaster-recovery targets, and penetration-test sign-off.

The system is complete as a runnable, testable local reference implementation. It is not represented as enterprise-production-ready until these handoffs are completed and the corresponding exit gates are evidenced.
