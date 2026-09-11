from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from backend.auth.security import AuthContext
from backend.domain.enums import AnalyticsPattern
from backend.domain.models import OrderRecord, SourcingEvent, SpendRecord
from backend.model_gateway.base import ModelGateway

ALLOWED_GROUP_BY = {"month", "category", "status", "supplier_id"}
ALLOWED_CATEGORIES = {
    "network-gear",
    "site-power",
    "field-tools",
    "maintenance",
    "installation",
}

PATTERN_DEFAULTS: dict[str, list[str]] = {
    AnalyticsPattern.SPENDING_BY_PERIOD.value: ["month"],
    AnalyticsPattern.ORDER_COUNTS_BY_STATUS.value: ["status"],
    AnalyticsPattern.SUPPLIER_CONCENTRATION.value: ["supplier_id", "category"],
    AnalyticsPattern.PRICE_VARIATION.value: ["month", "category"],
    AnalyticsPattern.ADDITIONAL_SERVICE_CHARGES.value: ["category"],
    AnalyticsPattern.SOURCING_OUTCOMES.value: ["outcome"],
}

PATTERN_GROUP_KEYS: dict[str, set[str]] = {
    AnalyticsPattern.SPENDING_BY_PERIOD.value: {"month", "category", "supplier_id"},
    AnalyticsPattern.ORDER_COUNTS_BY_STATUS.value: {"month", "status", "category", "supplier_id"},
    AnalyticsPattern.SUPPLIER_CONCENTRATION.value: {"month", "category", "supplier_id"},
    AnalyticsPattern.PRICE_VARIATION.value: {"month", "category", "status", "supplier_id"},
    AnalyticsPattern.ADDITIONAL_SERVICE_CHARGES.value: {
        "month",
        "category",
        "status",
        "supplier_id",
    },
    AnalyticsPattern.SOURCING_OUTCOMES.value: {"month", "category"},
}


def _resolve_group_by(pattern: str, group_by: list[str]) -> list[str]:
    allowed = PATTERN_GROUP_KEYS.get(pattern, set())
    if group_by:
        unsupported = [g for g in group_by if g not in ALLOWED_GROUP_BY or g not in allowed]
        if unsupported:
            raise ValueError(
                f"group_by dimension(s) not supported for {pattern}: {', '.join(unsupported)}"
            )
    requested = list(group_by)
    if requested:
        return requested
    return list(PATTERN_DEFAULTS.get(pattern, ["month"]))


def _currency(filters: dict[str, Any]) -> str:
    return str(filters.get("currency") or "USD")


def _iso_date(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


def _spend_columns(grouped: list[str]) -> list[ColumnElement[Any]]:
    mapping: dict[str, ColumnElement[Any]] = {
        "month": func.date_trunc("month", SpendRecord.period_start).label("month"),
        "category": SpendRecord.category,
        "supplier_id": SpendRecord.supplier_id,
    }
    return [mapping[key] for key in grouped]


def _order_columns(grouped: list[str]) -> list[ColumnElement[Any]]:
    mapping: dict[str, ColumnElement[Any]] = {
        "month": func.date_trunc("month", OrderRecord.ordered_at).label("month"),
        "category": OrderRecord.category,
        "supplier_id": OrderRecord.supplier_id,
        "status": OrderRecord.status,
    }
    return [mapping[key] for key in grouped]


def _sourcing_columns(grouped: list[str]) -> list[ColumnElement[Any]]:
    mapping: dict[str, ColumnElement[Any]] = {
        "month": func.date_trunc("month", SourcingEvent.closed_at).label("month"),
        "category": SourcingEvent.category,
        "outcome": SourcingEvent.outcome,
    }
    return [mapping[key] for key in grouped]


class AnalyticsService:
    def __init__(self, db: AsyncSession, gateway: ModelGateway):
        self.db = db
        self.gateway = gateway

    async def parse_intent(self, question: str) -> dict[str, Any]:
        generation = await self.gateway.generate(
            f"INTENT_JSON {question}", json_schema={"type": "object"}
        )
        intent = generation.structured if isinstance(generation.structured, dict) else {}
        pattern = intent.get("pattern")
        if pattern not in {p.value for p in AnalyticsPattern}:
            raise ValueError("unsupported analytics pattern")
        filters = intent.get("filters")
        if not isinstance(filters, dict):
            filters = {}
        raw_group_by = intent.get("group_by")
        group_by = [str(g) for g in raw_group_by] if isinstance(raw_group_by, list) else []
        presentation = intent.get("presentation")
        if presentation not in {"table", "bar", "line"}:
            presentation = "table"
        return {
            "pattern": pattern,
            "filters": filters,
            "group_by": group_by,
            "presentation": presentation,
        }

    def _dates(self, filters: dict[str, Any]) -> tuple[date, date]:
        try:
            start = date.fromisoformat(str(filters["start_date"]))
            end = date.fromisoformat(str(filters["end_date"]))
        except (KeyError, ValueError) as exc:
            raise ValueError("start_date and end_date are required") from exc
        if end < start:
            raise ValueError("end_date precedes start_date")
        return start, end

    def _spend_scope(
        self, stmt, auth: AuthContext, start: date, end: date, currency: str, categories: list[str]
    ):
        latest = (
            select(func.max(SpendRecord.source_revision))
            .where(SpendRecord.workspace_id == auth.workspace_id)
            .scalar_subquery()
        )
        stmt = (
            stmt.where(SpendRecord.workspace_id == auth.workspace_id)
            .where(SpendRecord.period_start >= start)
            .where(SpendRecord.period_end <= end)
            .where(SpendRecord.currency == currency)
            .where(SpendRecord.source_revision == latest)
        )
        if categories:
            stmt = stmt.where(SpendRecord.category.in_(categories))
        return stmt

    def _order_scope(
        self, stmt, auth: AuthContext, start: date, end: date, currency: str, categories: list[str]
    ):
        latest = (
            select(func.max(OrderRecord.source_revision))
            .where(OrderRecord.workspace_id == auth.workspace_id)
            .scalar_subquery()
        )
        stmt = (
            stmt.where(OrderRecord.workspace_id == auth.workspace_id)
            .where(OrderRecord.ordered_at >= start)
            .where(OrderRecord.ordered_at <= end)
            .where(OrderRecord.currency == currency)
            .where(OrderRecord.source_revision == latest)
        )
        if categories:
            stmt = stmt.where(OrderRecord.category.in_(categories))
        return stmt

    def _sourcing_scope(
        self, stmt, auth: AuthContext, start: date, end: date, categories: list[str]
    ):
        start_at = datetime.combine(start, time.min, tzinfo=UTC)
        end_exclusive = datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC)
        stmt = (
            stmt.where(SourcingEvent.workspace_id == auth.workspace_id)
            .where(SourcingEvent.opened_at >= start_at)
            .where(SourcingEvent.closed_at < end_exclusive)
        )
        if categories:
            stmt = stmt.where(SourcingEvent.category.in_(categories))
        return stmt

    async def execute(
        self, auth: AuthContext, *, pattern: str, filters: dict[str, Any], group_by: list[str]
    ) -> dict[str, Any]:
        if pattern not in {item.value for item in AnalyticsPattern}:
            raise ValueError("unsupported analytics pattern")
        start, end = self._dates(filters)
        categories = filters.get("category_ids") or []
        if categories and not set(categories) <= ALLOWED_CATEGORIES:
            raise ValueError("category is not in the allowlist")
        grouped = _resolve_group_by(pattern, group_by)
        currency = _currency(filters)
        freshness_stmt = None
        if pattern == AnalyticsPattern.SPENDING_BY_PERIOD.value:
            columns = _spend_columns(grouped)
            stmt = self._spend_scope(
                select(*columns, func.sum(SpendRecord.amount).label("amount")),
                auth,
                start,
                end,
                currency,
                categories,
            ).group_by(*columns)
            freshness_stmt = self._spend_scope(
                select(func.max(SpendRecord.period_end)), auth, start, end, currency, categories
            )
        elif pattern == AnalyticsPattern.ORDER_COUNTS_BY_STATUS.value:
            columns = _order_columns(grouped)
            stmt = self._order_scope(
                select(*columns, func.count().label("count")),
                auth,
                start,
                end,
                currency,
                categories,
            ).group_by(*columns)
            freshness_stmt = self._order_scope(
                select(func.max(OrderRecord.ordered_at)), auth, start, end, currency, categories
            )
        elif pattern == AnalyticsPattern.SUPPLIER_CONCENTRATION.value:
            columns = _spend_columns(grouped)
            stmt = self._spend_scope(
                select(*columns, func.sum(SpendRecord.amount).label("amount")),
                auth,
                start,
                end,
                currency,
                categories,
            ).group_by(*columns)
            freshness_stmt = self._spend_scope(
                select(func.max(SpendRecord.period_end)), auth, start, end, currency, categories
            )
        elif pattern == AnalyticsPattern.PRICE_VARIATION.value:
            columns = _order_columns(grouped)
            stmt = self._order_scope(
                select(*columns, func.avg(OrderRecord.amount).label("avg_amount")),
                auth,
                start,
                end,
                currency,
                categories,
            ).group_by(*columns)
            freshness_stmt = self._order_scope(
                select(func.max(OrderRecord.ordered_at)), auth, start, end, currency, categories
            )
        elif pattern == AnalyticsPattern.ADDITIONAL_SERVICE_CHARGES.value:
            columns = _order_columns(grouped)
            stmt = self._order_scope(
                select(
                    *columns,
                    func.sum(OrderRecord.amount).label("base"),
                    func.sum(OrderRecord.additional_service_amount).label("additional"),
                ),
                auth,
                start,
                end,
                currency,
                categories,
            ).group_by(*columns)
            freshness_stmt = self._order_scope(
                select(func.max(OrderRecord.ordered_at)), auth, start, end, currency, categories
            )
        elif pattern == AnalyticsPattern.SOURCING_OUTCOMES.value:
            columns = _sourcing_columns(grouped)
            stmt = self._sourcing_scope(
                select(
                    *columns,
                    func.count().label("count"),
                    func.avg(SourcingEvent.participant_count).label("avg_participants"),
                ),
                auth,
                start,
                end,
                categories,
            ).group_by(*columns)
            freshness_stmt = self._sourcing_scope(
                select(func.max(SourcingEvent.closed_at)), auth, start, end, categories
            )
        else:
            raise ValueError("unsupported analytics pattern")
        rows = (await self.db.execute(stmt.limit(500))).mappings().all()
        freshness = _iso_date(await self.db.scalar(freshness_stmt))
        serialized = []
        for row in rows:
            item = {}
            for key, value in dict(row).items():
                if isinstance(value, Decimal):
                    item[key] = str(value)
                elif hasattr(value, "isoformat"):
                    item[key] = value.isoformat()
                else:
                    item[key] = value
            serialized.append(item)
        return {
            "pattern": pattern,
            "filters": {"start_date": start.isoformat(), "end_date": end.isoformat(), **filters},
            "group_by": grouped,
            "freshness": freshness,
            "row_count": len(serialized),
            "rows": serialized,
        }
