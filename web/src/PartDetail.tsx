import { useEffect, useState } from "react";
import { api, formatDateTime, instanceId, parseSemanticId, type Part, type PartTree, type TreeNode } from "./api";
import { composeHref } from "./Compose";
import { CopyIcon, InfoIcon } from "./icons";
import { PartDataNotice } from "./DataChecks";
import { Skeleton } from "./ui";

function quantity(node: TreeNode): string | null {
  if (node.quantity === null) return null;
  const unit = node.unit?.replace(/^unit:/, "") ?? "";
  const n = Number.isInteger(node.quantity) ? node.quantity : node.quantity.toFixed(2);
  return `${n} ${unit}${unit === "piece" && node.quantity !== 1 ? "s" : ""}`.trim();
}

function NodeCard({ node, from, partnerName }: { node: TreeNode; from: string; partnerName?: string | null }) {
  const facts = [partnerName ?? node.business_partner, quantity(node), `from ${node.declared_in.join(" + ") || from}`]
    .filter(Boolean)
    .join(" · ");
  const content = (
    <>
      {node.part && <strong className="semibold">{node.part.name_at_manufacturer ?? "Unnamed part"}</strong>}
      <span className="node-id">{node.global_asset_id}</span>
      <span className="sub" title={partnerName ? node.business_partner ?? undefined : undefined}>
        {facts}
        {node.is_only_potential_parent && " · potential parent"}
      </span>
    </>
  );
  // Parts in the cache are navigable; partner twins not cached yet are drawn dashed.
  return node.part ? (
    <a className="node" href={`#/parts/${encodeURIComponent(node.global_asset_id)}`}>
      {content}
    </a>
  ) : (
    <div className="node">{content}</div>
  );
}

function Attributes({ part }: { part: Part }) {
  const rows: [string, string | null, boolean?][] = [
    ["Manufacturer", part.manufacturer_id, true],
    ["Part number", part.manufacturer_part_id, true],
    ["Customer part", [part.customer_part_id, part.name_at_customer].filter(Boolean).join(" · ") || null],
    [
      "Identifiers",
      Object.entries(part.local_identifiers)
        .map(([k, v]) => `${k}: ${v}`)
        .join(", ") || null,
      true,
    ],
    ["Produced", [part.production_date, part.country].filter(Boolean).join(" · ") || null],
    ["Sites", part.site_ids.join(", ") || null, true],
    [
      "Classification",
      part.classifications
        .map((c) => [c.standard, c.id].filter(Boolean).join(" · ") + (c.description ? ` (${c.description})` : ""))
        .join(", ") || null,
    ],
  ];
  return (
    <dl className="attrs">
      {rows.map(([label, value, mono]) => (
        <div key={label} className="contents">
          <dt>{label}</dt>
          <dd className={mono && value ? "cell-mono" : undefined}>{value ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

export function PartDetail({ id, dataVersion }: { id: string; dataVersion: number }) {
  const [tree, setTree] = useState<PartTree | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  // Partner names for the tree; the BPNL stays the fallback (and the tooltip).
  const [names, setNames] = useState<Record<string, string>>({});

  useEffect(() => {
    api.partners().then(
      (partners) =>
        setNames(Object.fromEntries(partners.filter((p) => p.name).map((p) => [p.bpnl, p.name as string]))),
      () => setNames({}),
    );
  }, [dataVersion]);

  useEffect(() => {
    setError(null);
    api.tree(id).then(setTree, (e: Error) => {
      setTree(null);
      setError(e.message);
    });
  }, [id, dataVersion]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard not available (e.g. insecure context): the ID stays selectable
    }
  };

  const part = tree?.part;
  const model = part ? parseSemanticId(part.semantic_id) : null;
  const serial = part ? instanceId(part.local_identifiers) : undefined;
  // Own part: investigate its supplier parts; partner part: investigate the part itself.
  const investigate = !tree
    ? []
    : tree.part.is_own
      ? tree.children.filter((n) => n.business_partner).map((n) => n.global_asset_id)
      : [tree.part.global_asset_id];
  const canAlert = Boolean(part?.is_own && tree?.parents.some((n) => n.business_partner));
  // Why an action is unavailable, said next to it rather than only in a tooltip.
  const unavailable = [
    investigate.length === 0 && "No supplier parts to investigate in this part's bill of material.",
    !canAlert && (part?.is_own ? "No direct customer known for this part, so no alert can be sent." : "Alerts are about own parts."),
  ].filter(Boolean) as string[];
  const partnerMissing = tree ? [...tree.parents, ...tree.children].some((n) => !n.part) : false;
  const sources = tree
    ? [
        model && { name: model.name, detail: part!.semantic_id.replace(/^urn:samm:/, "").replace(/#.*$/, "") },
        tree.children.some((n) => n.declared_in.includes("bom")) && {
          name: "SingleLevelBomAsBuilt",
          detail: `${tree.children.length} child${tree.children.length === 1 ? "" : "ren"}`,
        },
        tree.parents.some((n) => n.declared_in.includes("usage")) && {
          name: "SingleLevelUsageAsBuilt",
          detail: `${tree.parents.length} parent${tree.parents.length === 1 ? "" : "s"}`,
        },
      ].filter((s): s is { name: string; detail: string } => Boolean(s))
    : [];

  return (
    <>
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <a href="#/">Parts</a>
        <span aria-hidden="true">/</span>
        <span className="mono">{serial ?? id}</span>
      </nav>

      {error && (
        <div className="alert alert-error" role="alert">
          {error}
        </div>
      )}

      {!tree && !error && (
        <div className="detail-skeleton" aria-busy="true">
          <Skeleton width={220} />
          <Skeleton width="45%" height={36} />
          <Skeleton width={360} />
          <div className="card">
            <Skeleton width="100%" height={240} />
          </div>
        </div>
      )}

      {tree && part && model && (
        <>
          <div className="detail-head">
            <div className="detail-title">
              <div className="badges">
                {part.is_own && <span className="badge badge-own">Own part</span>}
                <span className="badge badge-outline">{part.kind === "batch" ? "Batch" : "Serialized"}</span>
                <span className={`badge ${model.major === 3 ? "badge-v3" : "badge-v4"}`}>
                  {model.name} {model.version}
                </span>
              </div>
              <h1>{part.name_at_manufacturer ?? "Unnamed part"}</h1>
              <div className="id-row">
                <code className="id-box">{part.global_asset_id}</code>
                <button type="button" className="icon-btn" aria-label="Copy Catena-X ID" onClick={copy}>
                  <CopyIcon />
                </button>
                <span className="sub" aria-live="polite">
                  {copied ? "Copied" : ""}
                </span>
              </div>
            </div>
            <div className="detail-actions">
            <div className="actions">
              {investigate.length > 0 ? (
                <a className="btn btn-secondary" href={composeHref("investigation", investigate)}>
                  Start investigation
                </a>
              ) : (
                <button type="button" className="btn btn-secondary" disabled title="No supplier parts to investigate">
                  Start investigation
                </button>
              )}
              {canAlert ? (
                <a className="btn btn-primary" href={composeHref("alert", [part.global_asset_id])}>
                  Send quality alert
                </a>
              ) : (
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled
                  title={part.is_own ? "No direct customer known for this part" : "Alerts are about own parts"}
                >
                  Send quality alert
                </button>
              )}
            </div>
            {unavailable.map((reason) => (
              <p key={reason} className="action-note">
                {reason}
              </p>
            ))}
            </div>
          </div>

          <PartDataNotice id={part.global_asset_id} dataVersion={dataVersion} />

          <section className="card tree-card" aria-labelledby="tree-title">
            <div className="card-head">
              <h2 id="tree-title">As-built, one level</h2>
              <span className="sub">
                Direct customers and suppliers only — deeper levels travel hop by hop through notifications.
              </span>
            </div>

            <div className="tree">
              <div className="tree-col parents">
                <span className="overline">Used in · customer</span>
                {tree.parents.length === 0 ? (
                  <span className="empty-node">No parent published</span>
                ) : (
                  tree.parents.map((node) => (
                    <div className="leaf" key={node.global_asset_id}>
                      <NodeCard node={node} from="usage" partnerName={node.business_partner ? names[node.business_partner] : null} />
                      <div className="leaf-line out" />
                    </div>
                  ))
                )}
              </div>

              <div className="tree-col focus">
                <span className="overline">This part</span>
                <div className="node-focus">
                  <strong>{part.name_at_manufacturer ?? "Unnamed part"}</strong>
                  <span className="mono small">
                    {[serial, part.manufacturer_part_id].filter(Boolean).join(" · ")}
                  </span>
                  <span className="light">
                    {[part.manufacturer_id, part.production_date && `produced ${part.production_date.slice(0, 10)}`]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </div>
              </div>

              <div className="tree-col children">
                <span className="overline">Built from · supplier</span>
                {tree.children.length === 0 ? (
                  <span className="empty-node indent">
                    No children published
                  </span>
                ) : (
                  <div className="branch">
                    <div className="branch-stub" />
                    {tree.children.length > 1 && <div className="branch-spine" />}
                    <div className="branch-items">
                      {tree.children.map((node) => (
                        <div className="leaf" key={node.global_asset_id}>
                          <div className="leaf-line" />
                          <NodeCard node={node} from="bom" partnerName={node.business_partner ? names[node.business_partner] : null} />
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {partnerMissing && (
              <div className="alert alert-info">
                <InfoIcon />
                Dashed cards are partner twins not in the cache yet; a partner sync reads them through the EDC (see Partners).
              </div>
            )}
          </section>

          <div className="grid-2">
            <section className="card" aria-labelledby="attr-title">
              <h2 id="attr-title">Part attributes</h2>
              <Attributes part={part} />
            </section>
            <section className="card" aria-labelledby="src-title">
              <h2 id="src-title">Source submodels</h2>
              <div className="source-list">
                {sources.map((s) => (
                  <div className="source" key={s.name}>
                    <strong className="semibold">{s.name}</strong>
                    <span className="cell-id">{s.detail}</span>
                  </div>
                ))}
              </div>
              <span className="sub">Last synced {formatDateTime(part.synced_at)} from the own Digital Twin Registry.</span>
            </section>
          </div>
        </>
      )}
    </>
  );
}
