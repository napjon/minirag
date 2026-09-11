from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from backend.domain.enums import (
    AnalyticsPattern,
    AnswerStatus,
    FindingSeverity,
    FindingState,
    JobState,
    Language,
    MatchLabel,
    Role,
    TemplateKind,
)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    workspace_id: UUID
    principal_id: UUID
    roles: list[Role]
    display_name: str


class DemoLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    workspace: str = Field(default="harbor", min_length=1, max_length=64)


class EvidenceRef(BaseModel):
    document_id: UUID
    document_version_id: UUID
    chunk_id: UUID
    section_path: str
    page_or_table_location: str
    supporting_span: str
    source_effective_date: date | None = None
    authorized_viewer_url: str


class ExecutionManifest(BaseModel):
    model_provider: str
    generation_model: str
    embedding_revision: str
    parser_version: str
    prompt_revision: str
    retrieval: dict[str, Any] = Field(default_factory=dict)
    token_input: int = 0
    token_output: int = 0
    cost_usd: Decimal = Decimal("0")
    stage_ms: dict[str, int] = Field(default_factory=dict)


class Envelope(BaseModel):
    request_id: str
    status: str
    result: Any = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    execution_manifest_id: UUID | None = None


class QuestionRequest(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    language: Language | None = None
    as_of: date | None = None
    conversation_id: UUID | None = None
    idempotency_key: str | None = None


class QuestionResult(BaseModel):
    status: AnswerStatus
    answer: str | None = None
    language: Language
    limitations: str | None = None
    claims: list[dict[str, Any]] = Field(default_factory=list)


class AnalyticsQueryRequest(BaseModel):
    question: str | None = None
    pattern: AnalyticsPattern | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    group_by: list[str] = Field(default_factory=list)
    presentation: Literal["table", "bar", "line"] = "table"
    idempotency_key: str | None = None


class ProductSearchRequest(BaseModel):
    query: str = Field(default="", max_length=1000)
    category: str | None = Field(default=None, max_length=128)
    min_price: Decimal | None = Field(default=None, max_digits=18, decimal_places=4)
    max_price: Decimal | None = Field(default=None, max_digits=18, decimal_places=4)
    location: str | None = Field(default=None, max_length=128)
    available_only: bool = True
    attributes: dict[str, Any] = Field(default_factory=dict)
    preferences: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=10, ge=1, le=50)


class ProductCompareRequest(BaseModel):
    product_ids: list[UUID] = Field(min_length=2, max_length=6)


class ListingCheckRequest(BaseModel):
    product_id: UUID
    idempotency_key: str | None = None


class SourcingEvalRequest(BaseModel):
    event_id: UUID
    idempotency_key: str | None = None


class IngestDocumentRequest(BaseModel):
    source_id: UUID
    title: str
    topic: str = "account-access"
    language: str = "en"
    idempotency_key: str


class SourceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    source_type: str = Field(default="policy", min_length=1, max_length=64)
    authority_class: str = Field(default="current_policy", min_length=1, max_length=64)
    owner_role: str = Field(default="admin", min_length=1, max_length=64)
    allowed_groups: list[str] = Field(default_factory=list, max_length=100)


class DraftCreateRequest(BaseModel):
    template_kind: TemplateKind
    title: str = Field(min_length=1, max_length=300)
    brief: dict[str, Any]
    idempotency_key: str = Field(min_length=1, max_length=200)


class DraftReviewRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    reason: str = Field(default="", max_length=2000)
    revision_hash: str = Field(min_length=1, max_length=128)


class FeedbackRequest(BaseModel):
    target_type: str = Field(min_length=1, max_length=64)
    target_id: UUID
    label: str = Field(min_length=1, max_length=64)
    comment: str = Field(default="", max_length=10000)
    idempotency_key: str = Field(min_length=1, max_length=200)


class JobView(BaseModel):
    id: UUID
    job_type: str
    state: JobState
    progress: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None


class FindingView(BaseModel):
    id: UUID
    detector_id: str
    detector_version: str
    severity: FindingSeverity
    state: FindingState
    explanation: str
    evidence: dict[str, Any]


class MatchResult(BaseModel):
    left_id: UUID
    right_id: UUID
    label: MatchLabel
    score: float
    reasons: list[str]
