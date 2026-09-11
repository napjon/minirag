from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.security import AuthContext
from backend.auth.visibility import can_read_product
from backend.domain.enums import MatchLabel, Role, Visibility
from backend.domain.models import PriceObservation, Product
from backend.model_gateway.base import ModelGateway

_DEFAULT_CONDITION = "new"


def _quantile(values: list[Decimal], q: float) -> Decimal:
    if not values:
        return Decimal("0")
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(q * (len(ordered) - 1))))
    return ordered[idx]


class CatalogService:
    def __init__(self, db: AsyncSession, gateway: ModelGateway):
        self.db = db
        self.gateway = gateway

    async def search(
        self,
        auth: AuthContext,
        *,
        query: str,
        category: str | None,
        min_price: Decimal | None,
        max_price: Decimal | None,
        location: str | None,
        available_only: bool,
        attributes: dict[str, Any],
        preferences: dict[str, Any],
        limit: int,
    ) -> list[dict[str, Any]]:
        filters = [Product.workspace_id == auth.workspace_id]
        if Role.ADMIN not in auth.roles and Role.REVIEWER not in auth.roles:
            filters.append(Product.visibility == Visibility.PUBLIC_WORKSPACE.value)
        if available_only:
            filters.append(Product.available.is_(True))
        if category:
            filters.append(Product.category == category)
        if location:
            filters.append(Product.location == location)
        if min_price is not None:
            filters.append(Product.list_price >= min_price)
        if max_price is not None:
            filters.append(Product.list_price <= max_price)
        for key, value in attributes.items():
            filters.append(Product.attributes[key].as_string() == str(value))

        query_text = (query or "").strip()
        if query_text:
            # Keep the candidate stage bounded. Both retrieval branches execute
            # in PostgreSQL, so product search does not load the full catalog or
            # calculate 250,000 vector scores in the API process.
            candidate_k = min(500, max(100, limit * 20))
            [q_vec] = await self.gateway.embed([query_text])
            tsq = func.plainto_tsquery("simple", query_text)
            ts_rank = func.coalesce(func.ts_rank_cd(Product.tsv, tsq), 0.0)
            first_term = query_text.split()[0]
            first_term = first_term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            first_term_pattern = f"%{first_term}%"
            lexical_stmt = (
                select(Product, ts_rank.label("ts_rank"))
                .where(*filters)
                .where(
                    or_(
                        Product.tsv.op("@@")(tsq),
                        Product.title.ilike(first_term_pattern, escape="\\"),
                        Product.description.ilike(first_term_pattern, escape="\\"),
                    )
                )
                .order_by(ts_rank.desc(), Product.completeness.desc(), Product.title)
                .limit(candidate_k)
            )
            lexical_rows = list((await self.db.execute(lexical_stmt)).all())
            distance = Product.embedding.cosine_distance(q_vec)
            vector_stmt = (
                select(Product, distance.label("distance"))
                .where(*filters, Product.embedding.is_not(None))
                .order_by(distance)
                .limit(candidate_k)
            )
            vector_rows = list((await self.db.execute(vector_stmt)).all())
            candidates_by_id: dict[UUID, tuple[Product, float]] = {
                product.id: (product, float(rank or 0.0)) for product, rank in lexical_rows
            }
            for product, _distance in vector_rows:
                candidates_by_id.setdefault(product.id, (product, 0.0))
            candidates = list(candidates_by_id.values())
        else:
            stmt = (
                select(Product)
                .where(*filters)
                .order_by(Product.completeness.desc(), Product.title)
                .limit(limit)
            )
            fetched = list((await self.db.scalars(stmt)).all())
            candidates = [(product, 0.0) for product in fetched]

        visible = [
            (product, rank)
            for product, rank in candidates
            if can_read_product(auth, visibility=product.visibility)
        ]
        if query_text:
            scored = []
            q_tokens = set(query_text.lower().split())
            for product, ts_rank in visible:
                p_tokens = set((product.title + " " + product.description).lower().split())
                lexical = len(q_tokens & p_tokens) / max(1, len(q_tokens))
                lexical = max(lexical, ts_rank)
                vec = list(product.embedding) if product.embedding is not None else []
                if vec:
                    semantic = sum(a * b for a, b in zip(q_vec, vec, strict=False))
                else:
                    semantic = 0.0
                relevance = 0.5 * lexical + 0.5 * max(0.0, float(semantic))
                pref = 0.0
                if preferences:
                    matches = sum(
                        1
                        for k, v in preferences.items()
                        if str(product.attributes.get(k, "")).lower() == str(v).lower()
                    )
                    pref = matches / max(1, len(preferences))
                completeness = float(product.completeness)
                if preferences:
                    score = 0.85 * relevance + 0.10 * pref + 0.05 * completeness
                else:
                    score = 0.95 * relevance + 0.05 * completeness
                reasons = []
                if category:
                    reasons.append(f"category={product.category}")
                if "capacity" in product.attributes:
                    reasons.append(f"capacity={product.attributes['capacity']}")
                scored.append((score, product, reasons, pref))
            scored.sort(key=lambda item: item[0], reverse=True)
            products_ranked = scored[:limit]
        else:
            products_ranked = [(1.0, product, [], 0.0) for product, _rank in visible[:limit]]
        return [
            {
                "id": product.id,
                "sku": product.sku,
                "title": product.title,
                "category": product.category,
                "list_price": str(product.list_price),
                "currency": product.currency,
                "unit": product.unit,
                "location": product.location,
                "attributes": product.attributes,
                "available": product.available,
                "score": round(float(score), 4),
                "reasons": reasons,
            }
            for score, product, reasons, _pref in products_ranked
        ]

    async def compare(self, auth: AuthContext, product_ids: list[UUID]) -> dict[str, Any]:
        products = list(
            (
                await self.db.scalars(
                    select(Product).where(
                        Product.workspace_id == auth.workspace_id,
                        Product.id.in_(product_ids),
                    )
                )
            ).all()
        )
        visible = [p for p in products if can_read_product(auth, visibility=p.visibility)]
        by_id = {p.id: p for p in visible}
        missing = [str(pid) for pid in product_ids if pid not in by_id]
        rows = []
        # Attribute names are part of the returned comparison schema. Build the
        # schema only from rows the caller is authorized to see so hidden
        # products cannot influence the response shape.
        keys = sorted({key for p in visible for key in p.attributes})
        for pid in product_ids:
            product = by_id.get(pid)
            if not product:
                continue
            rows.append(
                {
                    "id": product.id,
                    "sku": product.sku,
                    "title": product.title,
                    "list_price": str(product.list_price),
                    "currency": product.currency,
                    "unit": product.unit,
                    "location": product.location,
                    "attributes": {k: product.attributes.get(k, "unknown") for k in keys},
                }
            )
        return {"products": rows, "missing": missing}

    async def match(self, left: Product, right: Product) -> dict[str, Any]:
        reasons = []
        if left.sku == right.sku:
            return {
                "left_id": left.id,
                "right_id": right.id,
                "label": MatchLabel.SAME_PRODUCT.value,
                "score": 1.0,
                "reasons": ["identical sku"],
            }
        if left.attributes.get("model") and left.attributes.get("model") == right.attributes.get(
            "model"
        ):
            if left.attributes.get("pack_size") != right.attributes.get("pack_size"):
                return {
                    "left_id": left.id,
                    "right_id": right.id,
                    "label": MatchLabel.COMPARABLE_PRODUCT.value,
                    "score": 0.7,
                    "reasons": ["same model, different pack size"],
                }
            reasons.append("shared model")
            return {
                "left_id": left.id,
                "right_id": right.id,
                "label": MatchLabel.SAME_PRODUCT.value,
                "score": 0.9,
                "reasons": reasons,
            }
        if left.category != right.category:
            return {
                "left_id": left.id,
                "right_id": right.id,
                "label": MatchLabel.NOT_COMPARABLE.value,
                "score": 0.1,
                "reasons": ["different category"],
            }
        return {
            "left_id": left.id,
            "right_id": right.id,
            "label": MatchLabel.COMPARABLE_PRODUCT.value,
            "score": 0.5,
            "reasons": ["same category"],
        }

    async def references(self, auth: AuthContext, product_id: UUID) -> dict[str, Any]:
        product = await self.db.scalar(
            select(Product).where(
                Product.workspace_id == auth.workspace_id, Product.id == product_id
            )
        )
        if product is None or not can_read_product(auth, visibility=product.visibility):
            return {"status": "not_found"}
        cutoff = datetime.now(UTC) - timedelta(hours=72)
        observations = list(
            (
                await self.db.scalars(
                    select(PriceObservation).where(
                        PriceObservation.workspace_id == auth.workspace_id,
                        PriceObservation.product_id == product_id,
                        PriceObservation.comparable.is_(True),
                        PriceObservation.currency == product.currency,
                        PriceObservation.unit == product.unit,
                        PriceObservation.tax_included.is_(True),
                        PriceObservation.shipping_included.is_(False),
                        PriceObservation.condition == _DEFAULT_CONDITION,
                    )
                )
            ).all()
        )
        current = [o for o in observations if o.observed_at >= cutoff]
        historical = [o for o in observations if o.observed_at < cutoff]
        amounts = [o.amount / max(1, o.pack_size) for o in current]
        if len(amounts) < 3:
            return {
                "status": "insufficient_comparables",
                "product_id": product_id,
                "current_count": len(current),
                "historical": [
                    {
                        "amount": str(o.amount),
                        "observed_at": o.observed_at.isoformat(),
                        "source_name": o.source_name,
                    }
                    for o in historical
                ],
                "warning": (
                    "older observations cannot silently drive a current-price recommendation"
                ),
            }
        q1 = _quantile(amounts, 0.25)
        q3 = _quantile(amounts, 0.75)
        return {
            "status": "range",
            "product_id": product_id,
            "sample_count": len(amounts),
            "median": str(median(amounts)),
            "q1": str(q1),
            "q3": str(q3),
            "label": "observed comparison range",
            "observations": [
                {
                    "amount": str(o.amount),
                    "unit": o.unit,
                    "currency": o.currency,
                    "tax_included": o.tax_included,
                    "shipping_included": o.shipping_included,
                    "condition": o.condition,
                    "observed_at": o.observed_at.isoformat(),
                    "source_name": o.source_name,
                }
                for o in current
            ],
        }
