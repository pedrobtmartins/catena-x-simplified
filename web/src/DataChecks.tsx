// Data checks on the own bills of material: a serialized unit can only be in one place.
import { useEffect, useState } from "react";
import { api, type DataChecks, type DataFinding, type PartRef } from "./api";
import { InfoIcon } from "./icons";
import { Skeleton } from "./ui";

function Ref({ part, current }: { part: PartRef; current?: string }) {
  const label = (
    <>
      {part.name ?? <span className="mono">{part.global_asset_id}</span>}
      {part.serial && (
        <>
          {" "}
          <span className="mono small ref-serial" title={part.serial}>
            {part.serial}
          </span>
        </>
      )}
    </>
  );
  if (part.global_asset_id === current) return <strong className="semibold">{label}</strong>;
  // Only parts in the cache have a page; a supplier part not read yet is shown by its ID.
  return part.name ? <a href={`#/parts/${encodeURIComponent(part.global_asset_id)}`}>{label}</a> : label;
}

function Supplier({ finding }: { finding: DataFinding }) {
  const who = finding.partner_name ?? finding.business_partner;
  return who ? <span className="muted"> from {who}</span> : null;
}

export function FindingText({ finding, current }: { finding: DataFinding; current?: string }) {
  const [first, second] = finding.parents;
  if (finding.kind === "two_levels") {
    return (
      <>
        <Ref part={finding.part} current={current} />
        <Supplier finding={finding} /> is declared in the bill of material of <Ref part={first} current={current} />{" "}
        and again in that of its sub-assembly <Ref part={second} current={current} />.
      </>
    );
  }
  return (
    <>
      <Ref part={finding.part} current={current} />
      <Supplier finding={finding} /> is declared in the bills of material of {finding.parents.length} own parts that
      do not contain one another:{" "}
      {finding.parents.map((p, i) => (
        <span key={p.global_asset_id}>
          {i > 0 && ", "}
          <Ref part={p} current={current} />
        </span>
      ))}
      .
    </>
  );
}

const KIND_LABEL: Record<DataFinding["kind"], string> = {
  two_levels: "Two levels",
  two_assemblies: "Two assemblies",
};

interface Group {
  key: string;
  kind: DataFinding["kind"];
  parents: PartRef[];
  findings: DataFinding[];
}

/** Findings that share the same assemblies have one cause: they are listed together. */
function groupFindings(findings: DataFinding[]): Group[] {
  const groups = new Map<string, Group>();
  for (const f of findings) {
    const key = `${f.kind}|${f.parents.map((p) => p.global_asset_id).join("|")}`;
    const group = groups.get(key) ?? { key, kind: f.kind, parents: f.parents, findings: [] };
    group.findings.push(f);
    groups.set(key, group);
  }
  return [...groups.values()].sort((a, b) => b.findings.length - a.findings.length);
}

function bySupplier(findings: DataFinding[]): string {
  const counts = new Map<string, number>();
  for (const f of findings) {
    const who = f.partner_name ?? f.business_partner ?? "unknown supplier";
    counts.set(who, (counts.get(who) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([who, n]) => `${who} (${n})`)
    .join(", ");
}

function GroupText({ group, current }: { group: Group; current?: string }) {
  const n = group.findings.length;
  const what = n === 1 ? "1 part is" : `${n} parts are`;
  const [first, second] = group.parents;
  if (group.kind === "two_levels") {
    return (
      <>
        {what} declared in the bill of material of <Ref part={first} current={current} /> and again in that of its
        sub-assembly <Ref part={second} current={current} />.
      </>
    );
  }
  return (
    <>
      {what} declared in the bills of material of {group.parents.length} own parts that do not contain one another:{" "}
      {group.parents.map((p, i) => (
        <span key={p.global_asset_id}>
          {i > 0 && ", "}
          <Ref part={p} current={current} />
        </span>
      ))}
      .
    </>
  );
}

function GroupParts({ group, current }: { group: Group; current?: string }) {
  return (
    <details className="finding-parts">
      <summary>{group.findings.length === 1 ? "Show the part" : `Show the ${group.findings.length} parts`}</summary>
      <ul>
        {group.findings.map((f) => (
          <li key={f.part.global_asset_id}>
            <Ref part={f.part} current={current} />
            <Supplier finding={f} />
          </li>
        ))}
      </ul>
    </details>
  );
}

/** Sync history: every finding in the cache, grouped by the assemblies involved. */
export function DataChecksCard({ dataVersion }: { dataVersion: number }) {
  const [checks, setChecks] = useState<DataChecks | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    api.dataChecks().then(setChecks, (e: Error) => setError(e.message));
  }, [dataVersion]);

  const groups = checks ? groupFindings(checks.findings) : [];
  return (
    <section className="card" aria-labelledby="checks-title">
      <div className="card-head center">
        <h2 id="checks-title">Data checks</h2>
        {checks && (
          <span className={`badge ${checks.total ? "badge-warn" : "badge-ok"}`}>
            {checks.total ? `${checks.total} to review` : "No findings"}
          </span>
        )}
      </div>
      <p className="muted card-gap">
        Contradictions in your own bills of material, found in the local cache. A serialized unit is in one place at a
        time, so a part declared twice points to a twin to correct where it is published.
      </p>
      {error && <p className="error-text card-gap">{error}</p>}
      {!checks && !error && (
        <div className="stack-tight card-gap" aria-busy="true">
          <Skeleton width="80%" />
          <Skeleton width="65%" />
        </div>
      )}
      {groups.length > 0 && (
        <ul className="findings">
          {groups.map((group) => (
            <li key={group.key}>
              <span className="badge badge-warn">{KIND_LABEL[group.kind]}</span>
              <div className="stack-tight">
                <span>
                  <GroupText group={group} />
                </span>
                <span className="sub">By supplier: {bySupplier(group.findings)}</span>
                <GroupParts group={group} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Part page: the findings this part is part of, if any. */
export function PartDataNotice({ id, dataVersion }: { id: string; dataVersion: number }) {
  const [findings, setFindings] = useState<DataFinding[]>([]);

  useEffect(() => {
    api.dataChecks(id).then(
      (c) => setFindings(c.findings),
      () => setFindings([]),
    );
  }, [id, dataVersion]);

  if (findings.length === 0) return null;
  return (
    <div className="alert alert-warn" role="status">
      <InfoIcon />
      <div className="stack-tight">
        <strong className="semibold">Data check</strong>
        {groupFindings(findings).map((group) =>
          group.findings.length === 1 ? (
            <p key={group.key}>
              <FindingText finding={group.findings[0]} current={id} />
            </p>
          ) : (
            <div key={group.key} className="stack-tight">
              <p>
                <GroupText group={group} current={id} />
              </p>
              <GroupParts group={group} current={id} />
            </div>
          ),
        )}
        <a href="#/sync">All data checks</a>
      </div>
    </div>
  );
}
