// Direct partners found in the own BoM and usage data: connector addresses (editable by an
// admin), partner sync per partner or for all — followed live while it runs, with its metrics
// once done — and each connector's health with its checks.
import { useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  ApiError,
  formatDateTime,
  type CheckLevel,
  type CheckStatus,
  type Health,
  type Partner,
  type PartnerSyncProgress,
} from "./api";
import { ConnectorOverview, healthOf, type HealthFilter } from "./ConnectorOverview";
import { CheckIcon, ChevronIcon, SyncIcon } from "./icons";
import { HealthBadge, HealthPanel, STATUS as CHECK_STATUS } from "./PartnerHealth";
import { partnerNames, SyncLive, SyncSummary } from "./PartnerSyncPanel";
import { EmptyState, ErrorAlert, SkeletonRows } from "./ui";

const STATUS: Record<NonNullable<Partner["last_status"]>, { label: string; badge: string }> = {
  ok: { label: "Synced", badge: "badge-ok" },
  partial: { label: "Partial", badge: "badge-warn" },
  failed: { label: "Failed", badge: "badge-error" },
  no_connector: { label: "No connector", badge: "badge-warn" },
};

function PartnerRow({
  partner,
  canSync,
  busy,
  onSync,
  onSaved,
  canCheck,
  checking,
  onChecking,
  onChecked,
  canEdit,
  ownBpnl,
}: {
  partner: Partner;
  canSync: boolean;
  busy: boolean;
  onSync: () => void;
  onSaved: (p: Partner) => void;
  canCheck: boolean;
  checking: CheckLevel | null;
  onChecking: (level: CheckLevel | null) => void;
  onChecked: () => void;
  canEdit: boolean;
  ownBpnl: string | null;
}) {
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(partner.name ?? "");
  const [address, setAddress] = useState(partner.connector_address ?? "");
  const [error, setError] = useState<string | null>(null);
  const status = partner.last_status ? STATUS[partner.last_status] : null;

  const save = async () => {
    setError(null);
    try {
      onSaved(
        await api.updatePartner(partner.bpnl, {
          name: name.trim() || null,
          connector_address: address.trim() || null,
        }),
      );
      setEditing(false);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  return (
    <>
      <tr className={expanded ? "row-expanded" : undefined}>
        <td className="cell-partner">
          <div className="part-link">
            {partner.name ? (
              <>
                <strong>{partner.name}</strong>
                <span className="cell-id">{partner.bpnl}</span>
              </>
            ) : (
              <>
                <strong className="mono">{partner.bpnl}</strong>
                <span className="sub">No name yet</span>
              </>
            )}
          </div>
        </td>
        <td>
          <div className="badges">
            {partner.roles.map((role) => (
              <span key={role} className={`badge ${role === "supplier" ? "badge-v3" : "badge-v4"}`}>
                {role === "supplier" ? "Supplier" : "Customer"}
              </span>
            ))}
          </div>
        </td>
        <td>
          <div className="part-link">
            <span className="nowrap">{partner.linked_twins} linked</span>
            <span className="sub nowrap">{partner.cached_parts} cached</span>
          </div>
        </td>
        <td>
          {editing ? (
            <div className="edit-row">
              <input className="input" aria-label="Name" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
              <input
                className="input mono"
                aria-label="DSP endpoint"
                placeholder="https://edc.partner/api/v1/dsp"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
              />
              <ErrorAlert error={error} />
            </div>
          ) : partner.connector_address ? (
            <div className="part-link cell-connector">
              <span className="cell-id" title={partner.connector_address}>
                {partner.connector_address}
              </span>
              <span className="sub">{partner.connector_source === "api" ? "set here" : "from settings"}</span>
            </div>
          ) : (
            <span className="muted">Not set</span>
          )}
        </td>
        <td>
          {status ? (
            <div className="part-link">
              <span className={`badge ${status.badge}`}>
                {partner.last_status === "ok" && <CheckIcon />}
                {status.label}
              </span>
              <span className="sub" title={partner.last_message ?? undefined}>
                {partner.last_sync_at && formatDateTime(partner.last_sync_at)}
                {partner.twins_missing > 0 && ` · ${partner.twins_missing} not found`}
                {partner.consecutive_failures > 1 && ` · failed ${partner.consecutive_failures}× in a row`}
              </span>
            </div>
          ) : (
            <span className="muted">Never</span>
          )}
        </td>
        <td>
          <button
            type="button"
            className="health-toggle"
            aria-expanded={expanded}
            aria-label={`Connector health of ${partner.bpnl}`}
            onClick={() => setExpanded((v) => !v)}
          >
            <HealthBadge check={partner.last_check} />
            <span className="chevron">
              <ChevronIcon />
            </span>
          </button>
        </td>
        <td>
          <div className="actions nowrap">
            {editing ? (
              <>
                <button type="button" className="btn btn-primary" onClick={save}>
                  Save
                </button>
                <button type="button" className="btn btn-secondary" onClick={() => setEditing(false)}>
                  Cancel
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={!canEdit}
                  title={canEdit ? undefined : "Sign in as admin to change partners"}
                  onClick={() => setEditing(true)}
                >
                  Edit
                </button>
                <button
                  type="button"
                  className="icon-btn"
                  aria-label={`Sync ${partner.bpnl}`}
                  title={canSync ? "Sync this partner" : "No EDC configured"}
                  disabled={!canSync || busy || !partner.connector_address}
                  onClick={onSync}
                >
                  <SyncIcon className={busy ? "spin" : undefined} />
                </button>
              </>
            )}
          </div>
        </td>
      </tr>
      {expanded && (
        <tr className="health-row">
          <td colSpan={7}>
            <HealthPanel
              partner={partner}
              ownBpnl={ownBpnl}
              canCheck={canCheck}
              busy={checking}
              onBusy={onChecking}
              onChecked={onChecked}
            />
          </td>
        </tr>
      )}
    </>
  );
}

export function Partners({
  health,
  dataVersion,
  canEdit,
}: {
  health: Health | null;
  dataVersion: number;
  canEdit: boolean;
}) {
  const [partners, setPartners] = useState<Partner[] | null>(null);
  const [syncing, setSyncing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [checking, setChecking] = useState<CheckLevel | null>(null);
  const [checkSummary, setCheckSummary] = useState<string | null>(null);
  const [healthFilter, setHealthFilter] = useState<HealthFilter>(null);
  const [progress, setProgress] = useState<PartnerSyncProgress | null>(null);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const wasRunning = useRef(false);
  const canSync = Boolean(health?.edc_configured);
  const canCheck = Boolean(health?.can_check_partners);
  const visible = healthFilter === null ? partners : partners?.filter((p) => healthOf(p) === healthFilter);

  const names = useMemo(() => partnerNames(partners), [partners]);
  // A sync being started here, or one running (started here, by the periodic sync, in another
  // tab): follow it.
  const running = progress?.running ?? false;
  const polling = syncing !== null || running;

  useEffect(() => {
    api.partners().then(setPartners, (e: Error) => setError(e.message));
  }, [dataVersion, version]);

  // Often while a sync runs; now and then otherwise, to notice one started elsewhere.
  useEffect(() => {
    if (!canSync) return;
    const load = () => api.partnerSyncProgress().then(setProgress, () => undefined);
    if (!polling) load();
    const timer = window.setInterval(load, polling ? 700 : 5000);
    return () => window.clearInterval(timer);
  }, [polling, canSync]);

  // A run has ended (started here or elsewhere): show its metrics and the partners' new state.
  useEffect(() => {
    if (wasRunning.current && !running) {
      setSummaryOpen(true);
      setVersion((v) => v + 1);
    }
    wasRunning.current = running;
  }, [running]);

  // Starts the sync in the background; the polling above follows it to its end.
  // One partner: every twin; all partners: twins read recently are skipped unless `full`.
  const sync = async (bpnl?: string, full?: boolean) => {
    setSyncing(bpnl ?? "*");
    setSummaryOpen(false);
    setError(null);
    try {
      const started = await api.syncPartners(bpnl, full);
      setProgress(started);
      if (!started.running) {
        // Over before it could be followed.
        setSummaryOpen(true);
        setVersion((v) => v + 1);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      // 409: another sync runs — follow that one.
      api.partnerSyncProgress().then(setProgress, () => undefined);
    } finally {
      setSyncing(null);
    }
  };

  const checkUnhealthy = async () => {
    setChecking("catalog");
    setError(null);
    setCheckSummary(null);
    try {
      const { items } = await api.checkPartners("catalog");
      const counts = (Object.keys(CHECK_STATUS) as CheckStatus[])
        .map((status) => [items.filter((c) => c.status === status).length, CHECK_STATUS[status].label] as const)
        .filter(([n]) => n > 0)
        .map(([n, label]) => `${n} ${label.toLowerCase()}`);
      setCheckSummary(
        items.length
          ? `Checked ${items.length} partner${items.length === 1 ? "" : "s"}: ${counts.join(", ")}.`
          : "Every partner was healthy at its last check.",
      );
      setVersion((v) => v + 1);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setChecking(null);
    }
  };

  return (
    <>
      <div className="page-head-row">
        <div className="page-head">
          <h1>Partners</h1>
          <p>
            Direct suppliers and customers, found in your own BoM and usage data. Their linked twins are read through your
            EDC — one level only — so their parts show up in your trees.
          </p>
        </div>
        <div className="actions">
          <button
            type="button"
            className="btn btn-secondary"
            disabled={!canCheck || checking !== null}
            title={
              canCheck
                ? "Catalog check (read-only) of partners never checked or not healthy at their last check"
                : "No EDC configured"
            }
            onClick={checkUnhealthy}
          >
            {checking === "catalog" ? "Checking…" : "Check unhealthy"}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!canSync || polling}
            title={
              !canSync
                ? "No EDC configured"
                : running && syncing === null
                  ? "A partner sync is running"
                  : "Skips twins read recently; a partner's own sync button reads every twin of it"
            }
            onClick={() => sync()}
          >
            <SyncIcon className={polling ? "spin" : undefined} />
            {polling ? "Syncing…" : "Sync all partners"}
          </button>
        </div>
      </div>

      {!canSync && (
        <div className="alert alert-info">
          No EDC is configured (CXS_EDC_MANAGEMENT_URL): partners are listed from your own data, but their twins cannot
          be read{health?.can_send_notifications ? "." : " and notifications cannot be sent."}
        </div>
      )}
      <ErrorAlert error={error} />
      {checkSummary && <div className="alert alert-info">{checkSummary}</div>}

      {polling ? (
        <SyncLive progress={progress} names={names} />
      ) : (
        summaryOpen &&
        progress && (
          <SyncSummary
            progress={progress}
            names={names}
            onDismiss={() => setSummaryOpen(false)}
            onFullSync={canSync ? () => sync(undefined, true) : undefined}
          />
        )
      )}

      {partners && partners.length > 0 && (
        <ConnectorOverview partners={partners} filter={healthFilter} onFilter={setHealthFilter} />
      )}

      <div className="table-box partners-table">
        <table>
          <thead>
            <tr>
              <th scope="col">Partner</th>
              <th scope="col">Role</th>
              <th scope="col">Twins</th>
              <th scope="col">Connector (DSP)</th>
              <th scope="col">Last sync</th>
              <th scope="col">Health</th>
              <th scope="col">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {visible?.map((partner) => (
              <PartnerRow
                key={partner.bpnl}
                partner={partner}
                canSync={canSync}
                busy={
                  syncing === partner.bpnl ||
                  Boolean(running && progress?.partners.some((p) => p.bpnl === partner.bpnl && p.state === "running"))
                }
                onSync={() => sync(partner.bpnl)}
                onSaved={() => setVersion((v) => v + 1)}
                canEdit={canEdit}
                ownBpnl={health?.own_bpnl ?? null}
                canCheck={canCheck}
                checking={checking}
                onChecking={setChecking}
                onChecked={() => setVersion((v) => v + 1)}
              />
            ))}
            {!partners && !error && <SkeletonRows rows={3} cols={7} />}
            {partners && partners.length === 0 && (
              <EmptyState cols={7} title="No partners yet">
                <p>
                  Partners are found in your own data: the suppliers in your parts' bills of material and the customers
                  in their usage. Sync your own twins in <a href="#/">Parts</a> and they appear here.
                </p>
              </EmptyState>
            )}
            {partners && partners.length > 0 && visible?.length === 0 && (
              <tr>
                <td colSpan={7} className="muted">
                  No partners with this health status.{" "}
                  <button type="button" className="link-btn" onClick={() => setHealthFilter(null)}>
                    Show all
                  </button>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
