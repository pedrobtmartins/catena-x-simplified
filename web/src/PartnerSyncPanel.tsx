// A partner sync as it runs (partner by partner, twin by twin, polled from the backend) and the
// metrics of the run once it has finished.
import { formatTime, type Partner, type PartnerSyncProgress, type PartnerSyncState } from "./api";
import { CheckIcon, SyncIcon } from "./icons";

const STATE: Record<PartnerSyncState, { label: string; badge: string }> = {
  pending: { label: "Waiting", badge: "badge-outline" },
  running: { label: "Reading", badge: "badge-v4" },
  ok: { label: "Synced", badge: "badge-ok" },
  partial: { label: "Partial", badge: "badge-warn" },
  failed: { label: "Failed", badge: "badge-error" },
  no_connector: { label: "No connector", badge: "badge-warn" },
  backoff: { label: "Backed off", badge: "badge-outline" },
};

export function partnerSyncState(state: PartnerSyncState) {
  return STATE[state];
}

export function formatDuration(seconds: number): string {
  if (seconds < 10) return `${seconds.toFixed(1)} s`;
  const s = Math.round(seconds);
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  return m < 60 ? `${m} min ${s % 60} s` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

// Time left from the pace so far; only once there is a pace to go by.
function remaining(p: PartnerSyncProgress): number | null {
  // Twins skipped as up to date count as done at once: the pace is that of the twins read.
  const read = p.twins_done - p.twins_fresh;
  if (read < 3 || p.elapsed_seconds < 3 || p.twins_done >= p.linked_twins) return null;
  return ((p.linked_twins - p.twins_done) * p.elapsed_seconds) / read;
}

function PartnerName({ bpnl, names }: { bpnl: string; names: Map<string, string> }) {
  const name = names.get(bpnl);
  return name ? (
    <span className="part-link">
      <strong>{name}</strong>
      <span className="cell-id">{bpnl}</span>
    </span>
  ) : (
    <strong className="mono">{bpnl}</strong>
  );
}

function Bar({ done, total, label }: { done: number; total: number; label: string }) {
  const pct = total ? Math.round((done / total) * 100) : 100;
  return (
    <div className="sync-bar" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={total} aria-valuenow={done}>
      <span style={{ width: `${pct}%` }} />
    </div>
  );
}

function Counts({
  p,
}: {
  p: { twins_cached: number; twins_missing: number; twins_failed: number; twins_fresh: number };
}) {
  return (
    <span className="sync-counts">
      {p.twins_fresh > 0 && (
        <>
          <span className="dot" /> {p.twins_fresh} up to date
        </>
      )}
      <span className="dot ok" /> {p.twins_cached} cached
      <span className="dot warn" /> {p.twins_missing} not found
      <span className="dot error" /> {p.twins_failed} failed
    </span>
  );
}

/** The sync while it runs. ``progress`` is null (or the previous run) until the backend has started. */
export function SyncLive({ progress, names }: { progress: PartnerSyncProgress | null; names: Map<string, string> }) {
  const p = progress?.running ? progress : null;
  if (!p) {
    return (
      <section className="card sync-panel" aria-live="polite">
        <div className="sync-head">
          <h2>
            <SyncIcon className="spin" /> Starting partner sync…
          </h2>
        </div>
        <Bar done={0} total={1} label="Partner sync progress" />
      </section>
    );
  }
  const reading = p.partners.filter((row) => row.state === "running");
  const left = remaining(p);
  return (
    <section className="card sync-panel" aria-live="polite" aria-busy="true">
      <div className="sync-head">
        <h2>
          <SyncIcon className="spin" /> {p.full ? "Syncing partners" : "Syncing partners (recent twins skipped)"}
        </h2>
        <span className="sub">
          {p.partners_done} of {plural(p.partners_total, "partner")}
          {p.partners_running > 1 && ` (${p.partners_running} at once)`} · {p.twins_done} of {plural(p.linked_twins, "twin")} ·{" "}
          {formatDuration(p.elapsed_seconds)}
          {left !== null && ` · about ${formatDuration(left)} left`}
        </span>
      </div>
      <Bar done={p.twins_done} total={p.linked_twins} label="Partner sync progress" />
      <div className="sync-now">
        <ul className="sync-reading">
          {reading.length ? (
            reading.map((row) => (
              <li key={row.bpnl}>
                <span>
                  Reading <strong title={row.bpnl}>{names.get(row.bpnl) ?? row.bpnl}</strong> — twin{" "}
                  {Math.min(row.twins_done + 1, row.linked_twins)} of {row.linked_twins}
                </span>
                {row.current_twin && (
                  <span className="cell-id" title={row.current_twin}>
                    {row.current_twin}
                  </span>
                )}
              </li>
            ))
          ) : (
            <li className="muted">Between partners…</li>
          )}
        </ul>
        <Counts p={p} />
      </div>
      <ol className="sync-partners">
        {p.partners.map((row) => (
          <li key={row.bpnl} className={`sync-partner sync-${row.state}`}>
            <PartnerName bpnl={row.bpnl} names={names} />
            <Bar done={row.twins_done} total={row.linked_twins} label={`Progress of ${row.bpnl}`} />
            <span className="sub nowrap">
              {row.twins_done}/{row.linked_twins}
              {row.duration_seconds !== null && ` · ${formatDuration(row.duration_seconds)}`}
            </span>
            <span className={`badge ${STATE[row.state].badge}`}>
              {row.state === "ok" && <CheckIcon />}
              {STATE[row.state].label}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** What the summary shows: a finished run's progress, or a run from the history. */
export type SyncSummaryData = Pick<
  PartnerSyncProgress,
  | "full"
  | "elapsed_seconds"
  | "finished_at"
  | "error"
  | "partners_total"
  | "linked_twins"
  | "twins_cached"
  | "twins_fresh"
  | "twins_missing"
  | "twins_failed"
  | "removed_parts"
  | "partners"
> & { selection?: boolean };

/** The metrics of a finished run. ``onFullSync``: offered when twins read recently were skipped. */
export function SyncSummary({
  progress: p,
  names,
  onDismiss,
  onFullSync,
}: {
  progress: SyncSummaryData;
  names: Map<string, string>;
  onDismiss?: () => void;
  onFullSync?: () => void;
}) {
  const byState = (state: PartnerSyncState) => p.partners.filter((row) => row.state === state).length;
  const ok = byState("ok");
  const partial = byState("partial") + byState("no_connector");
  const failed = byState("failed");
  const backedOff = byState("backoff");
  const read = p.twins_cached + p.twins_missing + p.twins_failed;
  const pace = p.elapsed_seconds > 0 ? read / p.elapsed_seconds : 0;
  const resultNote = [
    ok && `${ok} synced`,
    partial && `${partial} partial`,
    failed && `${failed} failed`,
    backedOff && `${backedOff} backed off`,
  ]
    .filter(Boolean)
    .join(" · ");
  const hasFresh = p.partners.some((row) => row.twins_fresh > 0);
  // The twins this run set out to read: the linked ones, less those skipped as up to date.
  const toRead = p.linked_twins - p.twins_fresh;
  const hasIssues = p.partners.some((row) => row.message);
  const tone = failed ? "error" : partial || p.twins_missing ? "warn" : "ok";

  return (
    <section className={`card sync-panel sync-done sync-done-${tone}`} aria-label="Partner sync result">
      <div className="sync-head">
        <h2>
          {tone === "ok" && <CheckIcon />}
          {p.selection ? "Partner twins read" : "Partner sync finished"}
        </h2>
        <span className="sub">
          {formatDuration(p.elapsed_seconds)}
          {p.finished_at && ` · finished at ${formatTime(p.finished_at)}`}
          {!p.full && " · twins read recently skipped"}
        </span>
        {onDismiss && (
          <button type="button" className="btn btn-secondary btn-sm sync-dismiss" onClick={onDismiss}>
            Dismiss
          </button>
        )}
      </div>

      {p.error && <div className="alert alert-error">{p.error}</div>}

      <div className="stats sync-stats">
        <div className={`stat stat-${failed ? "error" : partial ? "warn" : "ok"}`}>
          <span className="overline">Partners</span>
          <span className="stat-value">{p.partners_total}</span>
          <span className="stat-note">{resultNote || "None to sync"}</span>
        </div>
        <div className="stat stat-ok">
          <span className="overline">Twins cached</span>
          <span className="stat-value">{p.twins_cached}</span>
          <span className="stat-note">
            {toRead === 0
              ? "Nothing to read"
              : `of ${toRead} ${p.full ? "linked" : "read"} · ${Math.round((p.twins_cached / toRead) * 100)}%`}
          </span>
        </div>
        {!p.full && (
          <div className="stat">
            <span className="overline">Up to date</span>
            <span className="stat-value">{p.twins_fresh}</span>
            <span className="stat-note">
              Read recently, skipped
              {onFullSync && p.twins_fresh > 0 && (
                <>
                  {" · "}
                  <button type="button" className="link-btn" onClick={onFullSync}>
                    Read them again
                  </button>
                </>
              )}
            </span>
          </div>
        )}
        <div className={`stat${p.twins_missing ? " stat-warn" : ""}`}>
          <span className="overline">Not found</span>
          <span className="stat-value">{p.twins_missing}</span>
          <span className="stat-note">No twin in the partner's registry</span>
        </div>
        <div className={`stat${p.twins_failed ? " stat-error" : ""}`}>
          <span className="overline">Failed</span>
          <span className="stat-value">{p.twins_failed}</span>
          <span className="stat-note">Lookup or submodel read failed</span>
        </div>
        <div className="stat">
          <span className="overline">Removed</span>
          <span className="stat-value">{p.removed_parts}</span>
          <span className="stat-note">Cached parts no longer linked</span>
        </div>
        <div className="stat">
          <span className="overline">Pace</span>
          <span className="stat-value">{read === 0 ? "—" : pace >= 10 ? Math.round(pace) : pace.toFixed(1)}</span>
          <span className="stat-note">twins read per second</span>
        </div>
      </div>

      {p.partners.length > 0 && (
        <div className="table-box">
          <table className="sync-table">
            <thead>
              <tr>
                <th scope="col">Partner</th>
                <th scope="col">Result</th>
                <th scope="col" className="num">Cached</th>
                {hasFresh && (
                  <th scope="col" className="num">
                    Up to date
                  </th>
                )}
                <th scope="col" className="num">Not found</th>
                <th scope="col" className="num">Failed</th>
                <th scope="col" className="num">Removed</th>
                <th scope="col" className="num">Time</th>
                {hasIssues && <th scope="col">First issue</th>}
              </tr>
            </thead>
            <tbody>
              {p.partners.map((row) => (
                <tr key={row.bpnl}>
                  <td>
                    <PartnerName bpnl={row.bpnl} names={names} />
                  </td>
                  <td>
                    <span className={`badge ${STATE[row.state].badge}`}>
                      {row.state === "ok" && <CheckIcon />}
                      {STATE[row.state].label}
                    </span>
                  </td>
                  <td className="num">
                    {row.twins_cached}/{row.linked_twins - row.twins_fresh}
                  </td>
                  {hasFresh && <td className="num">{row.twins_fresh}</td>}
                  <td className="num">{row.twins_missing}</td>
                  <td className="num">{row.twins_failed}</td>
                  <td className="num">{row.removed_parts}</td>
                  <td className="num nowrap">{row.duration_seconds !== null ? formatDuration(row.duration_seconds) : "—"}</td>
                  {hasIssues && (
                    <td className="sync-issue" title={row.message ?? undefined}>
                      {row.message ?? <span className="muted">—</span>}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function partnerNames(partners: Partner[] | null): Map<string, string> {
  return new Map((partners ?? []).flatMap((p) => (p.name ? [[p.bpnl, p.name] as [string, string]] : [])));
}
