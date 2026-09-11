from enum import StrEnum


class DeploymentProfile(StrEnum):
    HOSTED = "hosted"
    PRIVATE = "private"


class AuthMode(StrEnum):
    DEMO = "demo"
    OIDC = "oidc"


class ModelProvider(StrEnum):
    FIXTURE = "fixture"
    HOSTED = "hosted"
    PRIVATE = "private"


class Role(StrEnum):
    VIEWER = "viewer"
    ANALYST = "analyst"
    CATALOG_EDITOR = "catalog_editor"
    DRAFTER = "drafter"
    REVIEWER = "reviewer"
    ADMIN = "admin"


class SourceType(StrEnum):
    POLICY = "policy"
    FAQ = "faq"
    HISTORICAL_PLAN = "historical_plan"
    PRODUCT = "product"
    OPERATIONAL = "operational"
    PRICE_FEED = "price_feed"
    IMAGE = "image"
    FEEDBACK = "feedback"


class AuthorityClass(StrEnum):
    CURRENT_POLICY = "current_policy"
    GUIDANCE = "guidance"
    HISTORICAL_EXAMPLE = "historical_example"
    OPERATIONAL_FACT = "operational_fact"
    UNTRUSTED_OBSERVATION = "untrusted_observation"


class LifecycleStatus(StrEnum):
    RECEIVED = "received"
    QUARANTINED = "quarantined"
    EXTRACTED = "extracted"
    VALIDATED = "validated"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    INDEXED = "indexed"
    PUBLISHED = "published"
    FAILED = "failed"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"


class Visibility(StrEnum):
    PUBLIC_WORKSPACE = "public_workspace"
    RESTRICTED = "restricted"
    REVIEWER_ONLY = "reviewer_only"


class Language(StrEnum):
    EN = "en"
    ID = "id"
    MIXED = "mixed"


class JobType(StrEnum):
    INGEST = "ingest"
    INDEX = "index"
    QUESTION = "question"
    ANALYTICS = "analytics"
    DRAFT = "draft"
    EXPORT = "export"
    LISTING_CHECK = "listing_check"
    SOURCING_EVAL = "sourcing_eval"
    AUDIT_EXPORT = "audit_export"
    PRICE_REFRESH = "price_refresh"


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class AnswerStatus(StrEnum):
    ANSWERED = "answered"
    NEEDS_CLARIFICATION = "needs_clarification"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    OUT_OF_SCOPE = "out_of_scope"
    UNAVAILABLE = "unavailable"


class DraftState(StrEnum):
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class FindingState(StrEnum):
    NEW = "new"
    TRIAGED = "triaged"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"
    NOT_EVALUABLE = "not_evaluable"


class FindingSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MatchLabel(StrEnum):
    SAME_PRODUCT = "same_product"
    COMPARABLE_PRODUCT = "comparable_product"
    NOT_COMPARABLE = "not_comparable"


class AnalyticsPattern(StrEnum):
    SPENDING_BY_PERIOD = "spending_by_period"
    ORDER_COUNTS_BY_STATUS = "order_counts_by_status"
    SUPPLIER_CONCENTRATION = "supplier_concentration"
    PRICE_VARIATION = "price_variation"
    ADDITIONAL_SERVICE_CHARGES = "additional_service_charges"
    SOURCING_OUTCOMES = "sourcing_outcomes"


class TemplateKind(StrEnum):
    EQUIPMENT_REQUIREMENTS = "equipment_requirements"
    MAINTENANCE_SERVICE = "maintenance_service"
    INSTALLATION_WORK = "installation_work"
    RECURRING_SERVICE = "recurring_service"
