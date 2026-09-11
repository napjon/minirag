import { useEffect, useMemo, useState } from "react";
import { api, ApiError, clearAdminLog, clearSession, readLang, readSession, writeLang, writeSession } from "./api";
import { messages, type Copy } from "./i18n";
import { canOpenWorkspace, effectiveCapabilities } from "./capabilities";
import type { Health, Lang, Me, Session, WorkspaceId } from "./types";
import { AdminDrawer } from "./views/AdminDrawer";
import { Catalog } from "./views/Catalog";
import { Knowledge } from "./views/Knowledge";
import { Login } from "./views/Login";
import { Planning } from "./views/Planning";

function readWorkspace(): WorkspaceId {
  const hash = window.location.hash.replace("#", "");
  if (hash === "catalog" || hash === "planning" || hash === "knowledge") return hash;
  return "knowledge";
}

function readAdmin() {
  return new URLSearchParams(window.location.search).get("admin") === "true";
}

export default function App() {
  const [lang, setLang] = useState<Lang>(readLang);
  const [session, setSession] = useState<Session | null>(readSession);
  const [me, setMe] = useState<Me | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceId>(readWorkspace);
  const [admin] = useState(readAdmin);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [lastTarget, setLastTarget] = useState<{ type: string; id: string } | null>(null);
  const t: Copy = messages[lang];
  const capabilities = useMemo(
    () => effectiveCapabilities(me, me?.roles ?? session?.roles ?? []),
    [me, session],
  );

  useEffect(() => {
    document.documentElement.lang = lang;
    writeLang(lang);
  }, [lang]);

  useEffect(() => {
    const onHash = () => setWorkspace(readWorkspace());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    const onLogout = () => {
      setSession(null);
      setMe(null);
      setLastTarget(null);
    };
    window.addEventListener("marketdesk:logout", onLogout);
    return () => window.removeEventListener("marketdesk:logout", onLogout);
  }, []);

  useEffect(() => {
    api
      .health()
      .then((body) => {
        setHealth(body);
        setHealthError(false);
      })
      .catch(() => {
        setHealth(null);
        setHealthError(true);
      });
  }, []);

  useEffect(() => {
    if (!session) {
      setMe(null);
      return;
    }
    api
      .me()
      .then(setMe)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          clearSession();
          setSession(null);
        }
      });
  }, [session]);

  function navigate(next: WorkspaceId) {
    window.location.hash = next;
    setWorkspace(next);
  }

  function onSession(next: Session) {
    writeSession(next);
    setLastTarget(null);
    setMe(null);
    setSession(next);
    navigate("knowledge");
  }

  function signOut() {
    clearAdminLog();
    clearSession();
    setSession(null);
    setMe(null);
    setLastTarget(null);
    navigate("knowledge");
  }

  function onTarget(type: string, id: string) {
    setLastTarget({ type, id });
  }

  const workspaces = useMemo(
    () =>
      [
        { id: "knowledge" as const, label: t.knowledge, hint: t.knowledgeHint },
        { id: "catalog" as const, label: t.catalog, hint: t.catalogHint },
        { id: "planning" as const, label: t.planning, hint: t.planningHint },
      ],
    [t],
  );
  const availableWorkspaces = useMemo(
    () => workspaces.filter((item) => canOpenWorkspace(capabilities, item.id)),
    [capabilities, workspaces],
  );
  const showAdmin = admin && capabilities.has("admin");

  useEffect(() => {
    if (!session || !me || canOpenWorkspace(capabilities, workspace)) return;
    const fallback = availableWorkspaces[0]?.id;
    if (fallback) navigate(fallback);
  }, [availableWorkspaces, capabilities, me, session, workspace]);

  return (
    <div className={showAdmin ? "app shell app-admin" : "app shell"}>
      <aside className="nav">
        <div className="brand">
          <span className="logo">M</span>
          <div>
            <strong>{t.appName}</strong>
            <span className="tag">{t.workspaceName}</span>
          </div>
        </div>
        {session ? (
          <nav>
            {availableWorkspaces.map((item) => (
              <button
                key={item.id}
                type="button"
                className={workspace === item.id ? "nav-item active" : "nav-item"}
                onClick={() => navigate(item.id)}
              >
                <span>{item.label}</span>
                <small className="hint">{item.hint}</small>
              </button>
            ))}
          </nav>
        ) : (
          <p className="muted nav-copy">{t.tagline}</p>
        )}
        <div className="nav-foot userbox">
          <div className="lang">
            <button type="button" className={lang === "en" ? "active" : ""} onClick={() => setLang("en")}>
              EN
            </button>
            <button type="button" className={lang === "id" ? "active" : ""} onClick={() => setLang("id")}>
              ID
            </button>
          </div>
          {session ? (
            <div className="who">
              <strong>{session.display_name}</strong>
              <span>{session.email}</span>
              <span className="roles">{(me?.roles ?? session.roles).join(" · ")}</span>
              <button type="button" className="ghost" onClick={signOut}>
                {t.signOut}
              </button>
            </div>
          ) : null}
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <h1>{session ? availableWorkspaces.find((item) => item.id === workspace)?.label : t.signIn}</h1>
          <div className={`health ${health?.ok ? "ok" : healthError ? "bad" : ""}`}>
            {t.health}: {health?.ok ? t.online : healthError ? t.offline : t.loading}
            {health ? ` · ${health.provider}` : ""}
          </div>
        </header>
        <div className="content">
          {!session ? (
            <Login t={t} onSession={onSession} />
          ) : workspace === "catalog" ? (
            <Catalog key={session.email} t={t} lang={lang} capabilities={capabilities} onTarget={onTarget} />
          ) : workspace === "planning" ? (
            <Planning
              key={session.email}
              t={t}
              lang={lang}
              roles={me?.roles ?? session.roles}
              capabilities={capabilities}
              lastTarget={lastTarget}
              onTarget={onTarget}
            />
          ) : (
            <Knowledge key={session.email} t={t} lang={lang} capabilities={capabilities} onTarget={onTarget} />
          )}
        </div>
      </main>
      {showAdmin ? <AdminDrawer t={t} session={session} me={me} /> : null}
    </div>
  );
}
