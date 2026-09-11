from __future__ import annotations

from decimal import Decimal, InvalidOperation
from statistics import median
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.security import AuthContext
from backend.auth.visibility import can_read_product
from backend.domain.enums import FindingSeverity, FindingState, JobState, JobType
from backend.domain.models import DetectionFinding, Job, PriceObservation, Product, SourcingEvent
from backend.jobs.service import JobService

RULES = [
    {
        "rule_id": "low_participation",
        "rule_version": "1",
        "minimum_sample_size": 1,
        "severity": FindingSeverity.MEDIUM.value,
        "predicate": lambda event: event.participant_count < 3,
        "explanation": "Very low participation for this sourcing event.",
    },
    {
        "rule_id": "award_concentration",
        "rule_version": "1",
        "minimum_sample_size": 1,
        "severity": FindingSeverity.HIGH.value,
        "predicate": lambda event: False,
        "explanation": "Repeated award concentration within a category.",
    },
    {
        "rule_id": "submission_clustering",
        "rule_version": "1",
        "minimum_sample_size": 3,
        "severity": FindingSeverity.MEDIUM.value,
        "predicate": lambda event: _clustered(event.submission_times),
        "explanation": "Unusual clustering of submission times.",
    },
    {
        "rule_id": "offer_deviation",
        "rule_version": "1",
        "minimum_sample_size": 3,
        "severity": FindingSeverity.MEDIUM.value,
        "predicate": lambda event: _offer_outlier(event.offer_amounts),
        "explanation": "Offer-price deviation from the comparable cohort.",
    },
    {
        "rule_id": "co_participation",
        "rule_version": "1",
        "minimum_sample_size": 2,
        "severity": FindingSeverity.LOW.value,
        "predicate": lambda event: False,
        "explanation": "Repeated co-participation pattern requires investigation.",
    },
]


def repeated_co_participation(event, siblings) -> bool:
    pair = frozenset(event.participant_ids or [])
    if len(pair) < 2:
        return False
    for sibling in siblings:
        if getattr(sibling, "id", None) == getattr(event, "id", None):
            continue
        other = frozenset(sibling.participant_ids or [])
        if len(pair & other) >= 2:
            return True
    return False


def _clustered(times: list[str] | None) -> bool:
    if not times or len(times) < 3:
        return False
    seconds = sorted(times)
    return seconds[0] == seconds[-1] or len(set(seconds)) == 1


def _offer_outlier(amounts: list[str] | None) -> bool:
    if not amounts or len(amounts) < 3:
        return False
    values = _parse_amounts(amounts)
    if values is None:
        return False
    m = median(values)
    return any(v > m * Decimal("2") or v < m / Decimal("2") for v in values)


def _parse_amounts(amounts: list[str] | None) -> list[Decimal] | None:
    if not amounts:
        return None
    try:
        return [Decimal(a) for a in amounts]
    except (InvalidOperation, TypeError, ValueError):
        return None


def _quantile(values: list[Decimal], q: float) -> Decimal:
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(q * (len(ordered) - 1))))
    return ordered[idx]


class DetectionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def listing_checks(
        self, auth: AuthContext, product_id: UUID, idempotency_key: str | None = None
    ) -> list[DetectionFinding]:
        job = await self._job_if_key(auth, JobType.LISTING_CHECK.value, idempotency_key)
        cached = await self._findings_from_succeeded_job(auth, job)
        if cached is not None:
            return cached
        product = await self.db.scalar(
            select(Product).where(
                Product.workspace_id == auth.workspace_id, Product.id == product_id
            )
        )
        if product is None or not can_read_product(auth, visibility=product.visibility):
            return await self._finish_job(job, [])
        findings: list[DetectionFinding] = []
        required = ["capacity", "model"]
        missing = [key for key in required if key not in (product.attributes or {})]
        if missing:
            findings.append(
                self._finding(
                    auth,
                    entity_type="product",
                    entity_id=product.id,
                    revision=product.revision,
                    detector_id="spec_consistency",
                    explanation=f"Missing required attributes: {', '.join(missing)}",
                    severity=FindingSeverity.MEDIUM.value,
                    evidence={"missing": missing},
                )
            )
        if product.category not in {
            "network-gear",
            "site-power",
            "field-tools",
            "maintenance",
            "installation",
        }:
            findings.append(
                self._finding(
                    auth,
                    entity_type="product",
                    entity_id=product.id,
                    revision=product.revision,
                    detector_id="category_consistency",
                    explanation="Category is outside the approved catalog taxonomy.",
                    severity=FindingSeverity.HIGH.value,
                    evidence={"category": product.category},
                )
            )
        observations = list(
            (
                await self.db.scalars(
                    select(PriceObservation).where(
                        PriceObservation.workspace_id == auth.workspace_id,
                        PriceObservation.product_id == product.id,
                        PriceObservation.comparable.is_(True),
                    )
                )
            ).all()
        )
        amounts = [o.amount for o in observations if o.currency == product.currency]
        if len(amounts) >= 30:
            q1 = _quantile(amounts, 0.25)
            q3 = _quantile(amounts, 0.75)
            iqr = q3 - q1
            if product.list_price > q3 + Decimal("3") * iqr:
                findings.append(
                    self._finding(
                        auth,
                        entity_type="product",
                        entity_id=product.id,
                        revision=product.revision,
                        detector_id="product_price",
                        explanation="List price is above Q3 + 3×IQR of the comparable cohort.",
                        severity=FindingSeverity.HIGH.value,
                        evidence={
                            "list_price": str(product.list_price),
                            "q3": str(q3),
                            "iqr": str(iqr),
                        },
                    )
                )
        elif amounts:
            findings.append(
                self._finding(
                    auth,
                    entity_type="product",
                    entity_id=product.id,
                    revision=product.revision,
                    detector_id="product_price",
                    explanation="Insufficient comparable observations for a price signal.",
                    severity=FindingSeverity.LOW.value,
                    evidence={"sample_count": len(amounts)},
                    state=FindingState.NOT_EVALUABLE.value,
                )
            )
        persisted = await self._persist_findings(
            auth,
            entity_type="product",
            entity_id=product.id,
            revision=product.revision,
            findings=findings,
        )
        return await self._finish_job(job, persisted)

    async def sourcing_eval(
        self, auth: AuthContext, event_id: UUID, idempotency_key: str | None = None
    ) -> list[DetectionFinding]:
        job = await self._job_if_key(auth, JobType.SOURCING_EVAL.value, idempotency_key)
        cached = await self._findings_from_succeeded_job(auth, job)
        if cached is not None:
            return cached
        event = await self.db.scalar(
            select(SourcingEvent).where(
                SourcingEvent.workspace_id == auth.workspace_id, SourcingEvent.id == event_id
            )
        )
        if event is None:
            return await self._finish_job(job, [])
        siblings = list(
            (
                await self.db.scalars(
                    select(SourcingEvent).where(
                        SourcingEvent.workspace_id == auth.workspace_id,
                        SourcingEvent.category == event.category,
                        SourcingEvent.closed_at <= event.closed_at,
                        SourcingEvent.id != event.id,
                    )
                )
            ).all()
        )
        findings: list[DetectionFinding] = []
        for rule in RULES:
            if rule["rule_id"] == "award_concentration":
                winners = [s.winner_id for s in siblings if s.winner_id and s.id != event.id]
                triggered = winners.count(event.winner_id) >= 3 if event.winner_id else False
            elif rule["rule_id"] == "co_participation":
                triggered = repeated_co_participation(event, siblings)
            else:
                sample_ok = True
                if rule["rule_id"] == "submission_clustering":
                    sample_ok = len(event.submission_times or []) >= rule["minimum_sample_size"]
                elif rule["rule_id"] == "offer_deviation":
                    sample_ok = (
                        len(event.offer_amounts or []) >= rule["minimum_sample_size"]
                        and _parse_amounts(event.offer_amounts) is not None
                    )
                if not sample_ok:
                    findings.append(
                        self._finding(
                            auth,
                            entity_type="sourcing_event",
                            entity_id=event.id,
                            revision=event.revision,
                            detector_id=rule["rule_id"],
                            detector_version=rule["rule_version"],
                            explanation="not_evaluable: required fields or sample size missing",
                            severity=rule["severity"],
                            evidence={"event_id": str(event.id)},
                            state=FindingState.NOT_EVALUABLE.value,
                        )
                    )
                    continue
                triggered = rule["predicate"](event)
            if triggered:
                findings.append(
                    self._finding(
                        auth,
                        entity_type="sourcing_event",
                        entity_id=event.id,
                        revision=event.revision,
                        detector_id=rule["rule_id"],
                        detector_version=rule["rule_version"],
                        explanation=rule["explanation"],
                        severity=rule["severity"],
                        evidence={
                            "event_id": str(event.id),
                            "participants": event.participant_ids,
                            "winner_id": event.winner_id,
                        },
                    )
                )
        persisted = await self._persist_findings(
            auth,
            entity_type="sourcing_event",
            entity_id=event.id,
            revision=event.revision,
            findings=findings,
        )
        return await self._finish_job(job, persisted)

    async def get(self, auth: AuthContext, finding_id: UUID) -> DetectionFinding | None:
        finding = await self.db.get(DetectionFinding, finding_id)
        if finding is None or finding.workspace_id != auth.workspace_id:
            return None
        return finding

    def _finding(
        self,
        auth: AuthContext,
        *,
        entity_type: str,
        entity_id: UUID,
        revision: int,
        detector_id: str,
        explanation: str,
        severity: str,
        evidence: dict,
        detector_version: str = "1",
        state: str = FindingState.NEW.value,
    ) -> DetectionFinding:
        return DetectionFinding(
            workspace_id=auth.workspace_id,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_revision=revision,
            detector_id=detector_id,
            detector_version=detector_version,
            severity=severity,
            state=state,
            explanation=explanation,
            evidence=evidence,
        )

    async def _job_if_key(
        self, auth: AuthContext, job_type: str, idempotency_key: str | None
    ) -> Job | None:
        if not idempotency_key:
            return None
        return await JobService(self.db).create_or_get(
            auth, job_type=job_type, idempotency_key=idempotency_key
        )

    async def _findings_from_succeeded_job(
        self, auth: AuthContext, job: Job | None
    ) -> list[DetectionFinding] | None:
        if job is None or job.state != JobState.SUCCEEDED.value or not isinstance(job.result, dict):
            return None
        if "finding_ids" not in job.result:
            return None
        raw_ids = job.result.get("finding_ids") or []
        ids = [item if isinstance(item, UUID) else UUID(str(item)) for item in raw_ids]
        if not ids:
            return []
        rows = list(
            (
                await self.db.scalars(
                    select(DetectionFinding).where(
                        DetectionFinding.workspace_id == auth.workspace_id,
                        DetectionFinding.id.in_(ids),
                    )
                )
            ).all()
        )
        by_id = {row.id: row for row in rows}
        return [by_id[item] for item in ids if item in by_id]

    async def _finish_job(
        self, job: Job | None, findings: list[DetectionFinding]
    ) -> list[DetectionFinding]:
        if job is None:
            return findings
        job.result = {"finding_ids": [str(item.id) for item in findings]}
        job.state = JobState.SUCCEEDED.value
        job.progress = {"stage": "done"}
        await self.db.flush()
        return findings

    async def _persist_findings(
        self,
        auth: AuthContext,
        *,
        entity_type: str,
        entity_id: UUID,
        revision: int,
        findings: list[DetectionFinding],
    ) -> list[DetectionFinding]:
        detector_ids = [item.detector_id for item in findings]
        existing = await self._existing_findings(
            auth, entity_type, entity_id, revision, detector_ids
        )
        if existing:
            return existing
        if not findings:
            return []
        try:
            async with self.db.begin_nested():
                for finding in findings:
                    self.db.add(finding)
                await self.db.flush()
            return findings
        except IntegrityError:
            return await self._existing_findings(
                auth, entity_type, entity_id, revision, detector_ids
            )

    async def _existing_findings(
        self,
        auth: AuthContext,
        entity_type: str,
        entity_id: UUID,
        revision: int,
        detector_ids: list[str],
    ) -> list[DetectionFinding]:
        if not detector_ids:
            return []
        return list(
            (
                await self.db.scalars(
                    select(DetectionFinding).where(
                        DetectionFinding.workspace_id == auth.workspace_id,
                        DetectionFinding.entity_type == entity_type,
                        DetectionFinding.entity_id == entity_id,
                        DetectionFinding.entity_revision == revision,
                        DetectionFinding.detector_id.in_(detector_ids),
                    )
                )
            ).all()
        )
