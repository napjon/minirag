import { FormEvent, type ReactNode, useState } from "react";
import { api, ApiError } from "../api";
import type { Copy } from "../i18n";
import { DEMO_USERS, type Session } from "../types";

export function Login({
  t,
  onSession,
}: {
  t: Copy;
  onSession: (session: Session) => void;
}) {
  const [email, setEmail] = useState("analyst@marketdesk.test");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(nextEmail = email) {
    setLoading(true);
    setError(null);
    try {
      const token = await api.login(nextEmail);
      onSession({ ...token, email: nextEmail });
    } catch (err) {
      const message = err instanceof ApiError ? `${err.status ? `${err.status}: ` : ""}${err.message}` : String(err);
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void submit();
  }

  return (
    <div className="login-shell">
      <form className="login-card" onSubmit={onSubmit}>
        <p className="eyebrow">{t.workspaceName}</p>
        <h1>{t.appName}</h1>
        <p className="muted">{t.tagline}</p>
        <Fieldish label={t.email}>
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="username"
            required
          />
        </Fieldish>
        <button type="submit" className="primary" disabled={loading}>
          {loading ? t.loading : t.signIn}
        </button>
        {error ? (
          <div className="state state-error" role="alert">
            {error}
          </div>
        ) : null}
        <p className="section-label">{t.demoIdentities}</p>
        <div className="chips">
          {DEMO_USERS.map((user) => (
            <button
              type="button"
              key={user.email}
              className={email === user.email ? "chip active" : "chip"}
              onClick={() => {
                setEmail(user.email);
                void submit(user.email);
              }}
              disabled={loading}
            >
              {user.email}
              <span>{user.role}</span>
            </button>
          ))}
        </div>
        <p className="muted tiny">{t.demoWorkspace}</p>
      </form>
    </div>
  );
}

function Fieldish({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}
