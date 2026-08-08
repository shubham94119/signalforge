"""Fail-closed authorization checks used by every retrieval path."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Mapping

from .models import Evidence, IdentityContext


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    reason: str


class PolicyEnforcer:
    """Evaluate source ACLs against a trusted request identity.

    The enforcer is intentionally small and deterministic. Production source
    adapters may resolve a live policy, but they must return the same decision
    contract and must fail closed when that resolution fails.
    """

    def __init__(self, current_policy_versions: Mapping[str, str] | None = None) -> None:
        self._current_policy_versions = dict(current_policy_versions or {})

    def authorize(self, evidence: Evidence, identity: IdentityContext) -> AuthorizationDecision:
        if evidence.tenant_id != identity.tenant_id:
            return AuthorizationDecision(False, "tenant_mismatch")
        if evidence.acl.tenant_id != identity.tenant_id:
            return AuthorizationDecision(False, "acl_tenant_mismatch")

        expected_version = identity.policy_versions.get(evidence.source_instance)
        configured_version = self._current_policy_versions.get(evidence.source_instance)
        if configured_version is not None:
            expected_version = configured_version
        if expected_version is not None and expected_version != evidence.acl.source_policy_version:
            return AuthorizationDecision(False, "stale_policy")

        now = datetime.now(timezone.utc)
        if evidence.acl.expires_at is not None and evidence.acl.expires_at <= now:
            return AuthorizationDecision(False, "expired_policy")

        principals = identity.principal_ids()
        if principals.intersection(evidence.acl.denied_principals):
            return AuthorizationDecision(False, "explicit_deny")
        if evidence.acl.public_within_tenant:
            return AuthorizationDecision(True, "tenant_public")
        if principals.intersection(evidence.acl.allowed_principals):
            return AuthorizationDecision(True, "principal_allow")
        return AuthorizationDecision(False, "no_matching_allow")

    def filter_authorized(self, evidence: Iterable[Evidence], identity: IdentityContext) -> list[Evidence]:
        return [item for item in evidence if self.authorize(item, identity).allowed]
