// Connectivity checks of a partner's connector: last result badge and the expandable panel.
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
      </span>
    </div>
  );
}

function Steps({ check }: { check: PartnerCheck }) {
  return (
    <ul className="check-steps">
      {check.steps.map((step) => (
        <li key={step.key}>
          <span className={`badge ${STEP[step.status].badge}`}>{STEP[step.status].label}</span>
          <strong>{step.name}</strong>
          <span className="check-detail">{step.detail}</span>
        </li>
      ))}
    </ul>
  );
}

export function HealthPanel({
  partner,
  canCheck,
  busy,
  onBusy,
  onChecked,
}: {
  partner: Partner;
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
