import { useCallback, useEffect, useState } from "react";
import { api, ApiError, formatTime, syncState, type Health, type NotificationSummary, type SyncReport } from "./api";
import { Compose } from "./Compose";
import { BellIcon, ClockIcon, LogoMark, PartnersIcon, PartsIcon, SyncIcon } from "./icons";
import { NotificationDetail } from "./NotificationDetail";
import { Notifications } from "./Notifications";
import { PartDetail } from "./PartDetail";
import { PartList } from "./PartList";
import { Partners } from "./Partners";
import { SyncHistory } from "./SyncHistory";

type Route =
  | { page: "parts" }
  | { page: "part"; id: string }
  | { page: "sync" }
  | { page: "partners" }
  | { page: "notifications" }
  | { page: "notification"; id: number }
  | { page: "compose"; query: string };

function parseRoute(hash: string): Route {
  const part = /^#\/parts\/(.+)$/.exec(hash);
  if (part) return { page: "part", id: decodeURIComponent(part[1]) };
  const notification = /^#\/notifications\/(\d+)$/.exec(hash);
  if (notification) return { page: "notification", id: Number(notification[1]) };
  if (hash.startsWith("#/notifications")) return { page: "notifications" };
  if (hash.startsWith("#/compose?")) return { page: "compose", query: hash.slice("#/compose?".length) };
  if (hash === "#/sync") return { page: "sync" };
  if (hash === "#/partners") return { page: "partners" };
  return { page: "parts" };
}

const SECTION: Record<Route["page"], "parts" | "sync" | "partners" | "notifications"> = {
  parts: "parts",
  part: "parts",
  sync: "sync",
  partners: "partners",
  notifications: "notifications",
  notification: "notifications",
  compose: "notifications",
};

function useRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const onChange = () => {
      setRoute(parseRoute(window.location.hash));
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export function App() {
  const route = useRoute();
  const [health, setHealth] = useState<Health | null>(null);
  const [lastRun, setLastRun] = useState<SyncReport | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Bumped after every sync so pages reload their data.
  const [dataVersion, setDataVersion] = useState(0);

  const [summary, setSummary] = useState<NotificationSummary | null>(null);

  useEffect(() => {
    api.health().then(setHealth, (e: Error) => setError(e.message));
    api.lastSync().then(setLastRun, () => setLastRun(null));
  }, []);

  // New notifications arrive from partners at any time: refresh the inbox counter.
  useEffect(() => {
    const load = () => api.notificationSummary().then(setSummary, () => undefined);
    load();
    const timer = setInterval(load, 30_000);
    return () => clearInterval(timer);
  }, [route, dataVersion]);

  const sync = useCallback(async () => {
    setSyncing(true);
    setError(null);
    try {
      setLastRun(await api.sync());
      setDataVersion((v) => v + 1);
    } catch (e) {
      setError(e instanceof ApiError ? `Sync failed: ${e.message}` : String(e));
    } finally {
      setSyncing(false);
    }
  }, []);

  return (
    <div className="app">
      <header className="topbar">
        <a className="brand" href="#/">
          <LogoMark />
          <span className="brand-text">
            <span className="brand-name">Traceability</span>
            <span className="brand-sub">Catena-X · Tractus-X 26.03</span>
          </span>
        </a>
        {health && <span className="bpnl-chip">{health.own_bpnl}</span>}
        <div className="spacer" />
        <span className="sync-status" aria-live="polite">
          {lastRun ? (
            <>
              <span className={`dot ${syncState(lastRun)}`} />
              Synced {formatTime(lastRun.finished_at ?? lastRun.started_at)} · {lastRun.twins} twins ·{" "}
              {lastRun.issues.length} issues
            </>
          ) : (
            <>
              <span className="dot" />
              Not synced yet
            </>
          )}
        </span>
        <button
          type="button"
          className="btn btn-primary"
          onClick={sync}
          disabled={syncing || !health?.dtr_configured}
          title={health && !health.dtr_configured ? "No Digital Twin Registry configured" : undefined}
        >
          <SyncIcon className={syncing ? "spin" : undefined} />
          {syncing ? "Syncing…" : "Sync own twins"}
        </button>
      </header>

      {health?.dev_direct && (
        <div className="dev-banner" role="note">
          Development mode — partners are reached directly, without EDCs. Not for use in a dataspace.
        </div>
      )}

      <div className="layout">
        <nav className="sidenav" aria-label="Main">
          {(
            [
              ["parts", "#/", <PartsIcon key="i" />, "Parts"],
              ["notifications", "#/notifications", <BellIcon key="i" />, "Notifications"],
              ["partners", "#/partners", <PartnersIcon key="i" />, "Partners"],
              ["sync", "#/sync", <ClockIcon key="i" />, "Sync history"],
            ] as const
          ).map(([section, href, icon, label]) => (
            <a
              key={section}
              className="nav-item"
              href={href}
              aria-current={SECTION[route.page] === section ? "page" : undefined}
            >
              {icon}
              {label}
              {section === "notifications" && summary && summary.inbound_new > 0 && (
                <span className="badge badge-count" aria-label={`${summary.inbound_new} new`}>
                  {summary.inbound_new}
                </span>
              )}
            </a>
          ))}
        </nav>

        <main className="content">
          {error && (
            <div className="alert alert-error" role="alert">
              {error}
            </div>
          )}
          {route.page === "parts" && <PartList dataVersion={dataVersion} />}
          {route.page === "part" && <PartDetail id={route.id} dataVersion={dataVersion} />}
          {route.page === "sync" && <SyncHistory health={health} dataVersion={dataVersion} />}
          {route.page === "partners" && <Partners health={health} dataVersion={dataVersion} />}
          {route.page === "notifications" && <Notifications key={window.location.hash} dataVersion={dataVersion} />}
          {route.page === "notification" && <NotificationDetail id={route.id} health={health} />}
          {route.page === "compose" && <Compose key={route.query} query={route.query} health={health} />}
        </main>
      </div>
    </div>
  );
}
