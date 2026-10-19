// Connectivity checks of a partner's connector: last result badge and the expandable panel. The
// connector's status comes from discovery, the registry offer and the EDR access; the quality
// notification offers are a separate use case, shown apart, and never make a connector degraded.
import { useEffect, useState } from "react";
import {
  api,
  ApiError,
  formatDateTime,
  type CheckLevel,
  type CheckStatus,
  type Partner,
  type PartnerCheck,
  type PartnerCheckStep,
} from "./api";
import { CheckIcon } from "./icons";
import { ErrorAlert } from "./ui";

export const STATUS: Record<CheckStatus, { label: string; badge: string; title?: string }> = {
  healthy: { label: "Healthy", badge: "badge-ok" },
  degraded: { label: "Degraded", badge: "badge-warn" },
  skipped: {
    label: "Skipped",
    badge: "badge-outline",
    title: "The partner answered, but nothing was checked through an EDC (development mode)",
  },
  failed: { label: "Failed", badge: "badge-error" },
};

const STEP: Record<PartnerCheckStep["status"], { label: string; badge: string }> = {
  ok: { label: "OK", badge: "badge-ok" },
  warn: { label: "Warning", badge: "badge-warn" },
  failed: { label: "Failed", badge: "badge-error" },
  skipped: { label: "Skipped", badge: "badge-outline" },
};

export const LEVELS: { level: CheckLevel; label: string; hint: string }[] = [
  { level: "discovery", label: "Discover", hint: "Connector discovery only (read-only)" },
  { level: "catalog", label: "Catalog", hint: "Registry and notification offers in the catalog (read-only)" },
  {
    level: "full",
    label: "Full EDR",
    hint: "Negotiates for the registry and reads it — creates contract and transfer state",
  },
];

export const FULL_CHECK_WARNING =
  "A full check negotiates a contract and opens a transfer process in your connector and the partner's. Continue?";

const isNotification = (step: PartnerCheckStep) => step.key.startsWith("notification:");

const NOTIFICATIONS: Record<PartnerCheck["notifications"], { label: string; badge: string }> = {
  ready: { label: "Notifications ready", badge: "badge-ok" },
  incomplete: { label: "Notifications incomplete", badge: "badge-warn" },
  unchecked: { label: "Notifications not checked", badge: "badge-outline" },
};

/** A plain-text report of a check for the partner's connector team, with UTC timestamps so
 * they can find the calls in their logs. */
export function partnerReport(check: PartnerCheck, partner: Partner, ownBpnl: string | null): string {
  const outcome =
    check.status === "failed"
      ? "failed"
      : check.status === "degraded"
        ? "showed problems"
        : "worked, but some quality notification offers are missing";
  const line = (step: PartnerCheckStep) => `- ${step.name}: ${STEP[step.status].label}${step.detail ? ` — ${step.detail}` : ""}`;
  const notifications = check.steps.filter(isNotification);
  const lines = [
    `Hello${partner.name ? ` ${partner.name}` : ""},`,
    "",
    `A connectivity check from our connector to yours ${outcome}. Could you have a look on your side?`,
    "",
    `From (our BPNL):     ${ownBpnl ?? "—"}`,
    `To (your BPNL):      ${partner.bpnl}`,
    `Connector address:   ${check.connector_address ?? "none set"}`,
    `Check:               ${check.level} (#${check.id})`,
    `Started:             ${utc(check.started_at)}`,
    `Finished:            ${utc(check.finished_at)}`,
    "",
    "Connector:",
    ...check.steps.filter((s) => !isNotification(s)).map(line),
    "",
    ...(notifications.length ? ["Quality notification offers:", ...notifications.map(line), ""] : []),
    "Thank you.",
  ];
  return lines.join("\n");
}

/** "2026-10-16T09:17:51.284086Z" → "2026-10-16 09:17:51 UTC" */
function utc(iso: string): string {
  return new Date(iso).toISOString().replace("T", " ").replace(/\.\d+Z$/, " UTC");
}

function CopyReport({ check, partner, ownBpnl }: { check: PartnerCheck; partner: Partner; ownBpnl: string | null }) {
  const [copied, setCopied] = useState<"ok" | "failed" | null>(null);
  const text = partnerReport(check, partner, ownBpnl);

  useEffect(() => setCopied(null), [check.id]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied("ok");
    } catch {
      setCopied("failed");
    }
  };

  return (
    <>
      <button type="button" className="btn btn-secondary" onClick={copy}>
        {copied === "ok" ? "Copied" : "Copy report for partner"}
      </button>
      {copied === "failed" && (
        <div className="alert alert-error" role="alert">
          The browser did not allow copying. Select the text below and copy it yourself.
          <pre className="request-text">{text}</pre>
        </div>
      )}
    </>
  );
}

export function HealthBadge({ check }: { check: PartnerCheck | null }) {
  if (!check) return <span className="muted">Not checked</span>;
  const status = STATUS[check.status];
  return (
    <div className="part-link">
      <span className={`badge ${status.badge}`} title={status.title}>
        {check.status === "healthy" && <CheckIcon />}
        {status.label}
      </span>
      <span className="sub">
        {check.level} · {formatDateTime(check.finished_at)}
        {check.notifications === "incomplete" && " · notifications incomplete"}
      </span>
    </div>
  );
}

function StepList({ steps }: { steps: PartnerCheckStep[] }) {
  return (
    <ul className="check-steps">
      {steps.map((step) => (
        <li key={step.key}>
          <span className={`badge ${STEP[step.status].badge}`}>{STEP[step.status].label}</span>
          <strong>{step.name}</strong>
          <span className="check-detail">{step.detail}</span>
        </li>
      ))}
    </ul>
  );
}

function Steps({ check }: { check: PartnerCheck }) {
  const core = check.steps.filter((s) => !isNotification(s));
  const notifications = check.steps.filter(isNotification);
  const status = STATUS[check.status];
  return (
    <div className="check-groups">
      <div className="check-group">
        <p className="check-group-head">
          <strong>Connector</strong> <span className={`badge ${status.badge}`}>{status.label}</span>
          <span className="sub">discovery, registry offer and EDR access</span>
        </p>
        <StepList steps={core} />
      </div>
      {notifications.length > 0 && (
        <div className="check-group">
          <p className="check-group-head">
            <strong>Quality notifications</strong>{" "}
            <span className={`badge ${NOTIFICATIONS[check.notifications].badge}`}>
              {NOTIFICATIONS[check.notifications].label}
            </span>
            <span className="sub">a separate use case: these offers do not change the connector's status</span>
          </p>
          <StepList steps={notifications} />
        </div>
      )}
    </div>
  );
}

export function HealthPanel({
  partner,
  ownBpnl,
  canCheck,
  busy,
  onBusy,
  onChecked,
}: {
  partner: Partner;
  ownBpnl: string | null;
  canCheck: boolean;
  busy: CheckLevel | null;
  onBusy: (level: CheckLevel | null) => void;
  onChecked: () => void;
}) {
  const [history, setHistory] = useState<PartnerCheck[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    api.partnerChecks(partner.bpnl, 5).then(
      (page) => setHistory(page.items),
      (e: Error) => setError(e.message),
    );
  }, [partner.bpnl, version]);

  const run = async (level: CheckLevel) => {
    if (level === "full" && !window.confirm(FULL_CHECK_WARNING)) return;
    onBusy(level);
    setError(null);
    try {
      await api.checkPartner(partner.bpnl, level);
      setVersion((v) => v + 1);
      onChecked();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      onBusy(null);
    }
  };

  const [latest, ...older] = history ?? [];

  return (
    <div className="health-panel">
      <div className="health-head">
        <div>
          <p className="overline">Connector health</p>
          <span className="muted">
            {partner.connector_address ? (
              <span className="cell-id">{partner.connector_address}</span>
            ) : (
              "No connector address — set one with Edit"
            )}
          </span>
        </div>
        <div className="actions">
          {LEVELS.map(({ level, label, hint }) => (
            <button
              key={level}
              type="button"
              className={`btn ${level === "full" ? "btn-danger" : "btn-secondary"}`}
              title={canCheck ? hint : "No EDC configured"}
              disabled={!canCheck || busy !== null}
              onClick={() => run(level)}
            >
              {busy === level ? "Checking…" : label}
            </button>
          ))}
        </div>
      </div>
      <ErrorAlert error={error} />
      {latest ? (
        <>
          <Steps check={latest} />
          {(latest.status === "failed" || latest.status === "degraded" || latest.notifications === "incomplete") && (
            <div className="check-report">
              <CopyReport check={latest} partner={partner} ownBpnl={ownBpnl} />
            </div>
          )}
          {older.length > 0 && (
            <details className="check-history">
              <summary>Earlier checks ({older.length})</summary>
              {older.map((check) => (
                <div key={check.id} className="check-history-item">
                  <HealthBadge check={check} />
                  <Steps check={check} />
                </div>
              ))}
            </details>
          )}
        </>
      ) : (
        history && <p className="muted">No checks yet.</p>
      )}
    </div>
  );
}
