// The app shell: top bar (own BPNL, admin sign-in, last sync, "Sync own twins"), side navigation
// and hash routing (#/parts/…, #/notifications/…, #/partners, #/sync, #/setup). It reads the
// health of the backend on every route change, so pages can show only what is configured, and
// opens Setup on first use while no Digital Twin Registry is connected. A sync bumps
// `dataVersion`, which makes every page reload its data.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, formatTime, syncState, type Health, type Me, type NotificationSummary, type SyncReport, type SyncStatus } from "./api";
import { Compose } from "./Compose";
import { DataChecksPage } from "./DataChecks";
import { ThemeSwitch } from "./Theme";
import { Login } from "./Login";
import { BellIcon, ClockIcon, FlagIcon, LogoMark, PartnersIcon, PartsIcon, SettingsIcon, SyncIcon } from "./icons";
import { NotificationDetail } from "./NotificationDetail";
import { Notifications } from "./Notifications";
import { PartDetail } from "./PartDetail";
import { PartList } from "./PartList";
import { Partners } from "./Partners";
import { Setup } from "./Setup";
import { SyncHistory } from "./SyncHistory";

type Route =
  | { page: "parts" }
  | { page: "part"; id: string }
  | { page: "sync" }
  | { page: "partners" }
  | { page: "setup" }
  | { page: "login" }
  | { page: "checks" }
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
  if (hash === "#/setup") return { page: "setup" };
  if (hash === "#/login") return { page: "login" };
  if (hash === "#/data-checks") return { page: "checks" };
  return { page: "parts" };
}

// The browser tab says where you are; detail pages add what they show once it is known.
const TITLE: Record<Route["page"], string> = {
  parts: "Parts",
  part: "Part",
  sync: "Sync history",
  partners: "Partners",
  setup: "Setup",
  login: "Admin sign-in",
  checks: "Data checks",
  notifications: "Notifications",
  notification: "Notification",
  compose: "New notification",
};

const SECTION: Record<Route["page"], "parts" | "sync" | "partners" | "notifications" | "setup" | "checks"> = {
  parts: "parts",
  part: "parts",
  sync: "sync",
  partners: "partners",
  setup: "setup",
  login: "setup",
  checks: "checks",
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
  const [starting, setStarting] = useState(false);
  const [ownStatus, setOwnStatus] = useState<SyncStatus | null>(null);
  const ownRunning = ownStatus?.running ?? false;
  const syncing = starting || ownRunning;
  const wasOwnRunning = useRef(false);
  const [error, setError] = useState<string | null>(null);
  // Bumped after every sync so pages reload their data.
  const [dataVersion, setDataVersion] = useState(0);

  const [summary, setSummary] = useState<NotificationSummary | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const loadHealth = useCallback(() => api.health().then(setHealth, (e: Error) => setError(e.message)), []);

  useEffect(() => {
    api.me().then(setMe, () => setMe(null));
  }, [route]);

  useEffect(() => {
    document.title = `${TITLE[route.page]} · Traceability`;
  }, [route]);

  const signOut = async () => {
    setMe(await api.logout());
  };
  // Changing partners needs an admin once the admin login is set up.
  const canEdit = !me?.login_enabled || Boolean(me.admin);

  useEffect(() => {
    api.health().then((h) => {
      setHealth(h);
      // First run: without a registry the app has nothing to show yet, so start with the setup.
      if (!h.dtr_configured && ["", "#", "#/"].includes(window.location.hash)) window.location.hash = "#/setup";
    }, (e: Error) => setError(e.message));
    api.lastSync().then(setLastRun, () => setLastRun(null));
    api.syncStatus().then(setOwnStatus, () => undefined);
  }, []);

  // The own sync runs in the background: follow it while it runs.
  useEffect(() => {
    if (!syncing) return;
    const timer = window.setInterval(() => api.syncStatus().then(setOwnStatus, () => undefined), 1000);
    return () => window.clearInterval(timer);
  }, [syncing]);

  // It has ended: show the run and let the pages reload their data.
  useEffect(() => {
    if (wasOwnRunning.current && !ownRunning) {
      api.lastSync().then(setLastRun, () => undefined);
      setDataVersion((v) => v + 1);
    }
    wasOwnRunning.current = ownRunning;
  }, [ownRunning]);

  // New notifications arrive from partners at any time: refresh the inbox counter.
  useEffect(() => {
    const load = () => api.notificationSummary().then(setSummary, () => undefined);
    load();
    const timer = setInterval(load, 30_000);
    return () => clearInterval(timer);
  }, [route, dataVersion]);

  // Data check findings change only with a sync: counted once per sync for the menu.
  const [findings, setFindings] = useState<number | null>(null);
  useEffect(() => {
    api.dataChecks().then((c) => setFindings(c.total), () => setFindings(null));
  }, [dataVersion]);

  // Core connections still missing; the Setup page explains them.
  const unconfigured = health
    ? [health.dtr_configured, health.dev_direct || health.edc_configured].filter((ok) => !ok).length
    : 0;

  const sync = useCallback(async () => {
    setStarting(true);
    setError(null);
    try {
      const started = await api.sync();
      setOwnStatus(started);
      if (!started.running) {
        // Over before it could be followed.
        setLastRun(await api.lastSync());
        setDataVersion((v) => v + 1);
      }
    } catch (e) {
      setError(e instanceof ApiError ? `Sync failed: ${e.message}` : String(e));
      api.syncStatus().then(setOwnStatus, () => undefined);
    } finally {
      setStarting(false);
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
        <ThemeSwitch />
        {me?.login_enabled &&
          (me.admin ? (
            <span className="admin-chip">
              <span className="sub">Signed in as</span> {me.admin}
              <button type="button" className="link-btn" onClick={signOut}>
                Sign out
              </button>
            </span>
          ) : (
            <a className="link-btn admin-chip" href="#/login">
              Admin sign-in
            </a>
          ))}
        <span className="sync-status" aria-live="polite">
          {ownRunning && ownStatus ? (
            <>
              <span className="dot" />
              Syncing · {ownStatus.twins} twins · {ownStatus.parts} parts so far
            </>
          ) : lastRun ? (
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
              ["checks", "#/data-checks", <FlagIcon key="i" />, "Data checks"],
              ["sync", "#/sync", <ClockIcon key="i" />, "Sync history"],
              ["setup", "#/setup", <SettingsIcon key="i" />, "Setup"],
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
              {section === "setup" && unconfigured > 0 && (
                <span className="badge badge-count" aria-label={`${unconfigured} to set up`}>
                  {unconfigured}
                </span>
              )}
              {section === "checks" && findings !== null && findings > 0 && (
                <span className="badge badge-count" aria-label={`${findings} to review`}>
                  {findings}
                </span>
              )}
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
          {route.page === "checks" && <DataChecksPage dataVersion={dataVersion} ownBpnl={health?.own_bpnl ?? null} />}
          {route.page === "partners" && <Partners health={health} dataVersion={dataVersion} canEdit={canEdit} />}
          {route.page === "setup" && (
            <Setup
              health={health}
              me={me}
              dataVersion={dataVersion}
              lastRun={lastRun}
              syncing={syncing}
              onSync={sync}
              onHealthChange={loadHealth}
            />
          )}
          {route.page === "notifications" && <Notifications key={window.location.hash} dataVersion={dataVersion} />}
          {route.page === "notification" && <NotificationDetail id={route.id} health={health} />}
          {route.page === "login" && <Login me={me} onSignedIn={setMe} />}
          {route.page === "compose" && <Compose key={route.query} query={route.query} health={health} />}
        </main>
      </div>
    </div>
  );
}
