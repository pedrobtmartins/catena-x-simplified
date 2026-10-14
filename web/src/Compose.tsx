import { useEffect, useMemo, useState } from "react";
import { api, ApiError, SEVERITIES, severityLabel, TYPE_LABEL, type Health, type NotificationType, type Plan, type Severity } from "./api";
import { ChipGroup, ErrorAlert } from "./ui";

/** Link to the composer, pre-filled with candidate parts (and the notification it forwards). */
export function composeHref(type: NotificationType, items: string[], from?: number): string {
  const query = new URLSearchParams({ type, items: items.join(",") });
  if (from !== undefined) query.set("from", String(from));
  return `#/compose?${query}`;
}

export function parseCompose(query: string): { type: NotificationType; items: string[]; from: number | null } {
  const params = new URLSearchParams(query);
  return {
    type: params.get("type") === "investigation" ? "investigation" : "alert",
    items: (params.get("items") ?? "").split(",").filter(Boolean),
    from: params.get("from") ? Number(params.get("from")) : null,
  };
}

export function Compose({ query, health }: { query: string; health: Health | null }) {
  const initial = useMemo(() => parseCompose(query), [query]);
  const [selected, setSelected] = useState<Set<string>>(() => new Set(initial.items));
  const [severity, setSeverity] = useState<Severity>("MAJOR");
  const [description, setDescription] = useState("");
  const [responseBy, setResponseBy] = useState("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const alert = initial.type === "alert";
  const items = useMemo(() => initial.items.filter((i) => selected.has(i)), [initial.items, selected]);

  useEffect(() => {
    if (items.length === 0) {
      setPlan(null);
      return;
    }
    api.plan(initial.type, items).then(setPlan, (e: Error) => setError(e.message));
  }, [initial.type, items]);

  const recipients = plan ? Object.entries(plan.recipients) : [];
  const ready = items.length > 0 && description.trim().length > 0 && recipients.length > 0 && !plan?.unmatched.length;

  const toggle = (gid: string) => {
    const next = new Set(selected);
    if (next.has(gid)) next.delete(gid);
    else next.add(gid);
    setSelected(next);
  };

  const submit = async (send: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const created = await api.createNotifications({
        type: initial.type,
        affected_items: items,
        severity,
        description: description.trim(),
        expected_response_by: responseBy ? new Date(`${responseBy}T23:59:59`).toISOString() : null,
        forwarded_from: initial.from,
        send,
      });
      window.location.hash = created.length === 1 ? `#/notifications/${created[0].id}` : "#/notifications?box=outbound";
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <a href="#/notifications?box=outbound">Notifications</a>
        <span aria-hidden="true">/</span>
        <span>New {TYPE_LABEL[initial.type].toLowerCase()}</span>
      </nav>

      <div className="page-head">
        <h1>New {TYPE_LABEL[initial.type].toLowerCase()}</h1>
        <p>
          {alert
            ? "Tell your direct customers that parts you delivered are affected by a quality issue."
            : "Ask your direct suppliers to investigate parts they delivered to you."}{" "}
          One notification is created per {alert ? "customer" : "supplier"}, with only the parts that concern them.
          {initial.from !== null && (
            <>
              {" "}
              Forwarded from <a href={`#/notifications/${initial.from}`}>a received notification</a>.
            </>
          )}
        </p>
      </div>

      <div className="two-col">
        <div className="main-col">
          <section className="card" aria-labelledby="parts-title">
            <h2 id="parts-title">Affected parts</h2>
            <ul className="item-list">
              {initial.items.map((gid) => {
                const unmatched = plan?.unmatched.includes(gid) && selected.has(gid);
                return (
                  <li key={gid}>
                    <label className="check">
                      <input type="checkbox" checked={selected.has(gid)} onChange={() => toggle(gid)} />
                      <span className="cell-id">{gid}</span>
                    </label>
                    {unmatched && (
                      <span className="badge badge-error">No direct {alert ? "customer" : "supplier"} known</span>
                    )}
                  </li>
                );
              })}
              {initial.items.length === 0 && <li className="muted">No parts selected. Start from a part.</li>}
            </ul>
          </section>

          <section className="card form" aria-labelledby="details-title">
            <h2 id="details-title">Details</h2>
            <div className="field" style={{ maxWidth: "none" }}>
              <label id="severity-label">Severity</label>
              <ChipGroup<Severity>
                label="Severity"
                value={severity}
                onChange={setSeverity}
                options={SEVERITIES.map((s) => ({ label: severityLabel(s), value: s }))}
              />
            </div>
            <div className="field" style={{ maxWidth: "none" }}>
              <label htmlFor="description">Description</label>
              <textarea
                id="description"
                className="textarea"
                rows={5}
                maxLength={1000}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder={
                  alert ? "What is wrong, which batch or period, what customers should do…" : "What did you observe, since when…"
                }
              />
              <span className="sub">{description.length}/1000 · sent as the notification's information</span>
            </div>
            <div className="field">
              <label htmlFor="response-by">Response expected by (optional)</label>
              <input
                id="response-by"
                className="input"
                type="date"
                value={responseBy}
                onChange={(e) => setResponseBy(e.target.value)}
              />
            </div>
          </section>
        </div>

        <aside className="card" aria-labelledby="recipients-title">
          <h2 id="recipients-title">Recipients</h2>
          {recipients.length === 0 ? (
            <p className="muted" style={{ marginTop: 12 }}>
              {items.length === 0 ? "Select at least one part." : `No direct ${alert ? "customers" : "suppliers"} found.`}
            </p>
          ) : (
            <ul className="recipient-list">
              {recipients.map(([bpnl, ids]) => (
                <li key={bpnl}>
                  <span className="cell-mono">{bpnl}</span>
                  <span className="sub">
                    {ids.length} {ids.length === 1 ? "part" : "parts"}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <ErrorAlert error={error} />
          <div className="stack">
            <button
              type="button"
              className="btn btn-primary"
              disabled={!ready || busy || !health?.can_send_notifications}
              title={!health?.can_send_notifications ? "No EDC configured" : undefined}
              onClick={() => submit(true)}
            >
              {busy ? "Sending…" : `Create and send${recipients.length > 1 ? ` (${recipients.length})` : ""}`}
            </button>
            <button type="button" className="btn btn-secondary" disabled={!ready || busy} onClick={() => submit(false)}>
              Save as draft{recipients.length > 1 ? "s" : ""}
            </button>
            {!health?.can_send_notifications && (
              <span className="sub">No EDC configured: drafts can be saved, not sent.</span>
            )}
          </div>
        </aside>
      </div>
    </>
  );
}
