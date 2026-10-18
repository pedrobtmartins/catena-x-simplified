// Inbox and outbox of quality notifications, with open/all filters and the counts that need attention.
import { useEffect, useState } from "react";
import { api, formatDateTime, type NotificationPage, type NotificationSummary } from "./api";
import { ChipGroup, EmptyState, ErrorAlert, SeverityBadge, Skeleton, SkeletonRows, StatusBadge, TypeBadge } from "./ui";

const PAGE_SIZE = 50;

type Box = "inbound" | "outbound";

export function Notifications({ dataVersion }: { dataVersion: number }) {
  const [box, setBox] = useState<Box>(() => (window.location.hash.endsWith("?box=outbound") ? "outbound" : "inbound"));
  const [openOnly, setOpenOnly] = useState(true);
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<NotificationPage | null>(null);
  // undefined while loading, null if it could not be read.
  const [summary, setSummary] = useState<NotificationSummary | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.notificationSummary().then(setSummary, () => setSummary(null));
  }, [dataVersion]);

  useEffect(() => {
    api.notifications({ direction: box, openOnly, limit: PAGE_SIZE, offset }).then(
      (p) => {
        setPage(p);
        setError(null);
      },
      (e: Error) => setError(e.message),
    );
  }, [box, openOnly, offset, dataVersion]);

  return (
    <>
      <div className="page-head">
        <h1>Notifications</h1>
        <p>
          Quality alerts go to direct customers, investigations to direct suppliers. Each hop is its own notification;
          received ones can be forwarded to the next hop.
        </p>
      </div>

      <div className="stats">
        <div className="stat">
          <span className="overline">Inbox · new</span>
          <span className="stat-value">{summary === undefined ? <Skeleton width={36} height={28} /> : (summary?.inbound_new ?? "—")}</span>
          <span className="stat-note">Received, not yet acknowledged</span>
        </div>
        <div className="stat">
          <span className="overline">Inbox · open</span>
          <span className="stat-value">{summary === undefined ? <Skeleton width={36} height={28} /> : (summary?.inbound_open ?? "—")}</span>
          <span className="stat-note">Received from partners, not closed</span>
        </div>
        <div className="stat">
          <span className="overline">Outbox · open</span>
          <span className="stat-value">{summary === undefined ? <Skeleton width={36} height={28} /> : (summary?.outbound_open ?? "—")}</span>
          <span className="stat-note">Drafts and sent, not closed</span>
        </div>
      </div>

      <div className="filters">
        <ChipGroup<Box>
          label="Mailbox"
          value={box}
          onChange={(v) => {
            setBox(v);
            setOffset(0);
          }}
          options={[
            { label: "Inbox", value: "inbound" },
            { label: "Outbox", value: "outbound" },
          ]}
        />
        <ChipGroup<boolean>
          label="Status"
          value={openOnly}
          onChange={(v) => {
            setOpenOnly(v);
            setOffset(0);
          }}
          options={[
            { label: "Open", value: true },
            { label: "All", value: false },
          ]}
        />
      </div>

      <ErrorAlert error={error} />

      <div className="table-box">
        <table>
          <thead>
            <tr>
              <th scope="col">Notification</th>
              <th scope="col">{box === "inbound" ? "From" : "To"}</th>
              <th scope="col">Severity</th>
              <th scope="col">Status</th>
              <th scope="col">Affected</th>
              <th scope="col">Updated</th>
            </tr>
          </thead>
          <tbody>
            {page?.items.map((n) => (
              <tr key={n.id}>
                <td>
                  <a className="part-link" href={`#/notifications/${n.id}`}>
                    <strong className="clamp">{n.description || "No description"}</strong>
                    <span className="sub">
                      <TypeBadge type={n.type} />
                      {n.forwarded_from_id && <span className="tag-note">forwarded</span>}
                      {n.last_error && <span className="error-text tag-note">delivery failed</span>}
                    </span>
                  </a>
                </td>
                <td className="cell-mono">{n.partner_bpnl}</td>
                <td>
                  <SeverityBadge severity={n.severity} />
                </td>
                <td>
                  <StatusBadge status={n.status} />
                </td>
                <td>
                  {n.affected_items.length} {n.affected_items.length === 1 ? "part" : "parts"}
                </td>
                <td className="nowrap">{formatDateTime(n.updated_at)}</td>
              </tr>
            ))}
            {!page && !error && <SkeletonRows rows={4} cols={6} />}
            {page && page.items.length === 0 &&
              (box === "inbound" ? (
                <EmptyState cols={6} title={`No ${openOnly ? "open " : ""}notifications received`}>
                  <p>
                    Quality alerts from your suppliers and investigations from your customers arrive here, through your
                    connector. Each one can be answered and forwarded to the next hop.
                  </p>
                </EmptyState>
              ) : (
                <EmptyState cols={6} title={`No ${openOnly ? "open " : ""}notifications sent`}>
                  <p>
                    A notification starts from a part: open one in <a href="#/">Parts</a> and choose{" "}
                    <strong>Send quality alert</strong> for its customers or <strong>Start investigation</strong> for its
                    suppliers.
                  </p>
                </EmptyState>
              ))}
          </tbody>
        </table>
      </div>

      {page && page.total > PAGE_SIZE && (
        <div className="pager">
          <span className="muted">
            {offset + 1}–{Math.min(offset + PAGE_SIZE, page.total)} of {page.total}
          </span>
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
        </div>
      )}
    </>
  );
}
