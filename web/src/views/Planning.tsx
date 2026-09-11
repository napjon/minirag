import { FormEvent, useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  cachedDraftForLoadFailure,
  clearCachedDraft,
  readCachedDraft,
  readSession,
  writeCachedDraft,
} from "../api";
import type { Copy } from "../i18n";
import { dynamicLabel } from "../i18n";
import {
  TEMPLATE_KINDS,
  type DraftListItem,
  type Envelope,
  type Finding,
  type Role,
  type SourcingEvent,
} from "../types";
import { Field, FindingsTable, JsonBlock, PanelState, StatusBadge, WarningList } from "../ui";
import type { Capability } from "../capabilities";

type DraftPanelState = {
  id: string;
  title: string;
  state: string;
  revision_hash: string | null;
  unresolved_assumptions: string[];
  content: Record<string, unknown> | null;
};

const CACHE_ROLES: Role[] = ["drafter", "reviewer", "admin"];

export function Planning({
  t,
  lang,
  roles,
  capabilities,
  lastTarget,
  onTarget,
}: {
  t: Copy;
  lang: "en" | "id";
  roles: Role[];
  capabilities: Set<Capability>;
  lastTarget: { type: string; id: string } | null;
  onTarget: (type: string, id: string) => void;
}) {
  return (
    <div className="stack">
      {[...capabilities].some((capability) => capability.startsWith("drafts.")) ? (
        <DraftPanel t={t} lang={lang} roles={roles} capabilities={capabilities} onTarget={onTarget} />
      ) : null}
      {capabilities.has("sourcing") ? <SourcingPanel t={t} lang={lang} onTarget={onTarget} /> : null}
      {capabilities.has("feedback") ? <FeedbackPanel t={t} lang={lang} lastTarget={lastTarget} /> : null}
    </div>
  );
}

function canUseDraftCache(roles: Role[]) {
  return roles.some((role) => CACHE_ROLES.includes(role));
}

function DraftPanel({
  t,
  lang,
  roles,
  capabilities,
  onTarget,
}: {
  t: Copy;
  lang: "en" | "id";
  roles: Role[];
  capabilities: Set<Capability>;
  onTarget: (type: string, id: string) => void;
}) {
  const cached = readCachedDraft();
  const [template, setTemplate] = useState<(typeof TEMPLATE_KINDS)[number]>("equipment_requirements");
  const [title, setTitle] = useState("Router refresh");
  const [purpose, setPurpose] = useState("Replace edge routers");
  const [quantities, setQuantities] = useState("12");
  const [delivery, setDelivery] = useState("90 days");
  const [acceptance, setAcceptance] = useState("burn-in test");
  const [idempotency, setIdempotency] = useState<string>(() => crypto.randomUUID());
  const [draftId, setDraftId] = useState(cached?.id ?? "");
  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState<unknown>(null);
  const [loadLoading, setLoadLoading] = useState(false);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [draft, setDraft] = useState<DraftPanelState | null>(null);
  const [usedCache, setUsedCache] = useState(false);
  const [decision, setDecision] = useState<"approved" | "rejected">("approved");
  const [reason, setReason] = useState("");
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewError, setReviewError] = useState<unknown>(null);
  const [reviewResult, setReviewResult] = useState<Envelope<{ draft_id: string; state: string }> | null>(null);
  const [exportLoading, setExportLoading] = useState(false);
  const [exportError, setExportError] = useState<unknown>(null);
  const [exportResult, setExportResult] = useState<Envelope<Record<string, unknown>> | null>(null);
  const [queue, setQueue] = useState<DraftListItem[]>([]);
  const canCreate = capabilities.has("drafts.create");
  const canInspect = capabilities.has("drafts.read");
  const canReview = capabilities.has("drafts.review");
  const canExport = capabilities.has("drafts.export");
  const active = useRef(true);

  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);

  useEffect(() => {
    if (!canInspect) return;
    const state = roles.includes("reviewer") && !roles.includes("admin") ? "awaiting_review" : undefined;
    void api.listDrafts(state).then((body) => {
      if (active.current) setQueue(body.items ?? []);
    });
  }, [canInspect, roles]);

  function remember(next: DraftPanelState) {
    if (!active.current || !readSession()) return;
    writeCachedDraft({
      id: next.id,
      title: next.title,
      state: next.state,
      revision_hash: next.revision_hash,
    });
    setDraft(next);
    setDraftId(next.id);
    onTarget("draft", next.id);
  }

  async function createDraft(event: FormEvent) {
    event.preventDefault();
    setCreateLoading(true);
    setCreateError(null);
    setReviewResult(null);
    setExportResult(null);
    try {
      const created = await api.createDraft({
        template_kind: template,
        title,
        brief: {
          purpose,
          quantities,
          delivery_constraints: delivery,
          acceptance,
        },
        idempotency_key: idempotency,
      });
      let id = created.result?.result?.draft_id;
      if (!id && created.result?.job_id) {
        const job = await api.getJob(created.result.job_id);
        id = job.result?.draft_id;
      }
      if (!id) throw new Error("Draft job did not return a draft id");
      const loaded = await api.getDraft(id);
      if (!active.current) return;
      remember({
        id: loaded.id,
        title: loaded.title,
        state: loaded.state,
        revision_hash: loaded.revision_hash,
        unresolved_assumptions: loaded.unresolved_assumptions ?? [],
        content: loaded.content,
      });
      setUsedCache(false);
      setLoadError(null);
      const listed = await api.listDrafts(
        roles.includes("reviewer") && !roles.includes("admin") ? "awaiting_review" : undefined,
      );
      if (active.current) setQueue(listed.items ?? []);
    } catch (err) {
      setCreateError(err);
    } finally {
      setCreateLoading(false);
    }
  }

  async function fetchDraft(id: string) {
    if (!id) return;
    setLoadLoading(true);
    setLoadError(null);
    try {
      const loaded = await api.getDraft(id);
      if (!active.current) return;
      remember({
        id: loaded.id,
        title: loaded.title,
        state: loaded.state,
        revision_hash: loaded.revision_hash,
        unresolved_assumptions: loaded.unresolved_assumptions ?? [],
        content: loaded.content,
      });
      setUsedCache(false);
    } catch (err) {
      if (!active.current) return;
      setLoadError(err);
      const status = err instanceof ApiError ? err.status : 0;
      if (status === 403 || status === 404) clearCachedDraft();
      const fallback = cachedDraftForLoadFailure(status, readCachedDraft(), id);
      if (canUseDraftCache(roles) && fallback) {
        setDraft({
          id: fallback.id,
          title: fallback.title,
          state: fallback.state,
          revision_hash: fallback.revision_hash,
          unresolved_assumptions: [],
          content: null,
        });
        setUsedCache(true);
      } else {
        setDraft(null);
        setUsedCache(false);
      }
    } finally {
      if (active.current) setLoadLoading(false);
    }
  }

  async function loadDraft(event: FormEvent) {
    event.preventDefault();
    await fetchDraft(draftId);
  }

  async function submitReview(event: FormEvent) {
    event.preventDefault();
    if (!draft?.id || !draft.revision_hash) return;
    setReviewLoading(true);
    setReviewError(null);
    try {
      const result = await api.reviewDraft(draft.id, {
        decision,
        reason,
        revision_hash: draft.revision_hash,
      });
      setReviewResult(result);
      remember({ ...draft, state: result.result?.state ?? draft.state });
      const listed = await api.listDrafts(
        roles.includes("reviewer") && !roles.includes("admin") ? "awaiting_review" : undefined,
      );
      if (active.current) setQueue(listed.items ?? []);
    } catch (err) {
      setReviewResult(null);
      setReviewError(err);
    } finally {
      setReviewLoading(false);
    }
  }

  async function submitExport() {
    if (!draft?.id) return;
    setExportLoading(true);
    setExportError(null);
    try {
      setExportResult(await api.exportDraft(draft.id));
    } catch (err) {
      setExportResult(null);
      setExportError(err);
    } finally {
      setExportLoading(false);
    }
  }

  return (
    <section className="card">
      <h2>{t.drafts}</h2>
      {canCreate ? <form className="form" onSubmit={createDraft}>
        <div className="row wrap">
          <Field label={t.template}>
            <select value={template} onChange={(event) => setTemplate(event.target.value as typeof template)}>
              {TEMPLATE_KINDS.map((item) => (
                <option key={item} value={item}>
                  {dynamicLabel(lang, item)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t.title}>
            <input value={title} onChange={(event) => setTitle(event.target.value)} required />
          </Field>
        </div>
        <div className="row wrap">
          <Field label={t.purpose}>
            <input value={purpose} onChange={(event) => setPurpose(event.target.value)} />
          </Field>
          <Field label={t.quantities}>
            <input value={quantities} onChange={(event) => setQuantities(event.target.value)} />
          </Field>
          <Field label={t.delivery}>
            <input value={delivery} onChange={(event) => setDelivery(event.target.value)} />
          </Field>
          <Field label={t.acceptance}>
            <input value={acceptance} onChange={(event) => setAcceptance(event.target.value)} />
          </Field>
        </div>
        <div className="row wrap">
          <Field label={t.idempotency}>
            <input value={idempotency} onChange={(event) => setIdempotency(event.target.value)} />
          </Field>
          <button type="button" onClick={() => setIdempotency(crypto.randomUUID())}>
            {t.regenerate}
          </button>
          <button type="submit" className="primary" disabled={createLoading}>
            {t.createDraft}
          </button>
        </div>
      </form> : null}
      {createError ? <PanelState t={t} error={createError} emptyText="" /> : null}
      {canInspect && queue.length ? (
        <div className="stack">
          <h3>{t.reviewQueue}</h3>
          <ul>
            {queue.map((item) => (
              <li key={item.id}>
                <button type="button" onClick={() => void fetchDraft(item.id)}>
                  {item.title} ({dynamicLabel(lang, item.state)})
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <form className="form row" onSubmit={loadDraft}>
        <Field label={t.draftId}>
          <input value={draftId} onChange={(event) => setDraftId(event.target.value)} />
        </Field>
        <button type="submit" disabled={loadLoading || !draftId}>
          {t.loadDraft}
        </button>
      </form>
      {loadError ? <PanelState t={t} error={loadError} emptyText="" /> : null}
      <PanelState t={t} loading={loadLoading || createLoading} empty={!draft} emptyText={t.emptyDraft}>
        {draft ? (
          <div className="result">
            {usedCache ? <p className="muted">{t.cachedDraft}</p> : null}
            <div className="result-head">
              <strong>{draft.title}</strong>
              <StatusBadge status={draft.state} lang={lang} />
            </div>
            <p className="muted">
              {t.draftId}: {draft.id}
            </p>
            <p className="muted">
              {t.revision}: {draft.revision_hash ?? t.none}
            </p>
            <h3>{t.unresolved}</h3>
            {draft.unresolved_assumptions?.length ? (
              <ul>
                {draft.unresolved_assumptions.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : (
              <p className="muted">{t.none}</p>
            )}
            {draft.content && !usedCache ? <JsonBlock value={draft.content} /> : null}
          </div>
        ) : null}
      </PanelState>

      {canReview ? <><h3>{t.review}</h3>
      <p className="muted">{t.selfApproveNote}</p>
      <form className="form" onSubmit={submitReview}>
        <div className="row wrap">
          <Field label={t.decision}>
            <select value={decision} onChange={(event) => setDecision(event.target.value as typeof decision)}>
              <option value="approved">{t.approve}</option>
              <option value="rejected">{t.reject}</option>
            </select>
          </Field>
          <Field label={t.reason}>
            <input value={reason} onChange={(event) => setReason(event.target.value)} />
          </Field>
          <button type="submit" className="primary" disabled={reviewLoading || !draft?.revision_hash}>
            {t.submitReview}
          </button>
        </div>
      </form>
      <PanelState t={t} loading={reviewLoading} error={reviewError} empty={!reviewResult} emptyText={t.empty}>
        {reviewResult ? (
          <div className="result">
            <p>
              {t.reviewResult}: <StatusBadge status={reviewResult.status} lang={lang} /> {dynamicLabel(lang, reviewResult.result?.state ?? "")}
            </p>
            <WarningList t={t} warnings={reviewResult.warnings} />
          </div>
        ) : null}
      </PanelState></> : null}

      {canExport ? <><div className="row">
        <button type="button" onClick={() => void submitExport()} disabled={exportLoading || !draft?.id}>
          {t.exportDraft}
        </button>
      </div>
      <PanelState t={t} loading={exportLoading} error={exportError} empty={!exportResult} emptyText={t.empty}>
        {exportResult ? (
          <div className="result">
            <h3>{t.exportResult}</h3>
            <WarningList t={t} warnings={exportResult.warnings} />
            <JsonBlock value={exportResult.result} />
          </div>
        ) : null}
      </PanelState></> : null}
    </section>
  );
}

function SourcingPanel({ t, lang, onTarget }: { t: Copy; lang: "en" | "id"; onTarget: (type: string, id: string) => void }) {
  const [events, setEvents] = useState<SourcingEvent[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<unknown>(null);
  const [eventId, setEventId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [envelope, setEnvelope] = useState<Envelope<Finding[]> | null>(null);

  useEffect(() => {
    let cancelled = false;
    setListLoading(true);
    api
      .catalogEvents()
      .then((body) => {
        if (cancelled) return;
        setEvents(body.items ?? []);
        if (body.items?.[0]) setEventId(body.items[0].id);
      })
      .catch((err) => {
        if (!cancelled) setListError(err);
      })
      .finally(() => {
        if (!cancelled) setListLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const result = await api.sourcing(eventId);
      setEnvelope(result);
      onTarget("finding", result.result?.[0]?.id ?? result.request_id);
    } catch (err) {
      setEnvelope(null);
      setError(err);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="card">
      <h2>{t.sourcing}</h2>
      <PanelState t={t} loading={listLoading} error={listError} empty={!events.length} emptyText={t.noEvents}>
        <form className="form row" onSubmit={onSubmit}>
          <Field label={t.events}>
            <select value={eventId} onChange={(event) => setEventId(event.target.value)}>
              {events.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title} · {item.category} · {item.participant_count} {t.participantCount.toLowerCase()}
                </option>
              ))}
            </select>
          </Field>
          <button type="submit" className="primary" disabled={loading || !eventId}>
            {t.evaluate}
          </button>
        </form>
      </PanelState>
      <PanelState t={t} loading={loading} error={error} empty={!envelope} emptyText={t.emptySourcing}>
        {envelope ? (
          <div className="result">
            <WarningList t={t} warnings={envelope.warnings} />
            <FindingsTable t={t} lang={lang} findings={envelope.result ?? []} />
          </div>
        ) : null}
      </PanelState>
    </section>
  );
}

function FeedbackPanel({
  t,
  lang,
  lastTarget,
}: {
  t: Copy;
  lang: "en" | "id";
  lastTarget: { type: string; id: string } | null;
}) {
  const [targetType, setTargetType] = useState(lastTarget?.type ?? "question");
  const [targetId, setTargetId] = useState(lastTarget?.id ?? "");
  const [label, setLabel] = useState("helpful");
  const [comment, setComment] = useState("");
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<Envelope<{ id: string }> | null>(null);

  useEffect(() => {
    if (lastTarget) {
      setTargetType(lastTarget.type);
      setTargetId(lastTarget.id);
    }
  }, [lastTarget]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      setResult(
        await api.feedback({
          target_type: targetType,
          target_id: targetId,
          label,
          comment,
          idempotency_key: key,
        }),
      );
      setKey(crypto.randomUUID());
    } catch (err) {
      setResult(null);
      setError(err);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="card">
      <h2>{t.feedback}</h2>
      <form className="form" onSubmit={onSubmit}>
        <div className="row wrap">
          <Field label={t.targetType}>
            <input value={targetType} onChange={(event) => setTargetType(event.target.value)} required />
          </Field>
          <Field label={t.targetId}>
            <input value={targetId} onChange={(event) => setTargetId(event.target.value)} required />
          </Field>
          <Field label={t.label}>
            <select value={label} onChange={(event) => setLabel(event.target.value)}>
              <option value="helpful">{dynamicLabel(lang, "helpful")}</option>
              <option value="incorrect">{dynamicLabel(lang, "incorrect")}</option>
              <option value="incomplete">{dynamicLabel(lang, "incomplete")}</option>
              <option value="unsafe">{dynamicLabel(lang, "unsafe")}</option>
            </select>
          </Field>
        </div>
        <Field label={t.comment}>
          <textarea rows={2} value={comment} onChange={(event) => setComment(event.target.value)} />
        </Field>
        <button type="submit" className="primary" disabled={loading}>
          {t.submitFeedback}
        </button>
      </form>
      <PanelState t={t} loading={loading} error={error} empty={!result} emptyText={t.emptyFeedback}>
        {result ? (
          <p>
            {t.feedbackOk}: {result.result?.id}
          </p>
        ) : null}
      </PanelState>
    </section>
  );
}
