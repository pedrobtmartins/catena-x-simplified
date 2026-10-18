// The part page's structure: everything under the part (own levels all the way down, other
// companies' parts as leaves grouped per supplier) as a diagram or a table, and where the part is
// used, path by path up to the products. A part declared in two places is marked: a serialized
// unit is in one place at a time.
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { api, type PartStructure as Structure, type StructureLink, type StructurePart, type WhereUsed } from "./api";
import { composeHref } from "./Compose";
import { ChipGroup, ErrorAlert, Skeleton } from "./ui";

type Tab = "structure" | "used";
type Mode = "diagram" | "table";

/** A row of the visible tree; `key` is the path of IDs from the root (unique even for a part
 * reached twice), with a "g:<supplier>" segment for a supplier group. */
type Row =
  | { type: "root" | "own" | "leaf"; key: string; depth: number; id: string; link: StructureLink | null; inGroup?: boolean }
  | { type: "group"; key: string; depth: number; supplier: string; members: StructureLink[] };

const COL = 238;
const WIDTH = { root: 230, own: 230, group: 200, leaf: 200 } as const;
const HEIGHT = { root: 58, own: 58, group: 44, leaf: 42 } as const;
const GAP = 12;
const TOP = 48;
const LEFT = 16;

function shortId(id: string): string {
  return id.replace(/^urn:uuid:([0-9a-fA-F]{8})-.*-[0-9a-fA-F]{7}([0-9a-fA-F]{5})$/, "urn:uuid:$1…$2");
}

/** Identifiers such as a VAN can be very long tokens: cut for a label, whole in a tooltip. */
function clip(text: string | null, max = 24): string {
  if (!text) return "";
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function quantity(link: StructureLink | null): string {
  if (!link || link.quantity === null) return "";
  const unit = (link.unit ?? "").replace(/^unit:/, "");
  return `${Number.isInteger(link.quantity) ? link.quantity : link.quantity.toFixed(2)} ${unit === "piece" && link.quantity !== 1 ? "pieces" : unit}`.trim();
}

function maker(part: StructurePart | undefined, link: StructureLink | null): string {
  return part?.manufacturer_name ?? part?.manufacturer_id ?? link?.business_partner ?? "Unknown supplier";
}

/** Parts declared both in an assembly and in one of its sub-assemblies, within this structure. */
function findings(links: StructureLink[]): Map<string, { assembly: string; sub: string }> {
  const parents = new Map<string, string[]>();
  for (const l of links) parents.set(l.child, [...(parents.get(l.child) ?? []), l.parent]);
  const ancestors = (id: string, seen = new Set<string>()): Set<string> => {
    for (const p of parents.get(id) ?? []) if (!seen.has(p)) ancestors(p, seen.add(p));
    return seen;
  };
  const out = new Map<string, { assembly: string; sub: string }>();
  for (const [child, ps] of parents)
    for (const a of ps) for (const b of ps) if (a !== b && ancestors(b).has(a)) out.set(child, { assembly: a, sub: b });
  return out;
}

function useStructure(id: string, dataVersion: number) {
  const [structure, setStructure] = useState<Structure | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setStructure(null);
    setError(null);
    api.structure(id).then(setStructure, (e: Error) => setError(e.message));
  }, [id, dataVersion]);
  return { structure, error };
}

function Diagram({
  rows,
  parts,
  flags,
  expanded,
  query,
  selected,
  canOpen,
  onActivate,
}: {
  rows: Row[];
  parts: Map<string, StructurePart>;
  flags: Map<string, unknown>;
  expanded: Set<string>;
  query: string;
  selected: string | null;
  canOpen: (row: Row) => boolean;
  onActivate: (row: Row) => void;
}) {
  const focus = useRef<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  // Leaves are stacked top to bottom; a parent sits at the middle of its children.
  const layout = useMemo(() => {
    const kids = new Map<string, Row[]>();
    for (const r of rows) {
      const parent = r.key.slice(0, r.key.lastIndexOf("/"));
      kids.set(parent, [...(kids.get(parent) ?? []), r]);
    }
    const pos = new Map<string, { x: number; y: number; h: number }>();
    let y = TOP;
    const place = (r: Row) => {
      const children = kids.get(r.key) ?? [];
      const h = HEIGHT[r.type];
      const x = LEFT + r.depth * COL;
      if (!children.length) {
        pos.set(r.key, { x, y, h });
        y += h + GAP;
        return;
      }
      children.forEach(place);
      const first = pos.get(children[0].key)!;
      const last = pos.get(children[children.length - 1].key)!;
      pos.set(r.key, { x, y: (first.y + first.h / 2 + last.y + last.h / 2) / 2 - h / 2, h });
    };
    if (rows.length) place(rows[0]);
    const depth = Math.max(0, ...rows.map((r) => r.depth));
    return { pos, width: LEFT + depth * COL + WIDTH.own + LEFT, height: y + 12, depth };
  }, [rows]);

  useEffect(() => {
    if (!focus.current) return;
    const el = box.current?.querySelector<HTMLElement>(`[data-key="${CSS.escape(focus.current)}"]`);
    el?.scrollIntoView({ block: "nearest", inline: "nearest" });
    el?.focus({ preventScroll: true });
    focus.current = null;
  });

  const matches = (r: Row) => rowMatches(r, parts, query);
  const activate = (r: Row) => {
    focus.current = r.key;
    onActivate(r);
  };

  return (
    <div className="ps-canvas-box" ref={box}>
      <div className="ps-canvas" style={{ width: layout.width, height: layout.height }}>
        {Array.from({ length: layout.depth + 1 }, (_, d) => (
          <span key={d} className="ps-col-label" style={{ left: LEFT + d * COL }}>
            {d === 0 ? "This part" : `Level ${d}`}
          </span>
        ))}
        <svg width={layout.width} height={layout.height} aria-hidden="true">
          {rows.slice(1).map((r) => {
            const parentKey = r.key.slice(0, r.key.lastIndexOf("/"));
            const parent = rows.find((x) => x.key === parentKey);
            const p = layout.pos.get(parentKey);
            const c = layout.pos.get(r.key);
            if (!parent || !p || !c) return null;
            const x1 = p.x + WIDTH[parent.type];
            const y1 = p.y + p.h / 2;
            const x2 = c.x;
            const y2 = c.y + c.h / 2;
            const mx = (x1 + x2) / 2;
            const own = r.type === "own";
            const flagged = r.type !== "group" && flags.has(r.id);
            return (
              <path
                key={r.key}
                d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`}
                className={`ps-edge${own ? " own" : ""}${flagged ? " flagged" : ""}${query && !matches(r) ? " dim" : ""}`}
              />
            );
          })}
        </svg>
        {rows.map((r) => {
          const p = layout.pos.get(r.key)!;
          const { title, meta } = rowLabel(r, parts);
          const expandable = canOpen(r);
          const flagged = r.type === "group" ? r.members.filter((m) => flags.has(m.child)).length : flags.has(r.id) ? 1 : 0;
          const classes = ["ps-node", r.type, r.type !== "group" && r.id === selected ? "selected" : "", query ? (matches(r) ? "hit" : "dim") : ""];
          return (
            <button
              key={r.key}
              type="button"
              data-key={r.key}
              className={classes.filter(Boolean).join(" ")}
              style={{ left: p.x, top: p.y, width: WIDTH[r.type], height: p.h }}
              aria-expanded={expandable ? expanded.has(r.key) : undefined}
              onClick={() => activate(r)}
            >
              <span className="ps-body">
                <span className="ps-title">{title}</span>
                <span className="ps-meta">{meta}</span>
              </span>
              {flagged > 0 && (
                <span className="ps-warn" title={flagged > 1 ? `${flagged} with a data check finding` : "Data check finding"}>
                  !
                </span>
              )}
              {r.type === "group" && <span className="ps-count">{r.members.length}</span>}
              {expandable && <span className="ps-chev" aria-hidden="true">{expanded.has(r.key) ? "‹" : "›"}</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function rowLabel(r: Row, parts: Map<string, StructurePart>): { title: string; meta: string } {
  if (r.type === "group") return { title: r.supplier, meta: "supplier parts" };
  const part = parts.get(r.id);
  if (part?.own) return { title: part.name ?? "Unnamed part", meta: [clip(part.serial), part.part_number].filter(Boolean).join(" · ") };
  if (part?.cached) return { title: part.name ?? shortId(r.id), meta: [part.serial, r.inGroup ? null : maker(part, r.link), quantity(r.link)].filter(Boolean).join(" · ") };
  return { title: shortId(r.id), meta: [r.inGroup ? null : maker(part, r.link), quantity(r.link)].filter(Boolean).join(" · ") };
}

function rowMatches(r: Row, parts: Map<string, StructurePart>, query: string): boolean {
  if (!query) return true;
  const text = (id: string) => {
    const p = parts.get(id);
    return [id, p?.name, p?.serial, p?.part_number, p?.manufacturer_name, p?.manufacturer_id].join(" ");
  };
  const hay = r.type === "group" ? [r.supplier, ...r.members.map((m) => text(m.child))].join(" ") : text(r.id);
  return hay.toLowerCase().includes(query.toLowerCase());
}

function Table({
  rows,
  parts,
  flags,
  expanded,
  query,
  selected,
  canOpen,
  onActivate,
}: {
  rows: Row[];
  parts: Map<string, StructurePart>;
  flags: Map<string, unknown>;
  expanded: Set<string>;
  query: string;
  selected: string | null;
  canOpen: (row: Row) => boolean;
  onActivate: (row: Row) => void;
}) {
  const parentName = (r: Row) => {
    const segments = r.key.split("/");
    const ids = segments.filter((s) => !s.startsWith("g:"));
    const parent = segments[segments.length - 1].startsWith("g:") ? ids[ids.length - 1] : ids[ids.length - 2];
    return parent ? (parts.get(parent)?.name ?? shortId(parent)) : "";
  };
  return (
    <div className="ps-table-box">
      <table className="ps-table">
        <thead>
          <tr>
            <th scope="col">Part</th>
            <th scope="col">In</th>
            <th scope="col">Supplier</th>
            <th scope="col">Qty</th>
            <th scope="col">Identifier</th>
            <th scope="col">State</th>
          </tr>
        </thead>
        <tbody>
          {rows
            .filter((r) => rowMatches(r, parts, query))
            .map((r) => {
              const part = r.type === "group" ? undefined : parts.get(r.id);
              const expandable = canOpen(r);
              const flagged = r.type === "group" ? r.members.some((m) => flags.has(m.child)) : flags.has(r.id);
              const onKey = (e: KeyboardEvent) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onActivate(r);
                }
              };
              return (
                <tr
                  key={r.key}
                  className={r.type !== "group" && r.id === selected ? "selected" : undefined}
                  tabIndex={0}
                  aria-expanded={expandable ? expanded.has(r.key) : undefined}
                  onClick={() => onActivate(r)}
                  onKeyDown={onKey}
                >
                  <td>
                    <span className="ps-tree-cell" style={{ paddingLeft: r.depth * 22 }}>
                      <span className="ps-chev" aria-hidden="true">
                        {expandable ? (expanded.has(r.key) ? "▾" : "▸") : ""}
                      </span>
                      {r.type === "group" ? (
                        <>
                          {r.supplier} <span className="badge badge-outline">{r.members.length}</span>
                        </>
                      ) : part?.own ? (
                        <strong className="semibold">{part.name ?? "Unnamed part"}</strong>
                      ) : (
                        <span className="mono" title={r.id}>
                          {part?.name ?? shortId(r.id)}
                        </span>
                      )}
                      {flagged && <span className="badge badge-warn">Data check</span>}
                    </span>
                  </td>
                  <td className="sub">{r.depth ? parentName(r) : ""}</td>
                  <td>{r.type === "group" ? r.supplier : part?.own ? <span className="sub">own</span> : maker(part, r.link)}</td>
                  <td>{r.type === "group" ? `${r.members.length} pieces` : quantity(r.link)}</td>
                  <td className="mono" title={part?.serial ?? undefined}>
                    {clip(part?.serial ?? null)}
                  </td>
                  <td>
                    {r.type === "group" || !part?.cached ? (
                      <span className="badge badge-outline">Not read yet</span>
                    ) : (
                      <span className="badge badge-own">Cached</span>
                    )}
                  </td>
                </tr>
              );
            })}
        </tbody>
      </table>
    </div>
  );
}

function Panel({
  id,
  rootId,
  parts,
  links,
  flags,
  onWhereUsed,
}: {
  id: string | null;
  rootId: string;
  parts: Map<string, StructurePart>;
  links: StructureLink[];
  flags: Map<string, { assembly: string; sub: string }>;
  onWhereUsed: (id: string) => void;
}) {
  if (!id) {
    return (
      <aside className="ps-panel">
        <h3>Select a part</h3>
        <p className="sub">
          Own levels open all the way down. Other companies' parts are grouped per supplier and stop at one level: their
          contents are theirs, and deeper levels travel hop by hop through notifications.
        </p>
      </aside>
    );
  }
  const part = parts.get(id);
  const link = links.find((l) => l.child === id) ?? null;
  const flag = flags.get(id);
  const name = (gid: string) => parts.get(gid)?.name ?? shortId(gid);
  const rows: [string, string][] = part?.own
    ? [
        ["Serial", part.serial ?? "—"],
        ["Part number", part.part_number ?? "—"],
        ["Contains", `${links.filter((l) => l.parent === id).length} parts`],
      ]
    : [
        ["Supplier", maker(part, link)],
        ["Catena-X ID", id],
        ["Quantity", quantity(link) || "—"],
        ["Part data", part?.cached ? [part.serial, part.part_number].filter(Boolean).join(" · ") || "Cached" : "Not read yet: a partner sync reads it through your EDC"],
      ];
  return (
    <aside className="ps-panel">
      <span className={`badge ${part?.own ? "badge-own" : "badge-outline"}`}>{part?.own ? "Own part" : "Supplier part"}</span>
      <h3>{part?.name ?? shortId(id)}</h3>
      <dl>
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt>{k}</dt>
            <dd className={k === "Catena-X ID" || k === "Serial" ? "mono" : undefined}>{v}</dd>
          </div>
        ))}
      </dl>
      {flag && (
        <div className="alert alert-warn">
          Declared in the bill of material of {name(flag.assembly)} and again in its sub-assembly {name(flag.sub)}.
        </div>
      )}
      <div className="actions">
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => onWhereUsed(id)}>
          Where used
        </button>
        {part?.cached && id !== rootId && (
          <a className="btn btn-secondary btn-sm" href={`#/parts/${encodeURIComponent(id)}`}>
            Open part
          </a>
        )}
        {!part?.own && (
          <a className="btn btn-primary btn-sm" href={composeHref("investigation", [id])}>
            Start investigation
          </a>
        )}
      </div>
    </aside>
  );
}

function WhereUsedView({
  target,
  rootId,
  choices,
  onChoose,
  dataVersion,
}: {
  target: string;
  rootId: string;
  choices: StructurePart[];
  onChoose: (id: string) => void;
  dataVersion: number;
}) {
  const [used, setUsed] = useState<WhereUsed | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setUsed(null);
    setError(null);
    api.whereUsed(target).then(setUsed, (e: Error) => setError(e.message));
  }, [target, dataVersion]);

  const parts = new Map((used?.parts ?? []).map((p) => [p.global_asset_id, p]));
  const products = used ? [...new Set(used.paths.map((p) => p[p.length - 1]))] : [];
  const part = parts.get(target);
  const label = (p: StructurePart) =>
    p.own ? `${p.name ?? "Unnamed part"} · ${clip(p.serial)}` : `${clip(maker(p, null), 32)} · ${shortId(p.global_asset_id)}`;
  return (
    <div className="ps-used">
      <label className="ps-pick">
        <strong>Where is this part used?</strong>
        <select className="input" value={target} onChange={(e) => onChoose(e.target.value)}>
          {choices.map((p) => (
            <option key={p.global_asset_id} value={p.global_asset_id}>
              {p.global_asset_id === rootId ? `This part · ${label(p)}` : label(p)}
            </option>
          ))}
        </select>
      </label>
      <ErrorAlert error={error} />
      {!used && !error && <Skeleton width="60%" height={44} />}
      {used && used.paths.length === 1 && used.paths[0].length === 1 && (
        <p>
          Nothing in your data contains this part: it is a top-level product here. Its customers are known only where a
          usage aspect names them.
        </p>
      )}
      {used && !(used.paths.length === 1 && used.paths[0].length === 1) && (
        <>
          <p>
            In <strong>{products.length === 1 ? "1 product" : `${products.length} products`}</strong>, through{" "}
            {used.paths.length === 1 ? "1 path" : <strong>{used.paths.length} paths</strong>}.
            {used.truncated && " Only the first paths are shown."}
          </p>
          {used.paths.length > 1 && products.length < used.paths.length && part?.kind !== "batch" && (
            <div className="alert alert-warn">
              A serialized unit is in one place at a time: {used.paths.length} paths mean it is declared more than once. The
              data checks list it.
            </div>
          )}
          <div className="ps-paths">
            {used.paths.map((path) => (
              <div className="ps-path" key={path.join(">")}>
                {path.map((gid, i) => {
                  const p = parts.get(gid);
                  const cls = i === 0 ? "start" : i === path.length - 1 ? "end" : p?.own ? "own" : "";
                  return (
                    <span key={gid + i} className="ps-step-wrap">
                      {i > 0 && (
                        <span className="ps-arrow" aria-hidden="true">
                          →
                        </span>
                      )}
                      {p?.cached ? (
                        <a className={`ps-step ${cls}`} href={`#/parts/${encodeURIComponent(gid)}`}>
                          <span className="ps-title">{p.name ?? shortId(gid)}</span>
                          <span className="ps-meta" title={p.serial ?? undefined}>
                            {p.serial ? clip(p.serial) : maker(p, null)}
                          </span>
                        </a>
                      ) : (
                        <span className={`ps-step ${cls}`}>
                          <span className="ps-title">{shortId(gid)}</span>
                          <span className="ps-meta">{p ? maker(p, null) : "not cached"}</span>
                        </span>
                      )}
                    </span>
                  );
                })}
              </div>
            ))}
          </div>
          <div className="actions">
            {part && !part.own && (
              <a className="btn btn-primary" href={composeHref("investigation", [target])}>
                Start investigation with {maker(part, null)}
              </a>
            )}
            {part?.own && (
              <a className="btn btn-secondary" href={composeHref("alert", [target])}>
                Send quality alert
              </a>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export function PartStructure({ id, dataVersion }: { id: string; dataVersion: number }) {
  const { structure, error } = useStructure(id, dataVersion);
  const [tab, setTab] = useState<Tab>("structure");
  const [mode, setMode] = useState<Mode>("diagram");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<string | null>(null);
  const [target, setTarget] = useState(id);

  const parts = useMemo(() => new Map((structure?.parts ?? []).map((p) => [p.global_asset_id, p])), [structure]);
  const kids = useMemo(() => {
    const m = new Map<string, StructureLink[]>();
    for (const l of structure?.links ?? []) m.set(l.parent, [...(m.get(l.parent) ?? []), l]);
    return m;
  }, [structure]);
  const flags = useMemo(() => findings(structure?.links ?? []), [structure]);

  // Own levels open; supplier groups closed. A part without contents opens on where-used.
  useEffect(() => {
    if (!structure) return;
    const open = new Set<string>();
    const walk = (gid: string, key: string, seen: Set<string>) => {
      open.add(key);
      for (const l of kids.get(gid) ?? [])
        if (parts.get(l.child)?.own && !seen.has(l.child)) walk(l.child, `${key}/${l.child}`, new Set(seen).add(l.child));
    };
    walk(structure.root, structure.root, new Set([structure.root]));
    setExpanded(open);
    setSelected(null);
    setTarget(id);
    setTab(structure.links.length ? "structure" : "used");
  }, [structure, kids, parts, id]);

  const rows = useMemo(() => {
    if (!structure) return [] as Row[];
    const out: Row[] = [];
    const walk = (gid: string, depth: number, link: StructureLink | null, key: string, seen: Set<string>) => {
      out.push({ type: depth === 0 ? "root" : "own", key, depth, id: gid, link });
      if (!expanded.has(key)) return;
      const children = kids.get(gid) ?? [];
      for (const l of children.filter((c) => parts.get(c.child)?.own))
        if (!seen.has(l.child)) walk(l.child, depth + 1, l, `${key}/${l.child}`, new Set(seen).add(l.child));
      const groups = new Map<string, StructureLink[]>();
      for (const l of children.filter((c) => !parts.get(c.child)?.own)) {
        const name = maker(parts.get(l.child), l);
        groups.set(name, [...(groups.get(name) ?? []), l]);
      }
      for (const [supplier, members] of [...groups].sort((a, b) => b[1].length - a[1].length)) {
        const gkey = `${key}/g:${encodeURIComponent(supplier)}`;
        if (members.length === 1) {
          out.push({ type: "leaf", key: gkey, depth: depth + 1, id: members[0].child, link: members[0] });
          continue;
        }
        out.push({ type: "group", key: gkey, depth: depth + 1, supplier, members });
        if (expanded.has(gkey))
          for (const m of members) out.push({ type: "leaf", key: `${gkey}/${m.child}`, depth: depth + 2, id: m.child, link: m, inGroup: true });
      }
    };
    walk(structure.root, 0, null, structure.root, new Set([structure.root]));
    return out;
  }, [structure, expanded, kids, parts]);

  const toggle = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const canOpen = (r: Row) => r.type === "group" || ((r.type === "own" || r.type === "root") && kids.has(r.id));
  const activate = (r: Row) => {
    if (r.type !== "group") setSelected(r.id);
    if (canOpen(r)) toggle(r.key);
  };
  const search = (q: string) => {
    setQuery(q);
    // Open the groups that hold a match, so it can be seen.
    if (q) {
      const add = rows.filter((r) => r.type === "group" && r.members.some((m) => rowMatches({ type: "leaf", key: "", depth: 0, id: m.child, link: m }, parts, q)));
      if (add.length) setExpanded((prev) => new Set([...prev, ...add.map((r) => r.key)]));
    }
  };
  const expandAll = () => {
    // Groups appear as their parents open: repeat until nothing new opens.
    const all = new Set(expanded);
    let grew = true;
    let guard = 0;
    while (grew && guard++ < 20) {
      grew = false;
      const walkRows: Row[] = [];
      const visit = (gid: string, depth: number, key: string, seen: Set<string>) => {
        walkRows.push({ type: depth ? "own" : "root", key, depth, id: gid, link: null });
        if (!all.has(key)) return;
        for (const l of kids.get(gid) ?? []) {
          if (parts.get(l.child)?.own) {
            if (!seen.has(l.child)) visit(l.child, depth + 1, `${key}/${l.child}`, new Set(seen).add(l.child));
          } else
            walkRows.push({ type: "group", key: `${key}/g:${encodeURIComponent(maker(parts.get(l.child), l))}`, depth: depth + 1, supplier: "", members: [] });
        }
      };
      if (structure) visit(structure.root, 0, structure.root, new Set([structure.root]));
      for (const r of walkRows)
        if (!all.has(r.key)) {
          all.add(r.key);
          grew = true;
        }
    }
    setExpanded(all);
  };
  const collapse = () => setExpanded(new Set([structure?.root ?? id]));
  const whereUsed = (gid: string) => {
    setTarget(gid);
    setTab("used");
  };

  return (
    <section className="card ps" aria-labelledby="structure-title">
      <div className="ps-head">
        <h2 id="structure-title">{tab === "structure" ? "Structure" : "Where used"}</h2>
        <div className="ps-tools">
          <ChipGroup<Tab>
            label="View"
            options={[
              { label: "Structure", value: "structure" },
              { label: "Where used", value: "used" },
            ]}
            value={tab}
            onChange={setTab}
          />
          {tab === "structure" && (
            <ChipGroup<Mode>
              label="Mode"
              options={[
                { label: "Diagram", value: "diagram" },
                { label: "Table", value: "table" },
              ]}
              value={mode}
              onChange={setMode}
            />
          )}
        </div>
      </div>
      <ErrorAlert error={error} />
      {!structure && !error && <Skeleton width="100%" height={260} />}
      {structure && tab === "structure" && (
        <>
          <div className="ps-toolbar">
            <label className="search ps-search">
              <input
                aria-label="Find a part in the structure"
                placeholder="Find a part: name, serial, ID or supplier"
                value={query}
                onChange={(e) => search(e.target.value)}
              />
            </label>
            <button type="button" className="btn btn-secondary btn-sm" onClick={expandAll}>
              Expand all
            </button>
            <button type="button" className="btn btn-secondary btn-sm" onClick={collapse}>
              Collapse
            </button>
          </div>
          <div className="ps-legend sub">
            <span>
              <svg width="30" height="8" aria-hidden="true">
                <path d="M0 4h30" className="ps-edge own" />
              </svg>{" "}
              inside your company (every level)
            </span>
            <span>
              <svg width="30" height="8" aria-hidden="true">
                <path d="M0 4h30" className="ps-edge" />
              </svg>{" "}
              to another company (one level)
            </span>
            <span>
              <span className="ps-warn">!</span> data check finding
            </span>
            {structure.truncated && <span className="badge badge-warn">Cut at {structure.parts.length} parts</span>}
          </div>
          <div className="ps-layout">
            {mode === "diagram" ? (
              <Diagram rows={rows} parts={parts} flags={flags} expanded={expanded} query={query} selected={selected} canOpen={canOpen} onActivate={activate} />
            ) : (
              <Table rows={rows} parts={parts} flags={flags} expanded={expanded} query={query} selected={selected} canOpen={canOpen} onActivate={activate} />
            )}
            <Panel id={selected} rootId={structure.root} parts={parts} links={structure.links} flags={flags} onWhereUsed={whereUsed} />
          </div>
        </>
      )}
      {structure && tab === "used" && (
        <WhereUsedView
          target={target}
          rootId={structure.root}
          choices={[...parts.values()]}
          onChoose={setTarget}
          dataVersion={dataVersion}
        />
      )}
    </section>
  );
}
