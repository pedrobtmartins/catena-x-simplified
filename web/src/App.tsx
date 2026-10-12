import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type Health, type SyncReport } from "./api";
import { PartDetail } from "./PartDetail";
import { PartList } from "./PartList";

// Minimal hash routing: "#/" (list) and "#/parts/<globalAssetId>" (detail).
function useRoute(): [string | null, (id: string | null) => void] {
  const read = () => {
    const match = /^#\/parts\/(.+)$/.exec(window.location.hash);
    return match ? decodeURIComponent(match[1]) : null;
  };
  const [partId, setPartId] = useState(read);
  useEffect(() => {
    const onChange = () => setPartId(read());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  const navigate = (id: string | null) => {
    window.location.hash = id ? `#/parts/${encodeURIComponent(id)}` : "#/";
  };
  return [partId, navigate];
}

export function App() {
  const [partId, navigate] = useRoute();
  const [health, setHealth] = useState<Health | null>(null);
  const [report, setReport] = useState<SyncReport | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    api.health().then(setHealth, (e: Error) => setError(e.message));
    api.lastSync().then(setReport, () => setReport(null));
  }, []);

  const sync = useCallback(async () => {
    setSyncing(true);
    setError(null);
    try {
      setReport(await api.sync());
      setRefreshKey((k) => k + 1);
    } catch (e) {
      setError(e instanceof ApiError ? `Sync failed: ${e.message}` : String(e));
    } finally {
      setSyncing(false);
    }
  }, []);

  return (
    <div className="app">
      <header>
        <a className="brand" href="#/">
          Catena-X Traceability
        </a>
        <span className="bpnl">{health?.own_bpnl}</span>
        <div className="spacer" />
        {report && (
          <span className={report.complete && report.issues.length === 0 ? "sync ok" : "sync warn"}>
            Last sync {new Date(report.finished_at ?? report.started_at).toLocaleString()} ·{" "}
            {report.parts} parts · {report.issues.length} issues
          </span>
        )}
        <button onClick={sync} disabled={syncing || !health?.dtr_configured}>
          {syncing ? "Syncing…" : "Sync own twins"}
        </button>
      </header>
      {error && <div className="error">{error}</div>}
      {report && report.issues.length > 0 && (
        <details className="issues">
          <summary>{report.issues.length} sync issue(s)</summary>
          <ul>
            {report.issues.map((issue, i) => (
              <li key={i}>
                <code>{issue.global_asset_id || "registry"}</code> {issue.semantic_id && <em>{issue.semantic_id}</em>}:{" "}
                {issue.message}
              </li>
            ))}
          </ul>
        </details>
      )}
      <main>
        {partId ? (
          <PartDetail id={partId} onNavigate={navigate} />
        ) : (
          <PartList key={refreshKey} onOpen={navigate} />
        )}
      </main>
    </div>
  );
}
