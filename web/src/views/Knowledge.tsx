import { FormEvent, useState } from "react";
import { api } from "../api";
import type { Copy } from "../i18n";
import { dynamicLabel } from "../i18n";
import { ANALYTICS_PATTERNS, CATEGORIES, type Envelope, type Lang, type QuestionResult, type SourceView } from "../types";
import { DataTable, Field, PanelState, ResultChart, StatusBadge, WarningList } from "../ui";
import type { Capability } from "../capabilities";

export function Knowledge({
  t,
  lang,
  capabilities,
  onTarget,
}: {
  t: Copy;
  lang: Lang;
  capabilities: Set<Capability>;
  onTarget: (type: string, id: string) => void;
}) {
  return (
    <div className="stack">
      {capabilities.has("questions") ? <QaPanel t={t} lang={lang} onTarget={onTarget} /> : null}
      {capabilities.has("analytics") ? <AnalyticsPanel t={t} lang={lang} onTarget={onTarget} /> : null}
    </div>
  );
}

function QaPanel({
  t,
  lang,
  onTarget,
}: {
  t: Copy;
  lang: Lang;
  onTarget: (type: string, id: string) => void;
}) {
  const [question, setQuestion] = useState("Who may run operational queries?");
  const [asOf, setAsOf] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [envelope, setEnvelope] = useState<Envelope<QuestionResult> | null>(null);
  const [source, setSource] = useState<SourceView | null>(null);
  const [sourceError, setSourceError] = useState<unknown>(null);
  const [sourceLoading, setSourceLoading] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    setSource(null);
    try {
      const result = await api.question({
        question,
        language: lang,
        as_of: asOf || null,
      });
      setEnvelope(result);
      onTarget("question", result.request_id);
    } catch (err) {
      setEnvelope(null);
      setError(err);
    } finally {
      setLoading(false);
    }
  }

  async function openSource(id: string) {
    setSourceLoading(true);
    setSourceError(null);
    try {
      setSource(await api.getSource(id));
    } catch (err) {
      setSource(null);
      setSourceError(err);
    } finally {
      setSourceLoading(false);
    }
  }

  const result = envelope?.result;

  return (
    <section className="card">
      <h2>{t.qa}</h2>
      <form className="form" onSubmit={onSubmit}>
        <Field label={t.question}>
          <textarea
            rows={3}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            minLength={3}
            required
          />
        </Field>
        <div className="row">
          <Field label={t.asOf}>
            <input type="date" value={asOf} onChange={(event) => setAsOf(event.target.value)} />
          </Field>
          <button type="submit" className="primary" disabled={loading}>
            {t.ask}
          </button>
        </div>
      </form>
      <PanelState t={t} loading={loading} error={error} empty={!envelope} emptyText={t.emptyQa}>
        {envelope && result ? (
          <div className="result">
            <div className="result-head">
              <StatusBadge status={envelope.status} lang={lang} />
              {result.language ? <span className="muted">{result.language}</span> : null}
            </div>
            <WarningList t={t} warnings={envelope.warnings} />
            {result.answer ? <p className="answer">{result.answer}</p> : <p className="muted">{t.empty}</p>}
            {result.limitations ? (
              <p className="limitations">
                <strong>{t.limitations}: </strong>
                {result.limitations}
              </p>
            ) : null}
            {result.claims?.length ? (
              <div>
                <h3>{t.claims}</h3>
                <ul className="claims">
                  {result.claims.map((claim, index) => (
                    <li key={index}>
                      {typeof claim.text === "string" ? claim.text : JSON.stringify(claim)}
                      {typeof claim.evidence_id === "string" ? (
                        <span className="muted"> ({claim.evidence_id.slice(0, 8)})</span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            <h3>{t.citations}</h3>
            {envelope.evidence?.length ? (
              <ul className="citations">
                {envelope.evidence.map((item) => (
                  <li key={item.chunk_id}>
                    <div>
                      <strong>{item.section_path || item.document_id}</strong>
                      <p>{item.supporting_span}</p>
                      <p className="muted">
                        {item.page_or_table_location}
                        {item.source_effective_date ? ` · ${item.source_effective_date}` : ""}
                      </p>
                    </div>
                    <button type="button" onClick={() => void openSource(item.document_id)}>
                      {t.openSource}
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">{t.noCitations}</p>
            )}
          </div>
        ) : null}
      </PanelState>
      {sourceLoading || sourceError || source ? (
        <div className="source-pane">
          <div className="result-head">
            <h3>{t.source}</h3>
            <button type="button" className="ghost" onClick={() => setSource(null)}>
              {t.close}
            </button>
          </div>
          <PanelState t={t} loading={sourceLoading} error={sourceError} empty={!source} emptyText={t.empty}>
            {source ? (
              <article>
                <h4>{source.title}</h4>
                <p className="muted">
                  {t.topic}: {source.topic} · {t.status}: {source.status}
                  {source.effective_from ? ` · ${t.effective}: ${source.effective_from}` : ""}
                </p>
                <pre className="source-text">{source.text}</pre>
              </article>
            ) : null}
          </PanelState>
        </div>
      ) : null}
    </section>
  );
}

function AnalyticsPanel({
  t,
  lang,
  onTarget,
}: {
  t: Copy;
  lang: Lang;
  onTarget: (type: string, id: string) => void;
}) {
  const [pattern, setPattern] = useState<(typeof ANALYTICS_PATTERNS)[number]>("spending_by_period");
  const [start, setStart] = useState("2030-01-01");
  const [end, setEnd] = useState("2030-06-30");
  const [category, setCategory] = useState("");
  const [presentation, setPresentation] = useState<"table" | "bar" | "line">("table");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [envelope, setEnvelope] = useState<Envelope<import("../types").AnalyticsResult> | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const filters: Record<string, unknown> = { start_date: start, end_date: end };
      if (category) filters.category_ids = [category];
      const result = await api.analytics({
        pattern,
        filters,
        group_by: ["month"],
        presentation,
      });
      setEnvelope(result);
      onTarget("analytics", result.request_id);
    } catch (err) {
      setEnvelope(null);
      setError(err);
    } finally {
      setLoading(false);
    }
  }

  const rows = envelope?.result?.rows ?? [];
  const mode = envelope?.result?.presentation ?? presentation;

  return (
    <section className="card">
      <h2>{t.analytics}</h2>
      <p className="muted">{t.viewerNote}</p>
      <form className="form" onSubmit={onSubmit}>
        <div className="row wrap">
          <Field label={t.pattern}>
            <select value={pattern} onChange={(event) => setPattern(event.target.value as typeof pattern)}>
              {ANALYTICS_PATTERNS.map((item) => (
                <option key={item} value={item}>
                  {dynamicLabel(lang, item)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t.startDate}>
            <input type="date" value={start} onChange={(event) => setStart(event.target.value)} required />
          </Field>
          <Field label={t.endDate}>
            <input type="date" value={end} onChange={(event) => setEnd(event.target.value)} required />
          </Field>
          <Field label={t.category}>
            <select value={category} onChange={(event) => setCategory(event.target.value)}>
              <option value="">{t.allCategories}</option>
              {CATEGORIES.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t.presentation}>
            <select
              value={presentation}
              onChange={(event) => setPresentation(event.target.value as typeof presentation)}
            >
              <option value="table">{t.table}</option>
              <option value="bar">{t.bar}</option>
              <option value="line">{t.line}</option>
            </select>
          </Field>
          <button type="submit" className="primary" disabled={loading}>
            {t.runQuery}
          </button>
        </div>
      </form>
      <PanelState t={t} loading={loading} error={error} empty={!envelope} emptyText={t.emptyAnalytics}>
        {envelope?.result ? (
          <div className="result">
            <div className="result-head">
              <StatusBadge status={envelope.status} lang={lang} />
              <span className="muted">
                {envelope.result.row_count} {t.rowCount}
                {envelope.result.freshness ? ` · ${t.freshness} ${envelope.result.freshness}` : ""}
              </span>
            </div>
            <WarningList t={t} warnings={envelope.warnings} />
            {rows.length === 0 ? (
              <p className="muted">{t.noRows}</p>
            ) : (
              <>
                {(mode === "bar" || mode === "line") && (
                  <ResultChart
                    rows={rows}
                    mode={mode}
                    label={t.analyticsChart}
                    description={`${t.chartDataPoints}: ${rows.length}`}
                  />
                )}
                <DataTable rows={rows} lang={lang} />
              </>
            )}
          </div>
        ) : null}
      </PanelState>
    </section>
  );
}
