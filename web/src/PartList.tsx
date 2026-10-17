import { useEffect, useMemo, useState } from "react";
import { api, localIdentifiers, parseSemanticId, shortId, type PartPage, type Stats } from "./api";
import { SearchIcon } from "./icons";
import { ChipGroup, EmptyState, Skeleton, SkeletonRows } from "./ui";

const PAGE_SIZE = 50;

type Kind = "serial" | "batch" | undefined;
type Major = 3 | 4 | undefined;

function versionSplit(stats: Stats): { v3: number; v4: number; other: number } {
  const split = { v3: 0, v4: 0, other: 0 };
  for (const [semanticId, count] of Object.entries(stats.own_parts_by_semantic_id)) {
    const major = parseSemanticId(semanticId).major;
    if (major === 3) split.v3 += count;
    else if (major === 4) split.v4 += count;
    else split.other += count;
  }
  return split;
}

function plural(n: number, one: string, many: string) {
  return `${n} ${n === 1 ? one : many}`;
}

export function PartList({ dataVersion }: { dataVersion: number }) {
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState<Kind>(undefined);
  const [major, setMajor] = useState<Major>(undefined);
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<PartPage | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.stats().then(setStats, () => setStats(null));
  }, [dataVersion]);

  useEffect(() => {
    const timer = setTimeout(() => {
      api.parts({ search: search.trim() || undefined, kind, aspectMajor: major, limit: PAGE_SIZE, offset }).then(
        (p) => {
          setPage(p);
          setError(null);
        },
        (e: Error) => setError(e.message),
      );
    }, 200);
    return () => clearTimeout(timer);
  }, [search, kind, major, offset, dataVersion]);

  const split = useMemo(() => (stats ? versionSplit(stats) : null), [stats]);
  const filtered = Boolean(search.trim() || kind || major);

  return (
    <>
      <div className="page-head">
        <h1>Parts</h1>
        <p>Twins from your Digital Twin Registry, cached locally. Aspect models v3 and v4 side by side.</p>
      </div>

      {!stats && !error && (
        <div className="stats" aria-busy="true">
          {[0, 1, 2, 3].map((i) => (
            <div className="stat" key={i}>
              <Skeleton width="45%" />
              <Skeleton width="30%" height={28} />
              <Skeleton width="70%" />
            </div>
          ))}
        </div>
      )}

      {stats && split && (
        <div className="stats">
          <div className="stat">
            <span className="overline">Own parts</span>
            <span className="stat-value">{stats.own_parts}</span>
            <span className="stat-note">
              {plural(stats.own_parts_by_kind.serial ?? 0, "serialized part", "serialized parts")} ·{" "}
              {plural(stats.own_parts_by_kind.batch ?? 0, "batch", "batches")}
            </span>
          </div>
          <div className="stat">
            <span className="overline">Supplier links</span>
            <span className="stat-value">{stats.supplier_links}</span>
            <span className="stat-note">From {plural(stats.suppliers, "supplier", "suppliers")}, via BoM</span>
          </div>
          <div className="stat">
            <span className="overline">Customer links</span>
            <span className="stat-value">{stats.customer_links}</span>
            <span className="stat-note">At {plural(stats.customers, "customer", "customers")}, via usage</span>
          </div>
          <div className="stat">
            <span className="overline">Aspect versions</span>
            <div className="split-bar" aria-hidden="true">
              <div className="v3-fill" style={{ flex: `${split.v3} 1 0` }} />
              <div className="v4-fill" style={{ flex: `${split.v4} 1 0` }} />
            </div>
            <div className="legend">
              <span>
                <span className="swatch v3-fill" />v3 · {split.v3}
              </span>
              <span>
                <span className="swatch v4-fill" />v4 · {split.v4}
              </span>
            </div>
          </div>
        </div>
      )}

      <div className="filters">
        <div className="field">
          <label htmlFor="part-search">Search</label>
          <div className="search">
            <SearchIcon />
            <input
              id="part-search"
              type="search"
              placeholder="Catena-X ID, part number or name"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setOffset(0);
              }}
            />
          </div>
        </div>
        <ChipGroup<Kind>
          label="Kind"
          value={kind}
          onChange={(v) => {
            setKind(v);
            setOffset(0);
          }}
          options={[
            { label: "All", value: undefined },
            { label: "Serial", value: "serial" },
            { label: "Batch", value: "batch" },
          ]}
        />
        <ChipGroup<Major>
          label="Aspect version"
          value={major}
          onChange={(v) => {
            setMajor(v);
            setOffset(0);
          }}
          options={[
            { label: "Any version", value: undefined },
            { label: "v3", value: 3 },
            { label: "v4", value: 4 },
          ]}
        />
      </div>

      {error && (
        <div className="alert alert-error" role="alert">
          {error}
        </div>
      )}

      <div className="table-box">
        <table>
          <thead>
            <tr>
              <th scope="col">Part</th>
              <th scope="col">Serial / batch</th>
              <th scope="col">Part number</th>
              <th scope="col">Aspect model</th>
              <th scope="col">Produced</th>
              <th scope="col">Links</th>
              <th scope="col">Catena-X ID</th>
            </tr>
          </thead>
          <tbody>
            {page?.items.map((part) => {
              const model = parseSemanticId(part.semantic_id);
              const customer = [part.name_at_customer, part.customer_part_id].filter(Boolean).join(" · ");
              return (
                <tr key={part.global_asset_id}>
                  <td>
                    <a className="part-link" href={`#/parts/${encodeURIComponent(part.global_asset_id)}`}>
                      <strong>{part.name_at_manufacturer ?? "Unnamed part"}</strong>
                      {customer && <span className="sub">{customer}</span>}
                    </a>
                  </td>
                  <td className="cell-mono">{localIdentifiers(part) || "—"}</td>
                  <td className="cell-mono">{part.manufacturer_part_id ?? "—"}</td>
                  <td>
                    <span className={`badge ${model.major === 3 ? "badge-v3" : "badge-v4"}`}>
                      {model.name} {model.version}
                    </span>
                  </td>
                  <td>{part.production_date?.slice(0, 10) ?? "—"}</td>
                  <td className="cell-links">
                    <span>
                      {part.parents_count} {part.parents_count === 1 ? "customer" : "customers"}
                    </span>
                    <span className="sub">
                      {part.children_count} {part.children_count === 1 ? "component" : "components"}
                    </span>
                  </td>
                  <td className="cell-id" title={part.global_asset_id}>
                    {shortId(part.global_asset_id)}
                  </td>
                </tr>
              );
            })}
            {!page && !error && <SkeletonRows rows={6} cols={7} />}
            {page && page.items.length === 0 &&
              (filtered ? (
                <EmptyState cols={7} title="No parts match these filters">
                  <p>Clear the search or choose another type or aspect version.</p>
                </EmptyState>
              ) : (
                <EmptyState cols={7} title="No parts yet">
                  <p>
                    Choose <strong>Sync own twins</strong> to read your parts from your Digital Twin Registry. If the
                    registry is not connected yet, start in <a href="#/setup">Setup</a>.
                  </p>
                </EmptyState>
              ))}
          </tbody>
        </table>
      </div>

      {page && (
        <div className="pager">
          <span className="muted">
            {page.total === 0
              ? "0 parts"
              : `${offset + 1}–${Math.min(offset + PAGE_SIZE, page.total)} of ${plural(page.total, "part", "parts")}`}
          </span>
          {page.total > PAGE_SIZE && (
            <>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                Previous
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={offset + PAGE_SIZE >= page.total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Next
              </button>
            </>
          )}
        </div>
      )}
    </>
  );
}
