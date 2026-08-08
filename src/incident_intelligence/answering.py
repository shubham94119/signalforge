"""Grounded triage orchestration around retrieval and citation validation.

The answerer is a replaceable provider boundary. The included deterministic
answerer is intentionally modest: it turns authorized evidence into clearly
attributed source assertions, which gives the rest of the pipeline a usable
local contract before a language-model provider is selected.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Protocol, Sequence

from .citations import CitationValidator
from .models import (
    AnswerDraft,
    Claim,
    CitationValidationResult,
    Evidence,
    QueryContext,
    RetrievalResult,
)
from .policy import PolicyEnforcer
from .retrieval import HybridRetriever


@dataclass(frozen=True)
class ContextEvidence:
    citation_id: str
    evidence: Evidence
    snippet: str
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class GroundedContext:
    query: QueryContext
    evidence: tuple[ContextEvidence, ...]
    created_at: datetime

    def evidence_map(self) -> dict[str, Evidence]:
        return {item.citation_id: item.evidence for item in self.evidence}


@dataclass(frozen=True)
class EvidenceCard:
    citation_id: str
    evidence_id: str
    title: str
    snippet: str
    source_type: str
    source_url: str | None
    event_time: datetime | None
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class GroundedResponse:
    answer_id: str
    status: str
    summary: str
    claims: tuple[Claim, ...]
    evidence: tuple[EvidenceCard, ...]
    limitations: tuple[str, ...]
    validation: CitationValidationResult
    generated_at: datetime


class Answerer(Protocol):
    def generate(self, context: GroundedContext) -> AnswerDraft: ...


def _snippet(content: str, max_chars: int) -> str:
    normalized = " ".join(content.split())
    if len(normalized) <= max_chars:
        return normalized
    sentence = re.split(r"(?<=[.!?])\s+", normalized, maxsplit=1)[0]
    if len(sentence) <= max_chars:
        return sentence
    return normalized[: max_chars - 1].rstrip() + "…"


class AuthorizedContextBuilder:
    """Build a bounded context and recheck authorization at the model boundary."""

    def __init__(self, policy: PolicyEnforcer, max_evidence: int = 8, max_chars_per_item: int = 1200) -> None:
        self.policy = policy
        self.max_evidence = max_evidence
        self.max_chars_per_item = max_chars_per_item

    def build(self, query: QueryContext, results: Sequence[RetrievalResult]) -> GroundedContext:
        selected: list[ContextEvidence] = []
        for index, result in enumerate(results[: self.max_evidence], start=1):
            decision = self.policy.authorize(result.evidence, query.identity)
            if not decision.allowed:
                # Retrieval already filters, but this is a mandatory final check
                # immediately before content enters a model context.
                continue
            selected.append(
                ContextEvidence(
                    citation_id=f"E{index}",
                    evidence=result.evidence,
                    snippet=_snippet(result.evidence.content, self.max_chars_per_item),
                    score=result.score,
                    reasons=result.reasons,
                )
            )
        return GroundedContext(query=query, evidence=tuple(selected), created_at=datetime.now(timezone.utc))


class DeterministicAnswerer:
    """Local evidence-first answerer used until an LLM gateway is configured."""

    def __init__(self, max_claims: int = 3) -> None:
        self.max_claims = max_claims

    def generate(self, context: GroundedContext) -> AnswerDraft:
        claims: list[Claim] = []
        for item in context.evidence[: self.max_claims]:
            text = f"{item.evidence.title}: {item.snippet}"
            claims.append(
                Claim(
                    claim_id=f"claim-{item.citation_id}",
                    text=text,
                    citation_ids=(item.citation_id,),
                    claim_type="source_asserted",
                    material=True,
                )
            )
        if not claims:
            summary = "No accessible evidence was found for this question."
        else:
            summary = f"Found {len(claims)} authorized evidence item(s) relevant to the question."
        digest = hashlib.sha256(context.query.text.encode("utf-8")).hexdigest()[:12]
        return AnswerDraft(answer_id=f"local-{digest}", claims=tuple(claims), summary=summary)


class GroundedTriageService:
    """Retrieve, assemble, answer, validate, and fail safely."""

    def __init__(
        self,
        retriever: HybridRetriever,
        validator: CitationValidator,
        answerer: Answerer | None = None,
        context_builder: AuthorizedContextBuilder | None = None,
    ) -> None:
        self.retriever = retriever
        self.validator = validator
        self.answerer = answerer or DeterministicAnswerer()
        self.context_builder = context_builder or AuthorizedContextBuilder(retriever.policy)

    def investigate(self, query: QueryContext, limit: int = 8) -> GroundedResponse:
        results = self.retriever.search(query, limit=limit)
        context = self.context_builder.build(query, results)
        cards = tuple(
            EvidenceCard(
                citation_id=item.citation_id,
                evidence_id=item.evidence.evidence_id,
                title=item.evidence.title,
                snippet=item.snippet,
                source_type=item.evidence.source_type,
                source_url=item.evidence.source_url,
                event_time=item.evidence.event_time,
                score=item.score,
                reasons=item.reasons,
            )
            for item in context.evidence
        )
        generated_at = datetime.now(timezone.utc)
        if not context.evidence:
            empty_validation = CitationValidationResult(True, (), ())
            return GroundedResponse(
                answer_id="no-evidence",
                status="insufficient_evidence",
                summary="No accessible evidence was found for this question.",
                claims=(),
                evidence=cards,
                limitations=("The answer is limited by the current user's accessible and fresh sources.",),
                validation=empty_validation,
                generated_at=generated_at,
            )

        draft = self.answerer.generate(context)
        validation = self.validator.validate(draft, context.evidence_map(), query)
        accepted_ids = set(validation.accepted_claim_ids)
        accepted_claims = tuple(claim for claim in draft.claims if claim.claim_id in accepted_ids)
        limitations = list(validation.issues)
        if validation.valid:
            status = "grounded"
            summary = draft.summary or "Grounded response generated from authorized evidence."
        elif accepted_claims:
            status = "partial"
            summary = "Only claims that passed citation and authorization checks are shown."
            limitations.append("Unsupported or unsafe claims were omitted.")
        else:
            status = "evidence_only"
            summary = "Evidence was found, but no generated claim passed validation."
            limitations.append("Review the evidence cards directly; no grounded summary is available.")
        return GroundedResponse(
            answer_id=draft.answer_id,
            status=status,
            summary=summary,
            claims=accepted_claims,
            evidence=cards,
            limitations=tuple(dict.fromkeys(limitations)),
            validation=validation,
            generated_at=generated_at,
        )
