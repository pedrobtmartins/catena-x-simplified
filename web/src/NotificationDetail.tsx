import { useEffect, useState } from "react";
import {
  api,
  ApiError,
  formatDateTime,
  STATUS_LABEL,
  TYPE_LABEL,
  type ForwardPlan,
  type Health,
  type Notification,
  type NotificationDetail as Detail,
  type Status,
} from "./api";
import { composeHref } from "./Compose";
import { CheckIcon, InfoIcon } from "./icons";
import { ErrorAlert, SeverityBadge, StatusBadge, TypeBadge } from "./ui";

// The KIT's state model as a path; ACCEPTED and DECLINED share one step.
const STEPS: { label: string; statuses: Status[] }[] = [
  { label: "Draft", statuses: ["CREATED", "SENT"] },
  { label: "Received", statuses: ["RECEIVED"] },
  { label: "Acknowledged", statuses: ["ACKNOWLEDGED"] },
  { label: "Accepted / declined", statuses: ["ACCEPTED", "DECLINED"] },
  { label: "Closed", statuses: ["CLOSED"] },
];

function Progress({ notification }: { notification: Detail }) {
  const first = notification.direction === "inbound" ? "Sent" : "Draft";
  // A notification can be closed from any step; skipped steps stay grey.
  const reached = new Set<Status>(["CREATED"]);
  for (const m of notification.messages) if (m.status) reached.add(m.status);
  if (notification.messages.length > 0) reached.add("RECEIVED");
  const current = STEPS.findIndex((s) => s.statuses.includes(notification.status));
  return (
    <ol className="progress" aria-label="Status">
      {STEPS.map((step, i) => {
        const done = i < current && step.statuses.some((s) => reached.has(s));
        const state = i === current ? "current" : done ? "done" : "todo";
        const decided = i === 3 && (notification.status === "ACCEPTED" || notification.status === "DECLINED");
        return (
          <li key={step.label} className={`step ${state}`} aria-current={i === current ? "step" : undefined}>
            <span className="step-dot">{state === "done" && <CheckIcon size={12} />}</span>
            <span>{decided ? STATUS_LABEL[notification.status] : i === 0 ? first : step.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

const ACTION_LABEL: Record<string, string> = {
  send: "Send",
  ACKNOWLEDGED: "Acknowledge",
  ACCEPTED: "Accept",
  DECLINED: "Decline",
  CLOSED: "Close",
};

function Actions({ notification, health, onChange }: { notification: Detail; health: Health | null; onChange: (n: Notification) => void }) {
  const [information, setInformation] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isDraft = notification.status === "CREATED";
  const decision = notification.actions.some((a) => a === "ACCEPTED" || a === "DECLINED");
  const closing = notification.actions.includes("CLOSED") && !isDraft;
  const offline = !health?.can_send_notifications;

  if (notification.actions.length === 0) {
    return (
      <p className="muted">
        {notification.status === "CLOSED"
          ? "Closed — nothing left to do."
          : notification.direction === "outbound"
            ? "Waiting for the partner's answer."
            : "Waiting for the initiator to close it."}
      </p>
    );
  }

  const run = async (action: string) => {
    setBusy(action);
    setError(null);
    try {
      const updated =
        action === "send"
          ? await api.sendNotification(notification.id)
          : await api.changeStatus(notification.id, action as Status, information.trim() || undefined);
      setInformation("");
      onChange(updated);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      onChange(notification); // reload: a failed send records its error
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="action-box">
      {(decision || closing) && (
        <div className="field wide">
          <label htmlFor="information">
            {decision ? "Answer to the initiator (optional)" : "Closing note (optional)"}
          </label>
          <textarea
            id="information"
            className="textarea"
            maxLength={1000}
            rows={3}
            value={information}
            onChange={(e) => setInformation(e.target.value)}
            placeholder={decision ? "Findings, counter-measures, recommendations…" : "Why it is closed"}
          />
        </div>
      )}
      <ErrorAlert error={error} />
      <div className="actions">
        {notification.actions.map((action) => {
          const local = isDraft && action === "CLOSED"; // discarding a draft is not sent
          const label = local ? "Discard draft" : ACTION_LABEL[action];
          const primary = action === "send" || action === "ACKNOWLEDGED" || action === "ACCEPTED";
          return (
            <button
              key={action}
              type="button"
              className={`btn ${primary ? "btn-primary" : action === "DECLINED" ? "btn-danger" : "btn-secondary"}`}
              disabled={busy !== null || (offline && !local)}
              title={offline && !local ? "No EDC configured" : undefined}
              onClick={() => run(action)}
            >
              {busy === action ? "…" : label}
            </button>
          );
        })}
      </div>
      {!isDraft && (
        <span className="sub">Sent to {notification.partner_bpnl} as an update; applied here once they accept it.</span>
      )}
    </div>
  );
}

function Forwarding({ notification }: { notification: Detail }) {
  const [plan, setPlan] = useState<ForwardPlan | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (notification.direction !== "inbound") return;
    api.forwardPlan(notification.id).then(setPlan, (e: Error) => setError(e.message));
  }, [notification.id, notification.direction]);

  if (notification.direction === "outbound") {
    return notification.forwarded_from ? (
      <section className="card" aria-labelledby="fwd-title">
        <h2 id="fwd-title">Previous hop</h2>
        <p className="card-gap">
          Forwarded from{" "}
          <a href={`#/notifications/${notification.forwarded_from.id}`}>
            {TYPE_LABEL[notification.forwarded_from.type].toLowerCase()} received from{" "}
            {notification.forwarded_from.partner_bpnl}
          </a>
          .
        </p>
      </section>
    ) : null;
  }

  const recipients = plan ? Object.entries(plan.recipients) : [];
  const next = notification.type === "alert" ? "customers" : "suppliers";
  const items = recipients.flatMap(([, ids]) => ids);
  return (
    <section className="card" aria-labelledby="fwd-title">
      <div className="card-head">
        <h2 id="fwd-title">Next hop</h2>
        <span className="sub">
          {notification.type === "alert"
            ? "Own parts that contain the affected parts → their direct customers"
            : "Supplier parts in the affected own parts → their direct suppliers"}
        </span>
      </div>
      <ErrorAlert error={error} />
      {plan && (
        <div className="hop">
          <div>
            <span className="overline">Affected own parts</span>
            {plan.own_parts.length === 0 ? (
              <p className="muted">None of the affected parts is in your own as-built data.</p>
            ) : (
              <ul className="id-list">
                {plan.own_parts.map((gid) => (
                  <li key={gid}>
                    <a className="cell-id" href={`#/parts/${encodeURIComponent(gid)}`}>
                      {gid}
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <span className="overline">Direct {next}</span>
            {recipients.length === 0 ? (
              <p className="muted">No direct {next} found for them — the notification stops here.</p>
            ) : (
              <ul className="id-list">
                {recipients.map(([bpnl, ids]) => (
                  <li key={bpnl}>
                    <span className="cell-mono">{bpnl}</span>
                    <span className="sub">
                      {" "}
                      · {ids.length} {ids.length === 1 ? "part" : "parts"}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
      {notification.forwarded_to.length > 0 && (
        <div className="forwarded">
          <span className="overline">Already forwarded</span>
          {notification.forwarded_to.map((n) => (
            <a key={n.id} href={`#/notifications/${n.id}`} className="forward-link">
              <span className="cell-mono">{n.partner_bpnl}</span>
              <StatusBadge status={n.status} />
            </a>
          ))}
        </div>
      )}
      {items.length > 0 && (
        <div className="actions">
          <a
            className="btn btn-primary"
            href={composeHref(notification.type, items, notification.id)}
          >
            Forward as {TYPE_LABEL[notification.type].toLowerCase()}
          </a>
        </div>
      )}
    </section>
  );
}

export function NotificationDetail({ id, health }: { id: number; health: Health | null }) {
  const [notification, setNotification] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    api.notification(id).then(
      (n) => {
        setNotification(n);
        setError(null);
      },
      (e: Error) => setError(e.message),
    );
  }, [id, version]);

  const n = notification;
  const inbound = n?.direction === "inbound";

  return (
    <>
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <a href={`#/notifications${inbound || !n ? "" : "?box=outbound"}`}>Notifications</a>
        <span aria-hidden="true">/</span>
        <span>{n ? `${inbound ? "Received" : "Sent"} ${TYPE_LABEL[n.type].toLowerCase()}` : id}</span>
      </nav>

      <ErrorAlert error={error} />

      {n && (
        <>
          <div className="detail-head">
            <div className="detail-title">
              <div className="badges">
                <TypeBadge type={n.type} />
                <SeverityBadge severity={n.severity} />
                <StatusBadge status={n.status} />
              </div>
              <h1 className="notification-title">
                {TYPE_LABEL[n.type]} {inbound ? "from" : "to"} <span className="mono">{n.partner_bpnl}</span>
              </h1>
              {n.description && <p className="description">{n.description}</p>}
              <span className="sub">
                Created {formatDateTime(n.created_at)}
                {n.expected_response_by && ` · response expected by ${formatDateTime(n.expected_response_by)}`}
                {n.api_version && ` · Notification API ${n.api_version}`}
              </span>
            </div>
          </div>

          {n.last_error && (
            <div className="alert alert-error" role="alert">
              Last delivery failed: {n.last_error}
            </div>
          )}

          <section className="card" aria-labelledby="status-title">
            <div className="card-head">
              <h2 id="status-title">Status</h2>
              <span className="sub">
                {inbound
                  ? "You acknowledge, then accept or decline; the initiator closes."
                  : "The receiver acknowledges, accepts or declines; you close."}
              </span>
            </div>
            <Progress notification={n} />
            <Actions notification={n} health={health} onChange={() => setVersion((v) => v + 1)} />
          </section>

          <Forwarding notification={n} />

          <div className="grid-2">
            <section className="card" aria-labelledby="items-title">
              <h2 id="items-title">
                Affected parts <span className="muted">({n.items.length})</span>
              </h2>
              <ul className="item-list">
                {n.items.map(({ global_asset_id, part }) => (
                  <li key={global_asset_id}>
                    {part ? (
                      <a className="part-link" href={`#/parts/${encodeURIComponent(global_asset_id)}`}>
                        <strong>{part.name_at_manufacturer ?? "Unnamed part"}</strong>
                        <span className="cell-id">{global_asset_id}</span>
                      </a>
                    ) : (
                      <div className="part-link">
                        <span className="cell-id">{global_asset_id}</span>
                        <span className="sub">Not in the local cache</span>
                      </div>
                    )}
                    {part?.is_own && <span className="badge badge-own">Own part</span>}
                  </li>
                ))}
                {n.items.length === 0 && <li className="muted">No affected parts listed.</li>}
              </ul>
            </section>

            <section className="card" aria-labelledby="log-title">
              <h2 id="log-title">Messages</h2>
              {n.messages.length === 0 ? (
                <p className="muted card-gap">
                  <InfoIcon /> Not sent yet.
                </p>
              ) : (
                <ol className="timeline">
                  {n.messages.map((m) => (
                    <li className="run" key={m.message_id}>
                      <div className="run-rail">
                        <span className={`dot ${m.direction === "inbound" ? "in" : "out"}`} />
                        <span className="run-line" />
                      </div>
                      <div className="run-body">
                        <strong className="semibold">
                          {m.direction === "inbound" ? `From ${n.partner_bpnl}` : `To ${n.partner_bpnl}`} ·{" "}
                          {m.operation === "receive" ? "new notification" : m.status && STATUS_LABEL[m.status].toLowerCase()}
                        </strong>
                        <span className="sub">{formatDateTime(m.at)}</span>
                        {m.information && <p className="quote">{m.information}</p>}
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </div>
        </>
      )}
    </>
  );
}
