# Business Requirements Document: SignalForge Incident Intelligence Platform

| Field | Value |
|---|---|
| Document status | Draft for stakeholder review |
| Version | 1.0 |
| Date | 2026-08-06 |
| Product owner | TBD |
| Technical owner | TBD |
| Target release | MVP pilot, approximately 18 weeks after kickoff |

## 1. Executive summary

Engineering responders lose critical time correlating deployments, service topology, alerts, logs, traces, runbooks, and prior incidents. The proposed platform creates a permission-safe evidence layer and an incident-triage assistant that retrieves relevant operational context, explains why the evidence matters, and cites every material claim.

Project statement supplied for this initiative:

> Built an incident-intelligence platform using hybrid and graph-based RAG over deployment, observability, and operational knowledge sources; implemented ACL-aware retrieval, temporal evidence ranking, citation validation, and evaluation pipelines for grounded incident triage.

The initial product will support evidence discovery and grounded triage. It will not autonomously modify production systems or make final root-cause declarations.

## 2. Business problem

Incident data is fragmented across CI/CD systems, Kubernetes and cloud platforms, observability tools, ticketing systems, source control, chat, and documentation. Existing search tools commonly fail because they:

- rank text by lexical similarity without understanding service dependencies;
- favor recent content without aligning evidence to the incident timeline;
- reproduce source data without consistently enforcing source permissions;
- generate plausible answers whose claims cannot be traced to evidence;
- lack a repeatable evaluation process for retrieval quality and grounding.

This increases time to triage, makes outcomes depend on individual memory, and causes teams to repeat prior investigative work.

## 3. Product vision

Give every authorized responder a single, trustworthy place to ask incident questions, explore an incident timeline, and retrieve the most relevant evidence across operational systems without weakening existing access controls.

## 4. Objectives and success measures

The following targets are proposed MVP exit criteria and must be baselined during discovery.

| Objective | Measure | Proposed target |
|---|---|---|
| Reduce triage time | Median time from incident start to a useful evidence set | 40% lower than the pre-pilot baseline |
| Retrieve useful evidence | Recall@10 on a held-out, expert-labeled incident set | At least 0.85 |
| Rank useful evidence early | nDCG@10 on the same set | At least 0.75 |
| Produce grounded responses | Supported material claims | At least 95% |
| Provide complete citations | Material claims with one or more valid citations | At least 95% |
| Protect source permissions | Unauthorized retrieval in automated and adversarial tests | Zero known leakage; 100% authorization checks |
| Return results promptly | Search p95 / completed answer p95 | At most 3 seconds / 12 seconds under agreed pilot load |
| Keep critical data current | Deployment and alert ingestion lag p95 | At most 2 minutes |
| Earn responder trust | Pilot answers rated useful | At least 70% |
| Improve operations | Pilot incidents with assistant use | At least 60% after four weeks |

No aggregate relevance target can waive the zero-leakage requirement.

## 5. Stakeholders and users

| Role | Need |
|---|---|
| Incident commander | Rapid status, timeline, affected services, and cited evidence |
| On-call engineer | Relevant changes, telemetry, dependencies, runbooks, and similar incidents |
| Service owner | Service-specific evidence and corrective-action history |
| SRE/platform engineer | Cross-service patterns, operational knowledge, and system health |
| Security/compliance | Permission fidelity, auditability, retention, and data lineage |
| Engineering manager | Incident trends and adoption/outcome metrics |
| Knowledge curator | Source health, content quality, and entity corrections |
| Platform administrator | Connector, tenant, model, and policy configuration |

## 6. Scope

### 6.1 MVP scope

- OIDC/SSO authentication and group-aware authorization.
- One deployment source, one observability suite, one documentation source, one incident system, and a service catalog. Exact vendors are selected in Phase 0.
- Batch plus event-driven ingestion with incremental updates, deletion propagation, source lineage, and freshness monitoring.
- Canonical representation for documents, chunks, services, incidents, deployments, telemetry events, runbooks, people/teams, and relationships.
- Keyword, vector, metadata, and bounded graph retrieval.
- ACL filtering before candidate retrieval where supported and a mandatory authorization recheck before any evidence reaches the model or user.
- Incident-aware temporal ranking based on event time, incident time, source quality, and deployment proximity.
- A triage experience with search, generated summary, cited evidence, timeline, filters, and feedback.
- Claim-level citation validation, answer repair, and fail-safe abstention.
- Offline retrieval/generation evaluation, security tests, online telemetry, and pilot reporting.
- Admin views for connector status, index freshness, evaluation versions, and audit events.

### 6.2 Post-MVP candidates

- Additional connectors and cross-region or cross-business-unit federation.
- ChatOps interfaces, mobile experience, and incident-room summaries.
- Multimodal evidence such as dashboard screenshots.
- Proactive correlation and anomaly-triggered evidence packs.
- Root-cause hypothesis comparison and recommended remediation with approval gates.
- Multilingual content and responses.
- Trend analytics over incident classes and organizational learning.

### 6.3 Explicitly out of scope for MVP

- Autonomous production changes, rollback, scaling, or remediation.
- Replacing the incident-management, observability, service-catalog, or IAM system of record.
- Training a foundation model from scratch.
- Declaring root cause without human confirmation.
- Indexing private messages or unrestricted chat history by default.
- Weakening or normalizing away source-system access controls.

## 7. Assumptions and constraints

- The organization provides a stable user/group identity key through its identity provider.
- Source APIs expose usable permission metadata or offer a reliable authorization check.
- Each pilot service has ownership metadata and a minimum set of historic incidents.
- Data residency, retention, model-provider, and private-network requirements will be decided before implementation.
- Generated content is advisory and must clearly distinguish evidence, inference, and unknowns.
- Observability volumes are too large for indiscriminate raw-log embedding; ingestion must summarize, sample, or query telemetry systems on demand.
- All timestamps are stored in UTC, while the interface may render a user-selected timezone.

## 8. Business requirements

| ID | Requirement | Priority |
|---|---|---|
| BR-01 | Provide a unified incident evidence experience across approved operational sources. | Must |
| BR-02 | Preserve tenant, user, group, document, and source permissions end to end. | Must |
| BR-03 | Rank evidence using textual relevance, semantic similarity, topology, time, and source trust. | Must |
| BR-04 | Trace material answer claims to accessible, immutable evidence references. | Must |
| BR-05 | Represent service, deployment, incident, and dependency relationships for graph traversal. | Must |
| BR-06 | Expose uncertainty and abstain when accessible evidence is insufficient or conflicting. | Must |
| BR-07 | Measure retrieval, grounding, citation, security, latency, cost, and user outcomes. | Must |
| BR-08 | Maintain source lineage, freshness, deletion, and audit records. | Must |
| BR-09 | Support responder feedback and controlled improvement of ranking and prompts. | Should |
| BR-10 | Allow administrators to configure connectors and policies without code changes. | Should |
| BR-11 | Integrate with existing incident workflows without becoming a new system of record. | Should |
| BR-12 | Provide a path from single-team pilot to multi-tenant enterprise operation. | Should |

## 9. Functional requirements

### 9.1 Identity, tenancy, and access control

| ID | Requirement |
|---|---|
| FR-IAM-01 | Authenticate users through OIDC/OAuth 2.0 and validate issuer, audience, expiry, and signature. |
| FR-IAM-02 | Resolve tenant, user, group, role, and applicable source identities for each request. |
| FR-IAM-03 | Store an ACL envelope with every indexed object, including tenant, allow/deny principals, classification, source policy version, and inheritance metadata. |
| FR-IAM-04 | Apply tenant and ACL filters during retrieval wherever the backing store supports them. |
| FR-IAM-05 | Reauthorize every selected item immediately before model context assembly and user display. |
| FR-IAM-06 | Fail closed when permissions are missing, stale beyond policy, contradictory, or cannot be resolved. |
| FR-IAM-07 | Propagate access changes and deletions within the agreed revocation SLA. |
| FR-IAM-08 | Prevent leakage through snippets, citations, counts, cache keys, graph neighbors, errors, logs, and evaluation data. |
| FR-IAM-09 | Record authorization decisions and policy versions without storing unnecessary sensitive content. |

### 9.2 Ingestion and knowledge processing

| ID | Requirement |
|---|---|
| FR-ING-01 | Support scheduled backfills, incremental polling, webhook/event ingestion, retry, replay, and dead-letter handling. |
| FR-ING-02 | Preserve source ID, canonical URL, version, event time, update time, ingestion time, owner, content hash, and ACL envelope. |
| FR-ING-03 | Use source-aware parsing and chunking while preserving section, record, and temporal boundaries. |
| FR-ING-04 | Deduplicate exact and near-duplicate content without merging objects with different permissions. |
| FR-ING-05 | Redact or exclude secrets and configured sensitive fields before indexing or model use. |
| FR-ING-06 | Propagate updates, tombstones, retention expiry, and legal holds to all derived stores. |
| FR-ING-07 | Quarantine invalid records and expose connector freshness, error, and throughput metrics. |
| FR-ING-08 | Version parsers, chunkers, embeddings, entity extraction, and graph construction for reproducibility. |

### 9.3 Knowledge graph

| ID | Requirement |
|---|---|
| FR-GR-01 | Model services, teams, repositories, commits, deployments, environments, resources, alerts, incidents, runbooks, dashboards, and evidence artifacts. |
| FR-GR-02 | Model typed, directed, time-bounded relationships with provenance and confidence. |
| FR-GR-03 | Resolve source-specific identifiers to canonical entities without discarding aliases. |
| FR-GR-04 | Keep asserted relationships separate from model-inferred relationships. |
| FR-GR-05 | Limit traversal by tenant, ACL, relationship allowlist, direction, depth, fan-out, and time window. |
| FR-GR-06 | Permit curators to correct or merge entities with an auditable change history. |

### 9.4 Retrieval and temporal ranking

| ID | Requirement |
|---|---|
| FR-RET-01 | Interpret the query, incident context, services, environment, entities, and time range. |
| FR-RET-02 | Retrieve in parallel from lexical, vector, metadata, and graph channels. |
| FR-RET-03 | Normalize and fuse channel scores, rerank authorized candidates, and diversify the final context. |
| FR-RET-04 | Rank against event time and incident phase, not ingestion time alone. |
| FR-RET-05 | Boost evidence inside the incident window, causal precursors, related deployments, affected dependencies, and verified source-of-truth records. |
| FR-RET-06 | Penalize stale, duplicate, low-confidence, weakly related, or superseded evidence. |
| FR-RET-07 | Expose retrieval rationale, source, time, and relationship path for selected evidence. |
| FR-RET-08 | Support service, source, environment, severity, evidence type, and time filters. |

### 9.5 Triage response and citations

| ID | Requirement |
|---|---|
| FR-ANS-01 | Return a structured response containing current assessment, timeline, relevant changes, affected dependencies, hypotheses, suggested checks, evidence, uncertainty, and conflicts. |
| FR-ANS-02 | Attach citations to every material factual claim and label uncited content as suggestion or inference. |
| FR-ANS-03 | Resolve citations to an immutable evidence snapshot plus an authorized source deep link where possible. |
| FR-ANS-04 | Validate that cited evidence exists, is accessible, supports the associated claim, and uses the correct time/entity. |
| FR-ANS-05 | Repair invalid responses once under policy, then omit unsupported claims or abstain. |
| FR-ANS-06 | Never imply causation from correlation unless the evidence explicitly establishes it. |
| FR-ANS-07 | Display contradictory evidence and meaningful data-freshness warnings. |
| FR-ANS-08 | Keep retrieved evidence and generated content visually distinct. |

### 9.6 User experience and workflow

| ID | Requirement |
|---|---|
| FR-UX-01 | Let a user open an existing incident or begin an ad hoc investigation. |
| FR-UX-02 | Provide question history, filters, evidence cards, timeline, graph neighborhood, and source links. |
| FR-UX-03 | Let users mark an answer or citation useful, incorrect, outdated, unsupported, or access-sensitive. |
| FR-UX-04 | Do not expose hidden content through typeahead, related-item suggestions, or graph visualization. |
| FR-UX-05 | Support sharing only by reference; every recipient must independently reauthorize the content. |

### 9.7 Evaluation, administration, and audit

| ID | Requirement |
|---|---|
| FR-EVAL-01 | Maintain versioned datasets with queries, incident context, relevant evidence, expected facts, forbidden facts, and user personas. |
| FR-EVAL-02 | Evaluate individual retrieval channels, fusion, reranking, generation, citations, abstention, ACL safety, latency, and cost. |
| FR-EVAL-03 | Split train/tuning and test data by incident and time to prevent leakage. |
| FR-EVAL-04 | Block promotion when hard security, citation, quality, latency, or cost gates fail. |
| FR-EVAL-05 | Capture production traces with prompt, model, retriever, policy, and index versions using content-safe logging. |
| FR-ADM-01 | Show connector state, freshness, dead letters, index versions, policy status, and model configuration. |
| FR-ADM-02 | Audit connector, policy, prompt, model, evaluation, and curator changes. |

## 10. Business rules

1. Source-system permissions remain authoritative; the platform may narrow but never broaden them.
2. Deny rules override allow rules. Tenant separation is mandatory at every storage and cache boundary.
3. Permission state that cannot be proven valid is treated as denied.
4. Evidence time and ingestion time are distinct. Ranking uses evidence/event time when available.
5. A claim is material if it states an event, metric, state, ownership, dependency, change, impact, or causal relationship.
6. Material factual claims require accessible supporting evidence. A citation is not valid merely because it is topically related.
7. Inferences and suggested diagnostic steps must be labeled and cannot be presented as observed facts.
8. Evidence snapshots are immutable for audit, subject to retention and deletion obligations.
9. Evaluation records use synthetic or authorized content and must preserve the tested persona's access boundary.
10. User feedback cannot directly modify production prompts or rankers without review, evaluation, and versioned promotion.

## 11. Non-functional requirements

| Category | Requirement |
|---|---|
| Security | Encryption in transit and at rest; managed secrets; private connectivity where required; least-privilege service identities; dependency and image scanning. |
| Privacy | Data minimization, configurable redaction, retention, purpose limitation, export/deletion support, and no provider training on customer data. |
| Availability | Proposed MVP monthly availability of 99.5%, excluding planned maintenance; graceful degraded evidence-only search if generation fails. |
| Recovery | Proposed RPO of 15 minutes for configuration/metadata and 24 hours for rebuildable indexes; RTO of 4 hours. |
| Performance | Meet the p95 targets in Section 4 at agreed pilot concurrency; stream progressive results when useful. |
| Scalability | Horizontally scalable stateless APIs and workers; partition data by tenant and time; explicit graph and query limits. |
| Freshness | Per-source freshness SLOs with visible last-success and last-event timestamps. |
| Accessibility | Target WCAG 2.2 AA for the web experience. |
| Observability | Distributed traces, structured logs, metrics, cost attribution, correlation IDs, and source-safe diagnostics. |
| Maintainability | Typed interfaces, schema migration, infrastructure as code, automated tests, runbooks, and owned services. |
| Portability | Provider adapters for embeddings and language models; canonical source contracts; exportable evaluation datasets. |

## 12. Data governance and compliance

- Classify sources and fields before onboarding; define excluded data categories.
- Record the lawful/business purpose, owner, retention, residency, and deletion behavior per source.
- Encrypt tenant-specific data with platform or customer-managed keys according to policy.
- Never place secrets, access tokens, raw credentials, or unredacted sensitive payloads in prompts, traces, or evaluation exports.
- Maintain an auditable lineage from generated claim to chunk, source object/version, connector run, and policy version.
- Define model-provider terms, regional processing, retention, and abuse-monitoring behavior before production use.
- Perform a threat model and privacy/security review before the pilot and after material architecture changes.

## 13. Core user journeys

### 13.1 Investigate an active incident

1. The responder opens an incident and is authenticated.
2. The platform resolves the responder's tenant, groups, roles, and source identities.
3. The platform loads incident metadata and suggests a safe, authorized evidence view.
4. The responder asks, “What changed before latency increased?”
5. Retrieval correlates the incident window, affected services, upstream/downstream graph, deployments, alerts, runbooks, and similar incidents.
6. The platform returns a structured answer with claim-level citations, a timeline, conflicts, and next checks.
7. The responder opens source evidence, refines the time/service filters, and provides feedback.

### 13.2 Search prior operational knowledge

1. An engineer asks a service-scoped question outside an active incident.
2. The platform retrieves accessible runbooks, postmortems, deployment records, and service relationships.
3. The response distinguishes current instructions from superseded or historical content.

### 13.3 Handle insufficient or forbidden evidence

1. Accessible results are missing, stale, or contradictory.
2. The platform does not reveal whether inaccessible results exist.
3. It returns the limitations, safe evidence, and suggested manual checks, or abstains.

## 14. Reporting and analytics

The product will report, by tenant/team and within privacy constraints:

- adoption, active investigators, questions per incident, and evidence opens;
- time-to-first-useful-evidence and comparison with the incident baseline;
- answer/citation feedback, abstention, unsupported-claim, and conflict rates;
- retrieval quality by source, service, query class, and incident phase;
- ACL denials and stale-policy failures without content leakage;
- ingestion freshness, failures, index lag, and deletion lag;
- latency, model/token use, storage, and estimated cost per investigation.

Metrics must not become a mechanism for individual employee performance surveillance.

## 15. Dependencies

- Identity-provider application, claims, group synchronization, and test personas.
- Read-only credentials and API quotas for selected source systems.
- Service catalog quality and stable service identifiers.
- Historic, resolved incidents for evaluation and baselining.
- Approved cloud/runtime, model provider, networking, key management, and data stores.
- Security, privacy, legal, and source-owner review availability.
- Pilot-team participation for annotations, UAT, and weekly feedback.

## 16. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| ACL semantics differ by source | Data leakage | Source-specific policy adapters, deny-by-default contract, double authorization, adversarial tests |
| Permission updates lag indexes/caches | Revoked access persists | Event-driven invalidation, short safe TTLs, final authorization, revocation SLO monitoring |
| Poor service identifiers | Graph and ranking errors | Canonical ID registry, aliases, curator workflow, confidence and provenance |
| Raw telemetry volume is excessive | Cost and latency | On-demand querying, event aggregation, strict windows, sampling, retention tiers |
| Temporal correlation is mistaken for causation | Misleading triage | Language constraints, evidence labeling, citation entailment, human confirmation |
| Weak historic labels | Misleading evaluation | Expert adjudication, inter-rater checks, time/incident split, confidence flags |
| Model/provider changes regress behavior | Quality drift | Version pinning, canary evaluation, release gates, rollback |
| Users over-trust generated content | Operational risk | Evidence-first UX, uncertainty, clear advisory status, training, no autonomous actions |
| Too many stateful systems | Operational burden | Architecture decision record and volume-based choice; managed services where appropriate |
| Source outage or quota limits | Stale evidence | Backoff, checkpointing, stale-data indicator, degraded mode |

## 17. UAT and MVP acceptance

MVP is accepted only when all of the following are true:

1. Selected source connectors complete backfill, incremental update, permission change, and deletion scenarios.
2. All critical data paths pass tenant-isolation and persona-based ACL tests, including caches, citations, graph traversal, logs, and exports.
3. Retrieval, citation, grounding, latency, freshness, and usefulness meet the agreed pilot gates.
4. Every answer displays evidence, limitations, generation time, and source freshness; unsupported responses abstain safely.
5. Disaster recovery, key rotation, connector outage, model outage, rollback, and index rebuild procedures are exercised.
6. Security/privacy reviews have no unresolved critical or high findings.
7. Pilot responders complete the core journeys and the product owner signs off.
8. Operational ownership, dashboards, alerts, runbooks, support process, and on-call escalation are documented.

## 18. Approval and change control

Product, engineering, security, privacy/legal, SRE, and pilot-team representatives approve the baseline BRD. Changes affecting source scope, access policy, data residency, autonomous actions, model providers, or acceptance gates require explicit review and a versioned update.

## 19. Decisions required during discovery

1. Pilot teams, regions, expected concurrency, and target incident types.
2. Source vendors and authoritative identity/ACL semantics for each.
3. Hosting environment, tenancy model, data residency, and retention.
4. Approved embedding, reranking, and generation providers/models.
5. Whether telemetry is indexed, summarized, or queried on demand per source.
6. Graph-store choice and acceptable operational footprint.
7. Baseline incident metrics and final MVP quality/latency/cost gates.
8. Evidence snapshot and source-deletion policy where audit and deletion requirements conflict.
