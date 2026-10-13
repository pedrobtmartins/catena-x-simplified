import { useCallback, useEffect, useState } from "react";
import { api, ApiError, formatTime, syncState, type Health, type SyncReport } from "./api";
import { BellIcon, ClockIcon, LogoMark, PartsIcon, SyncIcon } from "./icons";
import { PartDetail } from "./PartDetail";
import { PartList } from "./PartList";
import { SyncHistory } from "./SyncHistory";

type Route = { page: "parts" } | { page: "part"; id: string } | { page: "sync" };

function parseRoute(hash: string): Route {
  const part = /^#\/parts\/(.+)$/.exec(hash);
  if (part) return { page: "part", id: decodeURIComponent(part[1]) };
  if (hash === "#/sync") return { page: "sync" };
  return { page: "parts" };
}

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

  useEffect(() => {
    api.health().then(setHealth, (e: Error) => setError(e.message));
    api.lastSync().then(setLastRun, () => setLastRun(null));
  }, []);

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

      <div className="layout">
        <nav className="sidenav" aria-label="Main">
          <a className="nav-item" href="#/" aria-current={route.page !== "sync" ? "page" : undefined}>
            <PartsIcon />
            Parts
          </a>
          <a className="nav-item" href="#/sync" aria-current={route.page === "sync" ? "page" : undefined}>
            <ClockIcon />
            Sync history
          </a>
          <span className="nav-item" aria-disabled="true">
            <BellIcon />
            Notifications
            <span className="badge badge-phase">Phase 2</span>
          </span>
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
        </main>
      </div>
    </div>
  );
}
