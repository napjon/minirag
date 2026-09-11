from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from backend.catalog.service import CatalogService
from backend.domain.enums import MatchLabel
from backend.domain.models import Product
from backend.seed import PRODUCTS


def _product(item: dict, *, sku: str | None = None, **overrides) -> Product:
    attributes = dict(item["attributes"])
    if "attributes" in overrides:
        attributes.update(overrides.pop("attributes"))
    return Product(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        sku=sku or item["sku"],
        title=overrides.pop("title", item["title"]),
        description=item["title"],
        category=overrides.pop("category", item["category"]),
        attributes=attributes,
        list_price=Decimal(overrides.pop("list_price", item["list_price"])),
        location=item["location"],
        **overrides,
    )


def _seed_item(sku: str) -> dict:
    return next(item for item in PRODUCTS if item["sku"] == sku)


@pytest.fixture
def catalog() -> CatalogService:
    return CatalogService(None, None)  # match() does not touch db or gateway


@pytest.mark.asyncio
async def test_identical_sku_is_same_product_even_when_pack_size_differs(catalog):
    single = _seed_item("NG-100")
    left = _product(single)
    right = _product(single, attributes={"pack_size": 2})
    result = await catalog.match(left, right)
    assert result["label"] == MatchLabel.SAME_PRODUCT.value
    assert result["score"] == 1.0
    assert result["reasons"] == ["identical sku"]


@pytest.mark.asyncio
async def test_same_model_different_pack_size_is_comparable(catalog):
    single = _seed_item("NG-100")
    two_pack = _seed_item("NG-100-2PK")
    left = _product(single)
    right = _product(two_pack)
    assert left.sku != right.sku
    assert left.attributes["model"] == right.attributes["model"]
    assert left.attributes["pack_size"] != right.attributes["pack_size"]
    result = await catalog.match(left, right)
    assert result["label"] == MatchLabel.COMPARABLE_PRODUCT.value
    assert result["score"] == 0.7
    assert result["reasons"] == ["same model, different pack size"]


@pytest.mark.asyncio
async def test_same_model_same_pack_size_different_sku_is_same_product(catalog):
    item = _seed_item("PW-40")
    left = _product(item)
    right = _product(item, sku="PW-40-ALT")
    result = await catalog.match(left, right)
    assert result["label"] == MatchLabel.SAME_PRODUCT.value
    assert result["score"] == 0.9
    assert result["reasons"] == ["shared model"]


@pytest.mark.asyncio
async def test_different_category_is_not_comparable(catalog):
    router = _product(_seed_item("NG-100"))
    rectifier = _product(_seed_item("PW-40"))
    result = await catalog.match(router, rectifier)
    assert result["label"] == MatchLabel.NOT_COMPARABLE.value
    assert result["score"] == 0.1
    assert result["reasons"] == ["different category"]


@pytest.mark.asyncio
async def test_same_category_without_shared_model_is_comparable(catalog):
    left = _product(_seed_item("NG-100"))
    right = _product(
        _seed_item("NG-100-2PK"),
        attributes={"model": "ER-40G", "pack_size": 2},
    )
    result = await catalog.match(left, right)
    assert result["label"] == MatchLabel.COMPARABLE_PRODUCT.value
    assert result["score"] == 0.5
    assert result["reasons"] == ["same category"]
