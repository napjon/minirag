from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from io import BytesIO

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.enums import LifecycleStatus, Visibility
from backend.domain.models import Chunk, Document, DocumentVersion, OutboxEvent, Source
from backend.integrations.object_store import ObjectStore, get_object_store
from backend.model_gateway.base import ModelGateway

TOKEN_RE = re.compile(r"\S+")


def token_count(text: str) -> int:
    return len(TOKEN_RE.findall(text))


def _windows(para: str, limit: int = 700) -> list[str]:
    words = TOKEN_RE.findall(para)
    if len(words) <= limit:
        return [para]
    parts: list[str] = []
    start = 0
    while start < len(words):
        end = min(len(words), start + limit)
        parts.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        nxt = end - 40
        start = end if nxt <= start else nxt
    return parts


def chunk_text(text: str, heading: str = "") -> list[tuple[str, str]]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[tuple[str, str]] = []
    buf: list[str] = []
    buf_tokens = 0
    current_heading = heading
    for para in paragraphs:
        if para.startswith("#"):
            if buf:
                chunks.append((current_heading, "\n\n".join(buf)))
                buf, buf_tokens = [], 0
            current_heading = para.lstrip("# ").strip()
            continue
        for piece in _windows(para):
            n = token_count(piece)
            if buf_tokens + n > 700 and buf:
                chunks.append((current_heading, "\n\n".join(buf)))
                overlap = buf[-1] if buf and token_count(buf[-1]) <= 80 else ""
                buf = [overlap] if overlap else []
                buf_tokens = token_count(overlap)
            buf.append(piece)
            buf_tokens += n
            if buf_tokens >= 900:
                chunks.append((current_heading, "\n\n".join(buf)))
                buf, buf_tokens = [], 0
    if buf:
        chunks.append((current_heading, "\n\n".join(buf)))
    return chunks or [(heading, text.strip() or "empty")]


def _looks_like_pdf(filename: str, body: bytes) -> bool:
    name = (filename or "").lower()
    return name.endswith(".pdf") or body.startswith(b"%PDF")


def _extract_pdf_text(body: bytes) -> tuple[str, int]:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(body))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages), max(1, len(reader.pages))


class IngestionService:
    def __init__(
        self,
        db: AsyncSession,
        gateway: ModelGateway,
        object_store: ObjectStore | None = None,
    ):
        self.db = db
        self.gateway = gateway
        self.object_store = object_store or get_object_store()

    async def ingest_text(
        self,
        *,
        workspace_id: uuid.UUID,
        source: Source,
        title: str,
        body: str,
        topic: str,
        language: str,
        visibility: str = Visibility.PUBLIC_WORKSPACE.value,
        allowed_groups: list[str] | None = None,
        effective_from: date | None = None,
        publish: bool = True,
        parser_version: str = "plaintext-1",
        mime_type: str = "text/plain",
        original_bytes: bytes | None = None,
        page_count: int | None = None,
    ) -> Document:
        if source.workspace_id != workspace_id:
            raise ValueError("source does not belong to workspace")
        if not source.is_active:
            raise ValueError("source is inactive")
        if not body.strip():
            raise ValueError("document has no extractable text")
        document = Document(
            workspace_id=workspace_id,
            source_id=source.id,
            title=title,
            visibility=visibility,
            classification="internal",
            lifecycle_status=LifecycleStatus.RECEIVED.value,
            language=language,
            topic=topic,
            allowed_groups=allowed_groups or [],
        )
        self.db.add(document)
        await self.db.flush()
        payload = original_bytes if original_bytes is not None else body.encode()
        content_hash = hashlib.sha256(payload).hexdigest()
        object_key = f"documents/{document.id}/{content_hash}"
        if original_bytes is None:
            object_key = f"{object_key}.txt"
        await self.object_store.aput_bytes(object_key, payload, content_type=mime_type)
        version = DocumentVersion(
            workspace_id=workspace_id,
            document_id=document.id,
            revision=1,
            content_hash=content_hash,
            object_key=object_key,
            mime_type=mime_type,
            parser_version=parser_version,
            approval_state="approved" if publish else "awaiting_approval",
            effective_from=effective_from,
            extracted_text=body,
            page_count=page_count if page_count is not None else max(1, body.count("\f") + 1),
        )
        self.db.add(version)
        await self.db.flush()
        parts = chunk_text(body, heading=title)
        embeddings = await self.gateway.embed([text for _, text in parts])
        for i, ((heading, text), embedding) in enumerate(zip(parts, embeddings, strict=True)):
            digest = hashlib.sha256(text.encode()).hexdigest()
            self.db.add(
                Chunk(
                    workspace_id=workspace_id,
                    document_id=document.id,
                    version_id=version.id,
                    ordinal=i,
                    heading_path=heading,
                    text=text,
                    language=language,
                    token_count=token_count(text),
                    content_hash=digest,
                    embedding=embedding,
                    tsv=None,
                )
            )
        document.current_version_id = version.id
        document.lifecycle_status = (
            LifecycleStatus.PUBLISHED.value if publish else LifecycleStatus.AWAITING_APPROVAL.value
        )
        self.db.add(
            OutboxEvent(
                workspace_id=workspace_id,
                event_type="document_indexed",
                payload={"document_id": str(document.id), "version_id": str(version.id)},
                published=True,
                published_at=datetime.now(UTC),
            )
        )
        await self.db.flush()
        await self.db.execute(
            update(Chunk)
            .where(Chunk.version_id == version.id)
            .values(tsv=func.to_tsvector("simple", Chunk.text))
        )
        return document

    async def ingest_bytes(
        self,
        *,
        workspace_id: uuid.UUID,
        source: Source,
        title: str,
        body: bytes,
        filename: str,
        topic: str,
        language: str,
        visibility: str = Visibility.PUBLIC_WORKSPACE.value,
        publish: bool = True,
        effective_from: date | None = None,
    ) -> Document:
        if _looks_like_pdf(filename, body):
            text, page_count = _extract_pdf_text(body)
            parser_version = "pypdf-1"
            mime_type = "application/pdf"
        else:
            text = body.decode("utf-8", errors="replace")
            page_count = max(1, text.count("\f") + 1)
            parser_version = "plaintext-1"
            mime_type = "text/plain"
        if not text.strip():
            raise ValueError("document has no extractable text")
        return await self.ingest_text(
            workspace_id=workspace_id,
            source=source,
            title=title,
            body=text,
            topic=topic,
            language=language,
            visibility=visibility,
            effective_from=effective_from,
            publish=publish,
            parser_version=parser_version,
            mime_type=mime_type,
            original_bytes=body,
            page_count=page_count,
        )

    async def supersede(
        self,
        document: Document,
        *,
        body: str,
        language: str,
        effective_from: date,
        publish: bool = True,
    ) -> Document:
        old = await self.db.get(DocumentVersion, document.current_version_id)
        next_revision = 1
        if old is not None:
            old.effective_to = effective_from - timedelta(days=1)
            next_revision = old.revision + 1
        content_hash = hashlib.sha256(body.encode()).hexdigest()
        object_key = f"documents/{document.id}/{content_hash}.txt"
        await self.object_store.aput_bytes(object_key, body.encode(), content_type="text/plain")
        version = DocumentVersion(
            workspace_id=document.workspace_id,
            document_id=document.id,
            revision=next_revision,
            content_hash=content_hash,
            object_key=object_key,
            mime_type="text/plain",
            parser_version="plaintext-1",
            approval_state="approved" if publish else "awaiting_approval",
            effective_from=effective_from,
            extracted_text=body,
            page_count=max(1, body.count("\f") + 1),
        )
        self.db.add(version)
        await self.db.flush()
        parts = chunk_text(body, heading=document.title)
        embeddings = await self.gateway.embed([text for _, text in parts])
        for i, ((heading, text), embedding) in enumerate(zip(parts, embeddings, strict=True)):
            digest = hashlib.sha256(text.encode()).hexdigest()
            self.db.add(
                Chunk(
                    workspace_id=document.workspace_id,
                    document_id=document.id,
                    version_id=version.id,
                    ordinal=i,
                    heading_path=heading,
                    text=text,
                    language=language,
                    token_count=token_count(text),
                    content_hash=digest,
                    embedding=embedding,
                    tsv=None,
                )
            )
        document.current_version_id = version.id
        document.lifecycle_status = (
            LifecycleStatus.PUBLISHED.value if publish else LifecycleStatus.AWAITING_APPROVAL.value
        )
        self.db.add(
            OutboxEvent(
                workspace_id=document.workspace_id,
                event_type="document_indexed",
                payload={"document_id": str(document.id), "version_id": str(version.id)},
                published=True,
                published_at=datetime.now(UTC),
            )
        )
        await self.db.flush()
        await self.db.execute(
            update(Chunk)
            .where(Chunk.version_id == version.id)
            .values(tsv=func.to_tsvector("simple", Chunk.text))
        )
        return document

    async def withdraw(self, document: Document) -> None:
        if document.lifecycle_status == LifecycleStatus.WITHDRAWN.value:
            return
        document.lifecycle_status = LifecycleStatus.WITHDRAWN.value
        self.db.add(
            OutboxEvent(
                workspace_id=document.workspace_id,
                event_type="document_withdrawn",
                payload={"document_id": str(document.id)},
                published=True,
                published_at=datetime.now(UTC),
            )
        )
        await self.db.flush()

    async def approve(self, document: Document) -> DocumentVersion:
        if document.lifecycle_status != LifecycleStatus.AWAITING_APPROVAL.value:
            raise ValueError("document is not awaiting approval")
        version = await self.db.get(DocumentVersion, document.current_version_id)
        if version is None or version.document_id != document.id:
            raise ValueError("current document version not found")
        version.approval_state = "approved"
        document.lifecycle_status = LifecycleStatus.APPROVED.value
        await self.db.flush()
        return version

    async def publish(self, document: Document) -> DocumentVersion:
        if document.lifecycle_status != LifecycleStatus.APPROVED.value:
            raise ValueError("document must be approved before publication")
        version = await self.db.get(DocumentVersion, document.current_version_id)
        if (
            version is None
            or version.document_id != document.id
            or version.approval_state != "approved"
        ):
            raise ValueError("approved current document version not found")
        document.lifecycle_status = LifecycleStatus.PUBLISHED.value
        self.db.add(
            OutboxEvent(
                workspace_id=document.workspace_id,
                event_type="document_published",
                payload={"document_id": str(document.id), "version_id": str(version.id)},
                published=True,
                published_at=datetime.now(UTC),
            )
        )
        await self.db.flush()
        return version

    async def reindex(self, document: Document) -> int:
        if document.lifecycle_status == LifecycleStatus.WITHDRAWN.value:
            raise ValueError("withdrawn documents cannot be reindexed")
        version = await self.db.get(DocumentVersion, document.current_version_id)
        if version is None or version.document_id != document.id:
            raise ValueError("current document version not found")
        chunks = list(
            await self.db.scalars(
                select(Chunk)
                .where(Chunk.workspace_id == document.workspace_id, Chunk.version_id == version.id)
                .order_by(Chunk.ordinal)
            )
        )
        embeddings = await self.gateway.embed([chunk.text for chunk in chunks])
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            chunk.embedding = embedding
            chunk.index_generation += 1
        await self.db.execute(
            update(Chunk)
            .where(Chunk.workspace_id == document.workspace_id, Chunk.version_id == version.id)
            .values(tsv=func.to_tsvector("simple", Chunk.text))
        )
        self.db.add(
            OutboxEvent(
                workspace_id=document.workspace_id,
                event_type="document_reindexed",
                payload={"document_id": str(document.id), "version_id": str(version.id)},
                published=True,
                published_at=datetime.now(UTC),
            )
        )
        await self.db.flush()
        return len(chunks)
