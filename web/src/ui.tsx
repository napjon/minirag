import type { ReactNode } from "react";
import { ApiError } from "./api";
import type { Copy } from "./i18n";
import { dynamicLabel } from "./i18n";
import type { Lang } from "./types";

export function PanelState({
  t,
  loading,
  error,
  empty,
  emptyText,
  children,
}: {
  t: Copy;
  loading?: boolean;
  error?: unknown;
  empty?: boolean;
  emptyText: string;
  children?: ReactNode;
}) {
  if (loading) {
    return (
      <div className="state state-loading" role="status">
        {t.loading}
      </div>
    );
  }
  if (error) {
    const status = error instanceof ApiError ? error.status : 0;
    const forbidden = status === 403;
    const message = error instanceof Error ? error.message : String(error);
    return (
      <div className={forbidden ? "state state-403" : "state state-error"} role="alert">
        <strong>
          {forbidden ? t.forbidden : t.error}
          {status ? ` (${status})` : ""}
        </strong>
        <p>{message}</p>
      </div>
    );
  }
  if (empty) {
    return (
      <div className="state state-empty">
        <p>{emptyText}</p>
        <p className="muted">{t.emptyHint}</p>
      </div>
    );
  }
  return (
    <>
      <span className="sr-only" role="status" aria-live="polite">{t.resultsReady}</span>
      {children}
    </>
  );
}

export function StatusBadge({ status, lang }: { status: string; lang: Lang }) {
  const tone =
    status === "answered" || status === "approved" || status === "accepted" || status === "range"
      ? "ok"
      : status === "needs_clarification" || status === "insufficient_evidence" || status === "insufficient_comparables"
        ? "warn"
        : status === "out_of_scope" || status === "unavailable" || status === "rejected"
          ? "bad"
          : "neutral";
  return <span className={`badge badge-${tone}`}>{dynamicLabel(lang, status)}</span>;
}

export function DataTable({ rows, lang }: { rows: Array<Record<string, unknown>>; lang: Lang }) {
  if (!rows.length) return null;
  const cols = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {cols.map((col) => (
              <th key={col}>{dynamicLabel(lang, col)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {cols.map((col) => (
                <td key={col}>{formatCell(row[col])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatCell(value: unknown): string {
  if (value == null || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function numericKeys(rows: Array<Record<string, unknown>>): string[] {
  if (!rows.length) return [];
  return Object.keys(rows[0]).filter((key) => rows.some((row) => Number.isFinite(Number(row[key]))));
}

export function ResultChart({
  rows,
  mode,
  label,
  description,
}: {
  rows: Array<Record<string, unknown>>;
  mode: "bar" | "line";
  label: string;
  description: string;
}) {
  if (!rows.length) return null;
  const keys = Object.keys(rows[0]);
  const valueKey = numericKeys(rows)[0];
  if (!valueKey) return null;
  const labelKey = keys.find((key) => key !== valueKey) ?? keys[0];
  const values = rows.map((row) => Math.abs(Number(row[valueKey]) || 0));
  const max = Math.max(...values, 1);

  if (mode === "line") {
    const w = 640;
    const h = 140;
    const pts = values
      .map((value, index) => {
        const x = values.length === 1 ? w / 2 : (index / (values.length - 1)) * (w - 24) + 12;
        const y = h - 16 - (value / max) * (h - 32);
        return `${x},${y}`;
      })
      .join(" ");
    return (
      <svg className="line-chart" viewBox={`0 0 ${w} ${h}`} role="img" aria-label={label}>
        <title>{label}</title>
        <desc>{description}</desc>
        <polyline fill="none" stroke="currentColor" strokeWidth="2" points={pts} />
      </svg>
    );
  }

  return (
    <div className="bars" role="img" aria-label={`${label}: ${description}`}>
      {rows.map((row, index) => {
        const value = Number(row[valueKey]) || 0;
        return (
          <div className="bar-row" key={index}>
            <span className="bar-label">{formatCell(row[labelKey])}</span>
            <div className="bar-track">
              <div className="bar-fill" style={{ width: `${(Math.abs(value) / max) * 100}%` }} />
            </div>
            <span className="bar-value">{formatCell(row[valueKey])}</span>
          </div>
        );
      })}
    </div>
  );
}

export function WarningList({ t, warnings }: { t: Copy; warnings?: string[] | null }) {
  if (!warnings?.length) return null;
  return (
    <div className="warnings">
      <strong>{t.warningsOnResult}</strong>
      <ul>
        {warnings.map((warning) => (
          <li key={warning}>{warning}</li>
        ))}
      </ul>
    </div>
  );
}

export function JsonBlock({ value }: { value: unknown }) {
  return <pre className="json">{JSON.stringify(value, null, 2)}</pre>;
}

export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}

export function FindingsTable({
  t,
  lang,
  findings,
}: {
  t: Copy;
  lang: Lang;
  findings: Array<{
    detector_id: string;
    detector_version: string;
    severity: string;
    state: string;
    explanation: string;
  }>;
}) {
  if (!findings.length) {
    return <p className="muted">{t.empty}</p>;
  }
  return (
    <DataTable lang={lang}
      rows={findings.map((item) => ({
        detector: item.detector_id,
        version: item.detector_version,
        severity: item.severity,
        state: item.state,
        explanation: item.explanation,
      }))}
    />
  );
}
