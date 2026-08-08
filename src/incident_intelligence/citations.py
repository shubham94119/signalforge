"""Deterministic citation and claim validation around generated answers."""

from __future__ import annotations

import re
from collections.abc import Mapping

from .models import AnswerDraft, CitationValidationResult, Evidence, QueryContext
from .policy import PolicyEnforcer
from .retrieval import _tokens


_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?%?\b")


class CitationValidator:
    """Validate citation existence, authorization, attribution, and support."""

    def __init__(self, policy: PolicyEnforcer, minimum_support: float = 0.25) -> None:
        self.policy = policy
        self.minimum_support = minimum_support

    @staticmethod
    def _support_score(claim_text: str, evidence: Evidence) -> float:
        # Citation text often includes a label such as ``Title:``. Normalize
        # punctuation at token boundaries without removing meaningful source
        # identifiers such as ``service:payments`` from their interior.
        strip_chars = ".,;:!?()[]{}"
        claim_tokens = {token.strip(strip_chars) for token in _tokens(claim_text)} - {""}
        evidence_tokens = {
            token.strip(strip_chars) for token in _tokens(f"{evidence.title} {evidence.content}")
        } - {""}
        if not claim_tokens:
            return 0.0
        overlap = len(claim_tokens.intersection(evidence_tokens)) / len(claim_tokens)
        claim_numbers = set(_NUMBER_RE.findall(claim_text))
        evidence_numbers = set(_NUMBER_RE.findall(f"{evidence.title} {evidence.content}"))
        if claim_numbers and not claim_numbers.issubset(evidence_numbers):
            return 0.0
        return overlap

    def validate(
        self,
        answer: AnswerDraft,
        evidence: Mapping[str, Evidence],
        query: QueryContext,
    ) -> CitationValidationResult:
        issues: list[str] = []
        accepted: list[str] = []
        seen_claim_ids: set[str] = set()
        for claim in answer.claims:
            if claim.claim_id in seen_claim_ids:
                issues.append(f"{claim.claim_id}: duplicate claim id")
                continue
            seen_claim_ids.add(claim.claim_id)
            claim_valid = True
            if claim.claim_type not in {"observed", "source_asserted", "inferred", "suggested"}:
                issues.append(f"{claim.claim_id}: unknown claim type")
                claim_valid = False
            if not claim.material:
                if claim_valid:
                    accepted.append(claim.claim_id)
                continue
            if not claim.citation_ids:
                issues.append(f"{claim.claim_id}: material claim has no citation")
                continue

            for citation_id in claim.citation_ids:
                item = evidence.get(citation_id)
                if item is None:
                    issues.append(f"{claim.claim_id}: missing citation {citation_id}")
                    claim_valid = False
                    continue
                decision = self.policy.authorize(item, query.identity)
                if not decision.allowed:
                    issues.append(f"{claim.claim_id}: unauthorized citation {citation_id}")
                    claim_valid = False
                    continue
                support = self._support_score(claim.text, item)
                if support < self.minimum_support:
                    issues.append(
                        f"{claim.claim_id}: citation {citation_id} support {support:.2f} "
                        f"below {self.minimum_support:.2f}"
                    )
                    claim_valid = False
            if claim_valid:
                accepted.append(claim.claim_id)

        return CitationValidationResult(not issues, tuple(issues), tuple(accepted))
