from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from backend.db import apply_rls, get_sessionmaker
from backend.domain.enums import Visibility
from backend.domain.models import PriceObservation, Principal, Product, Workspace
from tests.conftest import login


@pytest.mark.asyncio
async def test_hidden_reviewer_only_product_absent_from_search_and_list(client):
    catalog = await login(client, "catalog@marketdesk.test")
    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        principal = await db.scalar(
            select(Principal).where(Principal.email == "catalog@marketdesk.test")
        )
        await apply_rls(db, str(workspace.id), str(principal.id))
        secret = Product(
            workspace_id=workspace.id,
            sku=f"SECRET-PATH-{uuid.uuid4().hex[:8]}",
            title="Hidden reviewer path router",
            description="Hidden reviewer path router",
            category="network-gear",
            attributes={"model": "HID-PATH", "capacity": "1G"},
            list_price=Decimal("99"),
            visibility=Visibility.REVIEWER_ONLY.value,
        )
        db.add(secret)
        await db.flush()
        secret_id = secret.id
        await db.commit()
    listed = await client.get(
        "/v1/catalog/products?limit=50",
        headers={"Authorization": f"Bearer {catalog}"},
    )
    assert listed.status_code == 200
    listed_ids = {item["id"] for item in listed.json()["items"]}
    assert str(secret_id) not in listed_ids
    searched = await client.post(
        "/v1/products/search",
        json={"query": "Hidden reviewer path router", "limit": 20},
        headers={"Authorization": f"Bearer {catalog}"},
    )
    assert searched.status_code == 200, searched.text
    items = searched.json()["result"]["items"]
    assert all(item["id"] != str(secret_id) for item in items)
    assert all("Hidden reviewer path router" not in item.get("title", "") for item in items)


@pytest.mark.asyncio
async def test_search_ranks_unique_token_over_unordered_limit_decoys(client):
    catalog = await login(client, "catalog@marketdesk.test")
    token = f"ZXQUNIQUEALPHA{uuid.uuid4().hex[:8]}"
    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        principal = await db.scalar(
            select(Principal).where(Principal.email == "catalog@marketdesk.test")
        )
        await apply_rls(db, str(workspace.id), str(principal.id))
        db.add_all(
            [
                Product(
                    workspace_id=workspace.id,
                    sku=f"DEC-{uuid.uuid4().hex[:10]}-{i}",
                    title=f"AAA filler widget {i}",
                    description="generic filler listing",
                    category="network-gear",
                    attributes={"model": f"DEC-{i}"},
                    list_price=Decimal("10"),
                    completeness=Decimal("1"),
                )
                for i in range(210)
            ]
        )
        await db.flush()
        match = Product(
            workspace_id=workspace.id,
            sku=f"HIT-{uuid.uuid4().hex[:10]}",
            title=f"{token} ranked listing",
            description=f"only {token} should match this row",
            category="network-gear",
            attributes={"model": "HIT-TOKEN"},
            list_price=Decimal("11"),
            completeness=Decimal("0.1"),
        )
        db.add(match)
        await db.flush()
        match_id = str(match.id)
        await db.commit()
    searched = await client.post(
        "/v1/products/search",
        json={"query": token, "limit": 10},
        headers={"Authorization": f"Bearer {catalog}"},
    )
    assert searched.status_code == 200, searched.text
    items = searched.json()["result"]["items"]
    assert items, searched.text
    ids = [item["id"] for item in items]
    assert match_id in ids
    assert ids[0] == match_id
    assert items[0]["title"].startswith(token)


@pytest.mark.asyncio
async def test_references_range_excludes_eur_and_mismatched_unit(client):
    catalog = await login(client, "catalog@marketdesk.test")
    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        principal = await db.scalar(
            select(Principal).where(Principal.email == "catalog@marketdesk.test")
        )
        await apply_rls(db, str(workspace.id), str(principal.id))
        product = Product(
            workspace_id=workspace.id,
            sku=f"REF-{uuid.uuid4().hex[:10]}",
            title="Path references cohort router",
            description="Path references cohort router",
            category="network-gear",
            attributes={"model": "REF-COHORT"},
            list_price=Decimal("110"),
            currency="USD",
            unit="each",
        )
        db.add(product)
        await db.flush()
        product_id = product.id
        now = datetime.now(UTC)
        for i, amount in enumerate((Decimal("100"), Decimal("110"), Decimal("120"))):
            db.add(
                PriceObservation(
                    workspace_id=workspace.id,
                    product_id=product_id,
                    amount=amount,
                    unit="each",
                    currency="USD",
                    tax_included=True,
                    shipping_included=False,
                    condition="new",
                    source_name=f"usd-each-{i}",
                    observed_at=now - timedelta(hours=i),
                )
            )
        for i in range(4):
            db.add(
                PriceObservation(
                    workspace_id=workspace.id,
                    product_id=product_id,
                    amount=Decimal("99999"),
                    unit="each",
                    currency="EUR",
                    source_name=f"eur-{i}",
                    observed_at=now - timedelta(hours=i),
                )
            )
            db.add(
                PriceObservation(
                    workspace_id=workspace.id,
                    product_id=product_id,
                    amount=Decimal("99999"),
                    unit="box",
                    currency="USD",
                    source_name=f"box-{i}",
                    observed_at=now - timedelta(hours=i),
                )
            )
        db.add(
            PriceObservation(
                workspace_id=workspace.id,
                product_id=product_id,
                amount=Decimal("99999"),
                unit="each",
                currency="USD",
                tax_included=False,
                source_name="tax-ex",
                observed_at=now,
            )
        )
        db.add(
            PriceObservation(
                workspace_id=workspace.id,
                product_id=product_id,
                amount=Decimal("99999"),
                unit="each",
                currency="USD",
                shipping_included=True,
                source_name="ship-in",
                observed_at=now,
            )
        )
        db.add(
            PriceObservation(
                workspace_id=workspace.id,
                product_id=product_id,
                amount=Decimal("99999"),
                unit="each",
                currency="USD",
                condition="refurbished",
                source_name="refurb",
                observed_at=now,
            )
        )
        await db.commit()
    refs = await client.get(
        f"/v1/products/{product_id}/references",
        headers={"Authorization": f"Bearer {catalog}"},
    )
    assert refs.status_code == 200, refs.text
    body = refs.json()
    payload = body.get("result") or body
    assert payload.get("status") == "range", payload
    observations = payload.get("observations") or []
    assert observations
    for obs in observations:
        assert obs["currency"] == "USD"
        assert obs["unit"] == "each"
        assert obs["tax_included"] is True
        assert obs["shipping_included"] is False
        assert obs["condition"] == "new"
        assert Decimal(obs["amount"]) < Decimal("50000")
    assert Decimal(payload["median"]) < Decimal("50000")
    assert Decimal(payload["median"]) < Decimal("1000")


@pytest.mark.asyncio
async def test_compare_lists_hidden_product_in_missing_without_title(client):
    catalog = await login(client, "catalog@marketdesk.test")
    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        principal = await db.scalar(
            select(Principal).where(Principal.email == "catalog@marketdesk.test")
        )
        await apply_rls(db, str(workspace.id), str(principal.id))
        secret = Product(
            workspace_id=workspace.id,
            sku=f"SECRET-CMP-{uuid.uuid4().hex[:8]}",
            title="Hidden compare path router",
            description="Hidden compare path router",
            category="network-gear",
            attributes={"model": "HID-CMP", "secret_attr": "do-not-leak"},
            list_price=Decimal("99"),
            visibility=Visibility.REVIEWER_ONLY.value,
        )
        db.add(secret)
        await db.flush()
        secret_id = str(secret.id)
        await db.commit()
    listed = await client.get(
        "/v1/catalog/products?limit=10",
        headers={"Authorization": f"Bearer {catalog}"},
    )
    assert listed.status_code == 200
    visible_id = next(item["id"] for item in listed.json()["items"] if item["id"] != secret_id)
    compared = await client.post(
        "/v1/products/compare",
        json={"product_ids": [visible_id, secret_id]},
        headers={"Authorization": f"Bearer {catalog}"},
    )
    assert compared.status_code == 200, compared.text
    result = compared.json()["result"]
    assert secret_id in result["missing"]
    product_ids = {item["id"] for item in result["products"]}
    assert all("secret_attr" not in (item.get("attributes") or {}) for item in result["products"])
    assert secret_id not in product_ids
    assert visible_id in product_ids
    titles = " ".join(item.get("title") or "" for item in result["products"])
    assert "Hidden compare path router" not in titles
