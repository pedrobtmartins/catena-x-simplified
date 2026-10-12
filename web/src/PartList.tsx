import { useEffect, useState } from "react";
import { api, aspectLabel, type PartPage } from "./api";

const PAGE_SIZE = 50;

export function PartList({ onOpen }: { onOpen: (id: string) => void }) {
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<PartPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => {
      api.parts({ search: search.trim() || undefined, limit: PAGE_SIZE, offset }).then(
        (p) => {
          setPage(p);
          setError(null);
        },
        (e: Error) => setError(e.message),
      );
    }, 250);
    return () => clearTimeout(timer);
  }, [search, offset]);

  return (
    <section>
      <div className="toolbar">
        <input
          type="search"
          placeholder="Search by ID, part number or name"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setOffset(0);
          }}
        />
        {page && <span className="muted">{page.total} parts</span>}
      </div>
      {error && <div className="error">{error}</div>}
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Manufacturer part ID</th>
            <th>Local identifiers</th>
            <th>Kind</th>
            <th>Aspect</th>
            <th>Catena-X ID</th>
          </tr>
        </thead>
        <tbody>
          {page?.items.map((part) => (
            <tr key={part.global_asset_id} className="clickable" onClick={() => onOpen(part.global_asset_id)}>
              <td>{part.name_at_manufacturer ?? "—"}</td>
              <td>{part.manufacturer_part_id ?? "—"}</td>
              <td>
                {Object.entries(part.local_identifiers)
                  .map(([k, v]) => `${k}: ${v}`)
                  .join(", ") || "—"}
              </td>
              <td>{part.kind}</td>
              <td>{aspectLabel(part.semantic_id)}</td>
              <td>
                <code>{part.global_asset_id}</code>
              </td>
            </tr>
          ))}
          {page && page.items.length === 0 && (
            <tr>
              <td colSpan={6} className="muted">
                No parts. Run a sync of your own twins.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {page && page.total > PAGE_SIZE && (
        <div className="pager">
          <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
            Previous
          </button>
          <span className="muted">
            {offset + 1}–{Math.min(offset + PAGE_SIZE, page.total)} of {page.total}
          </span>
          <button disabled={offset + PAGE_SIZE >= page.total} onClick={() => setOffset(offset + PAGE_SIZE)}>
            Next
          </button>
        </div>
      )}
    </section>
  );
}
