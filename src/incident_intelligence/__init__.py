"""Incident-intelligence foundation.

The package deliberately has no runtime dependency on a particular search
engine, graph database, or model provider. Those integrations can implement
the interfaces in the individual modules as the platform moves beyond the
in-memory pilot slice.
"""

from .models import (
    ACL,
    AnswerDraft,
    Claim,
    Evidence,
    IdentityContext,
    QueryContext,
    RetrievalResult,
    FeedbackRecord,
)
from .policy import AuthorizationDecision, PolicyEnforcer
from .ingestion import InMemoryEvidenceStore, IngestionPipeline, SourceRecord
from .persistence import SQLiteEvidenceStore
from .retrieval import HybridRetriever
from .citations import CitationValidationResult, CitationValidator
from .answering import (
    AuthorizedContextBuilder,
    DeterministicAnswerer,
    GroundedResponse,
    GroundedTriageService,
)
from .evaluation import EvaluationCase, EvaluationDataset, EvaluationGate, EvaluationReport, EvaluationRunner
from .model_gateway import GenerationConfig, ModelBackedAnswerer, OpenAICompatibleGateway

__all__ = [
    "ACL",
    "AnswerDraft",
    "Claim",
    "Evidence",
    "IdentityContext",
    "QueryContext",
    "RetrievalResult",
    "FeedbackRecord",
    "AuthorizationDecision",
    "PolicyEnforcer",
    "InMemoryEvidenceStore",
    "SQLiteEvidenceStore",
    "IngestionPipeline",
    "SourceRecord",
    "HybridRetriever",
    "CitationValidationResult",
    "CitationValidator",
    "AuthorizedContextBuilder",
    "DeterministicAnswerer",
    "GroundedResponse",
    "GroundedTriageService",
    "EvaluationCase",
    "EvaluationDataset",
    "EvaluationGate",
    "EvaluationReport",
    "EvaluationRunner",
    "GenerationConfig",
    "ModelBackedAnswerer",
    "OpenAICompatibleGateway",
]
