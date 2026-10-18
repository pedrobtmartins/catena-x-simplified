// Sync history: the latest own-twin sync, the recent runs with their issues, the data checks and where the twins come from.
import { useEffect, useMemo, useState } from "react";
import { api, formatDateTime, formatTime, syncState, type Health, type SyncReport } from "./api";
import { CheckIcon } from "./icons";
import { DataChecksCard } from "./DataChecks";
import { Skeleton } from "./ui";

function duration(run: SyncReport): string | null {
  if (!run.finished_at) return null;
  const ms = new Date(run.finished_at).getTime() - new Date(run.started_at).getTime();
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

const STATE_LABEL = { ok: "Complete", warn: "Complete with issues", error: "Aborted" } as const;

function StateBadge({ run }: { run: SyncReport }) {
  const state = syncState(run);
  return (
    <span className={`badge badge-${state === "ok" ? "ok" : state === "warn" ? "warn" : "error"}`}>
      {state === "ok" && <CheckIcon />}
      {STATE_LABEL[state]}
    </span>
  );
}

const ASPECT_NAMES: Record<string, string> = {
  serial_part: "SerialPart",
  batch: "Batch",
  single_level_bom_as_built: "SingleLevelBomAsBuilt",
  single_level_usage_as_built: "SingleLevelUsageAsBuilt",
};

/** "io.catenax.serial_part:3.0.0" … → [{ name: "SerialPart", versions: "3.0.0 · 3.0.1 · 4.0.0 · 4.0.0 industry_core" }] */
function aspectSummary(keys: string[]): { name: string; versions: string }[] {
  const byName = new Map<string, { version: string; core: boolean }[]>();
  for (const key of keys) {
    const [namespace, version] = key.split(":");
    const core = namespace.includes(".industry_core.");
    const short = namespace.replace(/^io\.catenax\.(industry_core\.)?/, "");
    const name = ASPECT_NAMES[short] ?? short;
    byName.set(name, [...(byName.get(name) ?? []), { version, core }]);
  }
  return [...byName.entries()].map(([name, versions]) => ({
    name,
    versions: versions
      .sort((a, b) => Number(a.core) - Number(b.core) || a.version.localeCompare(b.version))
      .map((v) => (v.core ? `${v.version} industry_core` : v.version))
      .join(" · "),
  }));
}

export function SyncHistory({ health, dataVersion }: { health: Health | null; dataVersion: number }) {
  const [runs, setRuns] = useState<SyncReport[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.syncRuns(20).then(
      (page) => {
        setRuns(page.items);
        setError(null);
      },
      (e: Error) => setError(e.message),
    );
  }, [dataVersion]);

  const latest = runs?.[0];
  const aspects = useMemo(() => aspectSummary(health?.supported_aspects ?? []), [health]);

  return (
    <>
      <div className="page-head">
        <h1>Sync history</h1>
        <p>
          Each run reads every shell descriptor of your DTR and its supported submodels. Parts are only removed after
          a complete listing.
        </p>
      </div>

      {error && (
        <div className="alert alert-error" role="alert">
          {error}
        </div>
      )}

      <div className="two-col">
        <div className="main-col">
          <section className="card" aria-labelledby="latest-title">
            <div className="card-head center">
              <div className="stack-tight">
                <h2 id="latest-title">Latest run</h2>
                {latest && (
                  <span className="sub">
                    {formatDateTime(latest.started_at)}
                    {duration(latest) && ` · ${duration(latest)}`}
                  </span>
                )}
              </div>
              {latest && <StateBadge run={latest} />}
            </div>
            {latest ? (
              <div className="metrics">
                {[
                  [latest.twins, "Twins listed"],
                  [latest.parts, "Parts stored"],
                  [latest.relation_sets, "Relation sets"],
                  [latest.unsupported_submodels, "Unsupported submodels"],
                  [latest.removed_parts, "Parts removed"],
                ].map(([value, label]) => (
                  <div className="metric" key={label}>
                    <strong>{value}</strong>
                    <span className="sub">{label}</span>
                  </div>
                ))}
              </div>
            ) : runs ? (
              <p className="muted card-gap">No sync has run yet. Choose Sync own twins to start the first one.</p>
            ) : (
              !error && (
                <div className="metrics" aria-busy="true">
                  {[0, 1, 2, 3, 4].map((i) => (
                    <div className="metric" key={i}>
                      <Skeleton width={40} height={26} />
                      <Skeleton width="70%" />
                    </div>
                  ))}
                </div>
              )
            )}
          </section>

          {runs && runs.length > 0 && (
            <section className="card" aria-labelledby="runs-title">
              <h2 id="runs-title">Runs</h2>
              <ol className="timeline">
                {runs.map((run) => {
                  const state = syncState(run);
                  return (
                    <li className="run" key={run.id ?? run.started_at}>
                      <div className="run-rail">
                        <span className={`dot ${state}`} />
                        <span className="run-line" />
                      </div>
                      <div className="run-body">
                        <strong className="semibold">
                          {formatTime(run.started_at)} · {STATE_LABEL[state].toLowerCase()}
                        </strong>
                        <span className="text-2">
                          {run.twins} twins · {run.parts} parts · {run.relation_sets} relation sets ·{" "}
                          {run.issues.length} {run.issues.length === 1 ? "issue" : "issues"}
                          {run.removed_parts > 0 && ` · ${run.removed_parts} removed`}
                        </span>
                        {run.issues.map((issue, i) => (
                          <div className="issue" key={i}>
                            {(issue.global_asset_id || issue.semantic_id) && (
                              <code>
                                {[issue.global_asset_id, issue.semantic_id?.replace(/^urn:samm:/, "")]
                                  .filter(Boolean)
                                  .join(" · ")}
                              </code>
                            )}
                            <span>{issue.message}</span>
                          </div>
                        ))}
                      </div>
                    </li>
                  );
                })}
              </ol>
            </section>
          )}

          <DataChecksCard dataVersion={dataVersion} />
        </div>

        <aside className="card" aria-labelledby="cfg-title">
          <h2 id="cfg-title">Source</h2>
          <dl className="config">
            <div>
              <dt className="overline">Digital Twin Registry</dt>
              <dd className="cell-mono">{health?.dtr_url ?? (health?.dtr_configured ? "Configured" : "Not configured")}</dd>
            </div>
            <div>
              <dt className="overline">Schedule</dt>
              <dd>
                {health && health.sync_interval_seconds > 0
                  ? `Every ${Math.round(health.sync_interval_seconds / 60)} min`
                  : "Manual · periodic sync off"}
              </dd>
            </div>
            <div>
              <dt className="overline">Supported aspects</dt>
              <dd>
                <ul className="aspect-list">
                  {aspects.map((a) => (
                    <li key={a.name}>
                      <strong className="semibold">{a.name}</strong>
                      <span className="sub">{a.versions}</span>
                    </li>
                  ))}
                </ul>
              </dd>
            </div>
          </dl>
        </aside>
      </div>
    </>
  );
}
