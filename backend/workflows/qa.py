from __future__ import annotations

import json
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.security import AuthContext
from backend.config import Settings
from backend.domain.enums import AnswerStatus, Language
from backend.domain.models import Interaction
from backend.domain.schemas import EvidenceRef, QuestionResult
from backend.model_gateway.base import ModelGateway
from backend.retrieval.evidence import answer_is_supported, claim_is_supported
from backend.retrieval.service import RetrievalService

OUT_OF_SCOPE_HINTS = ("lottery", "medical diagnosis", "write malware")


def _persist_interaction(
    *,
    db: AsyncSession,
    auth: AuthContext,
    request_id: str,
    capability: str,
    status: str,
    question: str,
    as_of: date | None,
    result: QuestionResult,
    evidence: list[EvidenceRef],
    manifest: dict,
    cost_usd: float = 0.0,
) -> None:
    db.add(
        Interaction(
            workspace_id=auth.workspace_id,
            principal_id=auth.principal_id,
            request_id=request_id,
            capability=capability,
            status=status,
            request={"question": question, "as_of": as_of.isoformat() if as_of else None},
            response=json.loads(result.model_dump_json()),
            evidence=[json.loads(item.model_dump_json()) for item in evidence],
            execution_manifest=manifest,
            cost_usd=cost_usd,
            final_state="completed",
        )
    )


async def answer_question(
    *,
    db: AsyncSession,
    auth: AuthContext,
    gateway: ModelGateway,
    settings: Settings,
    request_id: str,
    question: str,
    language: Language | None,
    as_of: date | None,
) -> tuple[QuestionResult, list[EvidenceRef], dict]:
    if any(hint in question.lower() for hint in OUT_OF_SCOPE_HINTS):
        result = QuestionResult(
            status=AnswerStatus.OUT_OF_SCOPE,
            answer=None,
            language=language or Language.EN,
            limitations="This question is outside the configured topic boundary.",
        )
        manifest = {"reason": "out_of_scope"}
        _persist_interaction(
            db=db,
            auth=auth,
            request_id=request_id,
            capability="questions",
            status=result.status.value,
            question=question,
            as_of=as_of,
            result=result,
            evidence=[],
            manifest=manifest,
            cost_usd=float(manifest.get("cost_usd") or 0),
        )
        await db.flush()
        return result, [], manifest
    retrieval = RetrievalService(db, gateway)
    evidence_rows = await retrieval.search(
        auth,
        question,
        as_of=as_of,
        lexical_k=settings.lexical_k,
        vector_k=settings.vector_k,
        rerank_k=settings.rerank_k,
        evidence_k=settings.evidence_k,
    )
    evidence_rows = [row for row in evidence_rows if float(row.get("score") or 0) >= 0.2]
    evidence = [
        EvidenceRef(
            document_id=row["document_id"],
            document_version_id=row["document_version_id"],
            chunk_id=row["chunk_id"],
            section_path=row["section_path"],
            page_or_table_location=row["page_or_table_location"],
            supporting_span=row["supporting_span"],
            source_effective_date=row["source_effective_date"],
            authorized_viewer_url=row["authorized_viewer_url"],
        )
        for row in evidence_rows
    ]
    if not evidence_rows:
        result = QuestionResult(
            status=AnswerStatus.INSUFFICIENT_EVIDENCE,
            answer=None,
            language=language or Language.EN,
            limitations="No authorized published sources support this question.",
        )
        manifest = {"reason": "no_evidence"}
        _persist_interaction(
            db=db,
            auth=auth,
            request_id=request_id,
            capability="questions",
            status=result.status.value,
            question=question,
            as_of=as_of,
            result=result,
            evidence=[],
            manifest=manifest,
            cost_usd=float(manifest.get("cost_usd") or 0),
        )
        await db.flush()
        return result, [], manifest
    evidence_block = "\n".join(
        f"- {row['chunk_id']} span={' '.join(row['supporting_span'].split())}"
        for row in evidence_rows
    )
    prompt = (
        "QA_JSON Answer only from EVIDENCE. Return JSON with status, answer, claims"
        " (text, evidence_id), limitations.\n"
        f"QUESTION: {question}\nEVIDENCE:\n{evidence_block}"
    )
    generation = await gateway.generate(prompt, json_schema={"type": "object"})
    raw_payload = generation.structured
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    allowed_ids = {str(row["chunk_id"]) for row in evidence_rows}
    by_id = {str(row["chunk_id"]): row for row in evidence_rows}
    claims = []
    raw_claims = payload.get("claims")
    for claim in raw_claims if isinstance(raw_claims, list) else []:
        if not isinstance(claim, dict):
            continue
        eid = str(claim.get("evidence_id", ""))
        if eid not in allowed_ids:
            continue
        span = by_id[eid].get("supporting_span") or by_id[eid].get("text") or ""
        claim_text = claim.get("text")
        if not isinstance(claim_text, str) or not claim_text.strip():
            continue
        if not claim_is_supported(claim_text, span):
            continue
        claims.append({"text": claim_text, "evidence_id": eid})
    status_raw = payload.get("status") or ("answered" if claims else "insufficient_evidence")
    try:
        status = AnswerStatus(status_raw)
    except (TypeError, ValueError):
        status = AnswerStatus.INSUFFICIENT_EVIDENCE if not claims else AnswerStatus.ANSWERED
    candidate_answer = payload.get("answer")
    answer_text = candidate_answer if isinstance(candidate_answer, str) and claims else None
    limitations = payload.get("limitations")
    if not isinstance(limitations, str):
        limitations = None
    if status == AnswerStatus.ANSWERED and (not claims or not answer_text):
        status = AnswerStatus.INSUFFICIENT_EVIDENCE
        answer_text = None
    if answer_text and not answer_is_supported(
        answer_text,
        claims,
        {evidence_id: str(row.get("supporting_span") or "") for evidence_id, row in by_id.items()},
    ):
        status = AnswerStatus.INSUFFICIENT_EVIDENCE
        answer_text = None
    result = QuestionResult(
        status=status,
        answer=answer_text,
        language=language or Language.EN,
        limitations=limitations,
        claims=claims,
    )
    manifest = {
        "model_provider": gateway.provider,
        "generation_model": generation.model,
        "embedding_revision": "fixture-1",
        "parser_version": "plaintext-1",
        "prompt_revision": "qa-v1",
        "token_input": generation.input_tokens,
        "token_output": generation.output_tokens,
        "cost_usd": generation.cost_usd,
        "retrieval": {"evidence_count": len(evidence)},
    }
    _persist_interaction(
        db=db,
        auth=auth,
        request_id=request_id,
        capability="questions",
        status=result.status.value,
        question=question,
        as_of=as_of,
        result=result,
        evidence=evidence,
        manifest=manifest,
        cost_usd=generation.cost_usd,
    )
    await db.flush()
    return result, evidence, manifest
