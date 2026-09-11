import { useMemo, useState } from "react";
import { clearAdminLog, useAdminLog } from "../api";
import type { Copy } from "../i18n";
import type { Me, Session } from "../types";
import { JsonBlock } from "../ui";

export function AdminDrawer({
  t,
  session,
  me,
}: {
  t: Copy;
  session: Session | null;
  me: Me | null;
}) {
  const log = useAdminLog();
  const [open, setOpen] = useState(true);
  const warnings = useMemo(
    () => log.flatMap((entry) => entry.warnings.map((warning) => `${entry.path}: ${warning}`)),
    [log],
  );

  if (!open) {
    return (
      <button type="button" className="admin-tab" onClick={() => setOpen(true)}>
        {t.admin}
      </button>
    );
  }

  return (
    <aside className="admin-drawer" aria-label={t.admin}>
      <header>
        <h2>{t.admin}</h2>
        <div className="row">
          <button type="button" className="ghost" onClick={clearAdminLog}>
            {t.clearLog}
          </button>
          <button type="button" className="ghost" onClick={() => setOpen(false)}>
            {t.hideAdmin}
          </button>
        </div>
      </header>
      <p className="muted tiny">{t.adminHint}</p>
      <dl className="meta">
        <dt>{t.signedInAs}</dt>
        <dd>{session?.email ?? t.none}</dd>
        <dt>{t.roles}</dt>
        <dd>{(me?.roles ?? session?.roles ?? []).join(", ") || t.none}</dd>
        <dt>{t.groups}</dt>
        <dd>{me?.groups?.join(", ") || t.none}</dd>
        <dt>{t.principal}</dt>
        <dd className="mono">{session?.principal_id ?? t.none}</dd>
        <dt>{t.workspaceId}</dt>
        <dd className="mono">{session?.workspace_id ?? t.none}</dd>
      </dl>
      <h3>{t.warnings}</h3>
      {warnings.length ? (
        <ul className="warning-log">
          {warnings.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <p className="muted">{t.noWarnings}</p>
      )}
      <h3>{t.requestLog}</h3>
      <ol className="log">
        {log.map((entry) => (
          <li key={entry.id}>
            <details>
              <summary>
                <span className={entry.status >= 400 || entry.status === 0 ? "bad" : "ok"}>
                  {entry.status || "ERR"}
                </span>
                <span className="mono">
                  {entry.method} {entry.path}
                </span>
              </summary>
              <p className="muted tiny">{entry.at}</p>
              {entry.warnings.length ? (
                <p className="limitations">{entry.warnings.join(" · ")}</p>
              ) : null}
              <p className="tiny">{t.request}</p>
              <JsonBlock value={entry.request} />
              <p className="tiny">{t.response}</p>
              <JsonBlock value={entry.response} />
            </details>
          </li>
        ))}
      </ol>
    </aside>
  );
}
