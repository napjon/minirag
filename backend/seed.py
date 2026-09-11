from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, update

from backend.config import get_settings
from backend.db import apply_rls, get_sessionmaker, init_db, reset_engine
from backend.domain.enums import AuthorityClass, DeploymentProfile, Role, SourceType, Visibility
from backend.domain.models import (
    Chunk,
    Membership,
    OrderRecord,
    PriceObservation,
    Principal,
    Product,
    Source,
    SourcingEvent,
    SpendRecord,
    Workspace,
)
from backend.ingestion.service import IngestionService
from backend.model_gateway.base import get_gateway

POLICIES = [
    {
        "topic": "account-access",
        "title": "Account and role access procedure",
        "language": "en",
        "body": (
            "# Account access\n"
            "Workspace access requires an authenticated identity and an active membership.\n\n"
            "# Role assignment\n"
            "Analysts may run operational queries. Reviewers may approve drafts. "
            "Catalog editors may run listing checks.\n\n"
            "# Emergency access\n"
            "Emergency elevation is recorded in the audit log and expires after eight hours.\n"
        ),
    },
    {
        "topic": "account-access",
        "title": "Prosedur akses akun dan peran",
        "language": "id",
        "body": """# Akses akun
Akses ruang kerja membutuhkan identitas terautentikasi dan keanggotaan aktif.

# Penugasan peran
Analis boleh menjalankan kueri operasional. Peninjau boleh menyetujui draf.
""",
    },
    {
        "topic": "listing-submission",
        "title": "Listing submission and correction",
        "language": "en",
        "body": """# Submission
A listing must include category, model, capacity, unit, and a current price.

# Corrections
Sellers may correct a listing within five business days. Corrections create a new revision.

# Rejection
Listings without a model identifier remain unpublished.
""",
    },
    {
        "topic": "ordering",
        "title": "Ordering and approval procedures",
        "language": "en",
        "body": """# Approval threshold
Orders above 25,000 require a second approver.

# Required fields
Each order records category, supplier, amount, and date.

# Amendments
Service amendments follow the cancellation procedure before a replacement order is opened.
""",
    },
    {
        "topic": "amendments",
        "title": "Service amendments and cancellations",
        "language": "en",
        "body": """# Cancellation window
Recurring services may be cancelled with ten days notice.

# Fees
Cancellation fees cannot exceed 15 percent of the unused period.

# Evidence
Keep the original service scope attached to the cancellation record.
""",
    },
]

RESTRICTED_POLICY = {
    "topic": "account-access",
    "title": "Restricted incident handling notes",
    "language": "en",
    "body": """# Restricted notes
These notes are visible only to the incident-response group.
""",
}

PRODUCTS = [
    {
        "sku": "NG-100",
        "title": "Edge router 10G",
        "category": "network-gear",
        "attributes": {"model": "ER-10G", "capacity": "10Gbps", "pack_size": 1},
        "list_price": "1200.00",
        "location": "ap-southeast",
    },
    {
        "sku": "NG-100-2PK",
        "title": "Edge router 10G two-pack",
        "category": "network-gear",
        "attributes": {"model": "ER-10G", "capacity": "10Gbps", "pack_size": 2},
        "list_price": "2300.00",
        "location": "ap-southeast",
    },
    {
        "sku": "PW-40",
        "title": "Site rectifier 48V",
        "category": "site-power",
        "attributes": {"model": "SR-48", "capacity": "40A", "pack_size": 1},
        "list_price": "890.00",
        "location": "ap-southeast",
    },
    {
        "sku": "FT-12",
        "title": "Fiber termination kit",
        "category": "field-tools",
        "attributes": {"model": "FTK-12", "capacity": "12-core", "pack_size": 1},
        "list_price": "145.00",
        "location": "eu-central",
    },
    {
        "sku": "MN-YEAR",
        "title": "Annual field maintenance",
        "category": "maintenance",
        "attributes": {"model": "MNT-1Y", "capacity": "1-site", "pack_size": 1},
        "list_price": "5400.00",
        "location": "global",
    },
    {
        "sku": "IN-STD",
        "title": "Standard rack installation",
        "category": "installation",
        "attributes": {"model": "INST-RACK", "capacity": "42U", "pack_size": 1},
        "list_price": "760.00",
        "location": "global",
    },
]


async def seed() -> None:
    settings = get_settings()
    await reset_engine()
    await init_db(settings)
    async with get_sessionmaker()() as db:
        existing = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        if existing:
            return
        workspace = Workspace(
            slug="harbor",
            name="Harbor workspace",
            deployment_profile=DeploymentProfile.HOSTED.value,
            config={"languages": ["en", "id"]},
        )
        db.add(workspace)
        await db.flush()
        users = [
            ("admin@marketdesk.test", "Workspace Admin", [Role.ADMIN.value], ["ops"]),
            (
                "analyst@marketdesk.test",
                "Operations Analyst",
                [Role.ANALYST.value, Role.VIEWER.value],
                ["ops"],
            ),
            (
                "reviewer@marketdesk.test",
                "Document Reviewer",
                [Role.REVIEWER.value, Role.VIEWER.value],
                ["ops"],
            ),
            (
                "drafter@marketdesk.test",
                "Specification Drafter",
                [Role.DRAFTER.value, Role.VIEWER.value],
                ["ops"],
            ),
            (
                "catalog@marketdesk.test",
                "Catalog Editor",
                [Role.CATALOG_EDITOR.value, Role.VIEWER.value],
                ["ops"],
            ),
            (
                "restricted@marketdesk.test",
                "Restricted Viewer",
                [Role.VIEWER.value],
                ["restricted"],
            ),
        ]
        principals: dict[str, Principal] = {}
        first_principal = None
        for email, name, roles, groups in users:
            principal = Principal(subject=email, display_name=name, email=email)
            db.add(principal)
            await db.flush()
            principals[email] = principal
            if first_principal is None:
                first_principal = principal
                await apply_rls(db, str(workspace.id), str(principal.id))
            db.add(
                Membership(
                    workspace_id=workspace.id,
                    principal_id=principal.id,
                    roles=roles,
                    group_ids=groups,
                )
            )
        policy_source = Source(
            workspace_id=workspace.id,
            source_type=SourceType.POLICY.value,
            authority_class=AuthorityClass.CURRENT_POLICY.value,
            owner_role=Role.ADMIN.value,
            name="Approved procedures",
        )
        db.add(policy_source)
        await db.flush()
        gateway = get_gateway(settings)
        ingestion = IngestionService(db, gateway)
        for item in POLICIES:
            await ingestion.ingest_text(
                workspace_id=workspace.id,
                source=policy_source,
                title=item["title"],
                body=item["body"],
                topic=item["topic"],
                language=item["language"],
                effective_from=date(2030, 1, 1),
                publish=True,
            )
        await ingestion.ingest_text(
            workspace_id=workspace.id,
            source=policy_source,
            title=RESTRICTED_POLICY["title"],
            body=RESTRICTED_POLICY["body"],
            topic=RESTRICTED_POLICY["topic"],
            language="en",
            visibility=Visibility.RESTRICTED.value,
            allowed_groups=["incident-response"],
            effective_from=date(2030, 1, 1),
            publish=True,
        )
        await db.execute(update(Chunk).values(tsv=func.to_tsvector("simple", Chunk.text)))
        products = []
        for item in PRODUCTS:
            product = Product(
                workspace_id=workspace.id,
                sku=item["sku"],
                title=item["title"],
                description=item["title"],
                category=item["category"],
                attributes=item["attributes"],
                list_price=Decimal(item["list_price"]),
                location=item["location"],
            )
            [embedding] = await gateway.embed([item["title"] + " " + str(item["attributes"])])
            product.embedding = embedding
            db.add(product)
            await db.flush()
            products.append(product)
            now = datetime.now(UTC)
            for i in range(4):
                db.add(
                    PriceObservation(
                        workspace_id=workspace.id,
                        product_id=product.id,
                        amount=Decimal(item["list_price"]) + Decimal(i * 10),
                        unit="each",
                        currency="USD",
                        source_name=f"licensed-feed-{i}",
                        observed_at=now - timedelta(hours=i * 6),
                    )
                )
        await db.execute(
            update(Product).values(
                tsv=func.to_tsvector("simple", Product.title + " " + Product.description)
            )
        )
        for month in range(1, 7):
            for category, amount in [
                ("network-gear", 12000 + month * 250),
                ("site-power", 8000 + month * 100),
                ("maintenance", 5400),
            ]:
                db.add(
                    SpendRecord(
                        workspace_id=workspace.id,
                        period_start=date(2030, month, 1),
                        period_end=date(2030, month, 28),
                        category=category,
                        supplier_id="supplier-a" if month % 2 else "supplier-b",
                        amount=Decimal(amount),
                    )
                )
                db.add(
                    OrderRecord(
                        workspace_id=workspace.id,
                        status="approved" if month < 6 else "pending",
                        category=category,
                        supplier_id="supplier-a" if month % 2 else "supplier-b",
                        amount=Decimal(amount),
                        additional_service_amount=Decimal("120"),
                        ordered_at=date(2030, month, 10),
                    )
                )
        db.add(
            SourcingEvent(
                workspace_id=workspace.id,
                category="network-gear",
                title="Edge router replenishment",
                participant_count=2,
                participant_ids=["supplier-a", "supplier-b"],
                winner_id="supplier-a",
                offer_amounts=["1100", "1180"],
                submission_times=["2030-03-01T10:00:00Z", "2030-03-01T10:00:00Z"],
                opened_at=datetime(2030, 2, 1, tzinfo=UTC),
                closed_at=datetime(2030, 3, 1, tzinfo=UTC),
            )
        )
        db.add(
            SourcingEvent(
                workspace_id=workspace.id,
                category="network-gear",
                title="Core switch replacement",
                participant_count=5,
                participant_ids=["supplier-a", "supplier-c", "supplier-d"],
                winner_id="supplier-a",
                offer_amounts=["4000", "4100", "4050"],
                submission_times=["2030-04-01T09:00:00Z", "2030-04-01T12:00:00Z"],
                opened_at=datetime(2030, 3, 1, tzinfo=UTC),
                closed_at=datetime(2030, 4, 1, tzinfo=UTC),
            )
        )
        await db.commit()


def run() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    run()
