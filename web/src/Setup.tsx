import { useEffect, useState } from "react";
import {
  api,
  ApiError,
  BPNL_PATTERN,
  type ConfigGroup,
  type ConnectionCheck,
  type Health,
  type Me,
  type Partner,
  type SyncReport,
} from "./api";
import { Checklist } from "./Checklist";
import { ConfigEditor } from "./ConfigEditor";
import { CheckIcon } from "./icons";
import { ErrorAlert } from "./ui";

const ASSETS: Record<Health["notification_assets"]["state"], string> = {
  not_configured: "Not published (needs an EDC and CXS_NOTIFICATION_BASE_URL)",
  publishing: "Publishing…",
  published: "Published",
  failed: "Publishing failed",
};

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : String(e);
}

const CHECK: Record<ConnectionCheck["status"], { label: string; badge: string; dot: string }> = {
  ok: { label: "Connected", badge: "badge-ok", dot: "ok" },
  failed: { label: "Failed", badge: "badge-error", dot: "error" },
  skipped: { label: "Not tested", badge: "badge-warn", dot: "warn" },
  not_configured: { label: "Not configured", badge: "badge-outline", dot: "" },
};

function Setting({
  label,
  value,
  configured,
  check,
}: {
  label: string;
  value: string;
  configured: boolean;
  check?: ConnectionCheck;
}) {
  const result = check ? CHECK[check.status] : null;
  return (
    <div>
      <dt className="overline">{label}</dt>
      <dd className="setting">
        <span className={`dot ${result ? result.dot : configured ? "ok" : ""}`} />
        <span className="cell-mono">{value}</span>
      </dd>
      {check && result && check.status !== "not_configured" && (
        <dd className="setting-check">
          <span className={`badge ${result.badge}`}>
            {check.status === "ok" && <CheckIcon />}
            {result.label}
          </span>
          <span className="sub">{check.detail}</span>
        </dd>
      )}
    </div>
  );
}

const AUTH_LABEL = { oauth: "OAuth 2.0", api_key: "API key" } as const;

export type Checks = Partial<Record<ConnectionCheck["key"], ConnectionCheck>>;

/** Runs the connection tests; the results are shared by the checklist and the participant card. */
export function useConnectionTests() {
  const [checks, setChecks] = useState<Checks | null>(null);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const show = (results: ConnectionCheck[]) => setChecks(Object.fromEntries(results.map((c) => [c.key, c])));
  const test = async () => {
    setTesting(true);
    setError(null);
    try {
      show(await api.testConnections());
    } catch (e) {
      setError(message(e));
    } finally {
      setTesting(false);
    }
  };
  return { checks, testing, error, test, show };
}

function Participant({
  health,
  me,
  tests,
  onEdit,
}: {
  health: Health;
  me: Me | null;
  tests: ReturnType<typeof useConnectionTests>;
  onEdit: (() => void) | null;
}) {
  const assets = health.notification_assets;
  const { checks, testing, error, test } = tests;
  const failed = checks ? Object.values(checks).filter((c) => c.status === "failed").length : 0;

  const edcAuth = health.edc_auth.length ? health.edc_auth.map((a) => AUTH_LABEL[a]).join(" + ") : "no credentials";
  return (
    <section className="card" aria-labelledby="participant-title">
      <div className="card-head" style={{ alignItems: "center" }}>
        <h2 id="participant-title">Your participant</h2>
        <div className="actions">
          {onEdit && (
            <button type="button" className="btn btn-primary" onClick={onEdit}>
              Edit settings
            </button>
          )}
          <button type="button" className="btn btn-secondary" onClick={test} disabled={testing}>
            {testing ? "Testing…" : "Test connections"}
          </button>
        </div>
      </div>
      <p className="sub card-note">
        {onEdit ? (
          "Enter the settings here, or let the deployment set them (CXS_* variables, which win)."
        ) : me?.login_enabled ? (
          <>
            Set by the deployment or by an admin. <a href="#/login">Sign in as admin</a> to enter settings here.
          </>
        ) : (
          <>
            Set when the app is deployed (<span className="mono">CXS_*</span> variables, see backend/README.md). To
            enter them here instead, your IT team sets up the admin login (CXS_ADMIN_PASSWORD_HASH and CXS_SECRET_KEY).
          </>
        )}{" "}
        The test makes read-only calls with the configured credentials.
      </p>
      <ErrorAlert error={error} />
      {checks && (
        <div className={`alert ${failed ? "alert-error" : "alert-info"}`} role="status">
          {failed
            ? `${failed} connection${failed === 1 ? "" : "s"} failed — see the details below.`
            : "Every configured connection works."}
        </div>
      )}
      <dl className="config">
        <Setting label="BPNL" value={health.own_bpnl} configured />
        <Setting
          label="Digital Twin Registry"
          value={
            health.dtr_configured
              ? `${health.dtr_url ?? "Configured"} · ${health.dtr_auth === "oauth" ? "OAuth 2.0" : "no authentication"}`
              : "Not configured (CXS_DTR_BASE_URL)"
          }
          configured={health.dtr_configured}
          check={checks?.dtr}
        />
        <Setting
          label="EDC management API"
          value={
            health.dev_direct
              ? "Development mode: no EDC"
              : health.edc_configured
                ? `Configured · ${edcAuth}`
                : "Not configured (CXS_EDC_MANAGEMENT_URL)"
          }
          configured={health.edc_configured}
          check={checks?.edc}
        />
        <Setting
          label="Notification assets"
          value={assets.state === "failed" && assets.message ? `${ASSETS.failed}: ${assets.message}` : ASSETS[assets.state]}
          configured={assets.state === "published"}
        />
        <Setting
          label="Central IdP"
          value={health.central_idp_url ?? "Not configured (CXS_CENTRAL_IDP_*)"}
          configured={Boolean(health.central_idp_url)}
          check={checks?.central_idp}
        />
        <Setting
          label="Connector discovery"
          value={
            health.can_discover_connectors
              ? "Discovery Finder configured"
              : "Not configured (CXS_DISCOVERY_FINDER_URL and CXS_CENTRAL_IDP_*)"
          }
          configured={health.can_discover_connectors}
          check={checks?.discovery}
        />
        <Setting
          label="Partner names (BPDM)"
          value={
            health.can_look_up_names ? "BPDM Pool configured" : "Not configured (CXS_BPDM_POOL_URL and CXS_CENTRAL_IDP_*)"
          }
          configured={health.can_look_up_names}
          check={checks?.bpdm}
        />
      </dl>
    </section>
  );
}

/** The DSP endpoints the discovery service knows for a BPNL, each one ready to be used. */
function Candidates({
  bpnl,
  current,
  onUse,
}: {
  bpnl: string;
  current: string | null;
  onUse: ((address: string) => void) | null;
}) {
  const [endpoints, setEndpoints] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setEndpoints(null);
    setError(null);
    api.discoverConnectors(bpnl).then(
      (result) => setEndpoints(result.endpoints),
      (e) => setError(message(e)),
    );
  }, [bpnl]);

  if (error) return <ErrorAlert error={`Discovery failed: ${error}`} />;
  if (endpoints === null) return <p className="muted">Asking the discovery service…</p>;
  if (endpoints.length === 0)
    return <p className="muted">No connector is registered for {bpnl} in the discovery service.</p>;
  return (
    <ul className="candidates" aria-label={`Connectors registered for ${bpnl}`}>
      {endpoints.map((endpoint) => (
        <li key={endpoint}>
          <span className="cell-id">{endpoint}</span>
          {endpoint === current ? (
            <span className="badge badge-ok">
              <CheckIcon />
              In use
            </span>
          ) : onUse ? (
            <button type="button" className="btn btn-secondary" onClick={() => onUse(endpoint)}>
              Use
            </button>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function AddPartner({
  partners,
  canDiscover,
  canLookUp,
  canEdit,
  onAdded,
}: {
  partners: Partner[];
  canDiscover: boolean;
  canLookUp: boolean;
  canEdit: boolean;
  onAdded: () => void;
}) {
  const [bpnl, setBpnl] = useState("");
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [discovering, setDiscovering] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const trimmed = bpnl.trim();
  const valid = BPNL_PATTERN.test(trimmed);
  const existing = valid ? partners.find((p) => p.bpnl === trimmed) : undefined;
  const [lookup, setLookup] = useState<{ bpnl: string; text: string } | null>(null);

  // A complete BPNL: fill an empty name with its legal name from the BPDM Pool.
  useEffect(() => {
    if (!canLookUp || !valid) return;
    let current = true;
    setLookup({ bpnl: trimmed, text: "Looking up the legal name…" });
    api.legalEntity(trimmed).then(
      ({ legal_name }) => {
        if (!current) return;
        if (legal_name) setName((name) => name || legal_name);
        setLookup({
          bpnl: trimmed,
          text: legal_name ? `Legal name in BPDM: ${legal_name}` : "This BPNL is not in the BPDM Pool.",
        });
      },
      (e) => current && setLookup({ bpnl: trimmed, text: `Name lookup failed: ${message(e)}` }),
    );
    return () => {
      current = false;
    };
  }, [canLookUp, valid, trimmed]);

  const add = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.updatePartner(trimmed, { name: name.trim() || null, connector_address: address.trim() || null });
      setBpnl("");
      setName("");
      setAddress("");
      setDiscovering(null);
      onAdded();
    } catch (e) {
      setError(message(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="card" id="add-partner" aria-labelledby="add-title">
      <h2 id="add-title">Add a partner</h2>
      <p className="sub card-note">
        Partners in your BoM and usage data are listed on their own. Add the others you exchange notifications with.
      </p>
      <form className="filters setup-form" onSubmit={add}>
        <div className="field">
          <label htmlFor="add-bpnl">BPNL</label>
          <input
            id="add-bpnl"
            className="input mono"
            placeholder="BPNL000000000000"
            value={bpnl}
            onChange={(e) => setBpnl(e.target.value)}
            aria-invalid={trimmed !== "" && !valid}
          />
        </div>
        <div className="field">
          <label htmlFor="add-name">Name</label>
          <input id="add-name" className="input" placeholder="Optional" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="field field-wide">
          <label htmlFor="add-address">Connector (DSP endpoint)</label>
          <div className="input-row">
            <input
              id="add-address"
              className="input mono"
              placeholder="https://edc.partner.example/api/v1/dsp"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
            />
            <button
              type="button"
              className="btn btn-secondary"
              disabled={!canDiscover || !valid}
              title={canDiscover ? "Find the connectors registered for this BPNL" : "No Discovery Finder configured"}
              onClick={() => setDiscovering(trimmed)}
            >
              Discover
            </button>
          </div>
        </div>
        <button
          type="submit"
          className="btn btn-primary"
          disabled={!valid || saving || !canEdit}
          title={canEdit ? undefined : "Sign in as admin to change partners"}
        >
          {existing ? "Update partner" : "Add partner"}
        </button>
      </form>
      {trimmed !== "" && !valid && <p className="sub field-hint">A BPNL is “BPNL” followed by 12 letters or digits.</p>}
      {valid && lookup?.bpnl === trimmed && <p className="sub field-hint">{lookup.text}</p>}
      {existing && (
        <p className="sub field-hint">
          {existing.bpnl} is already listed{existing.name ? ` as ${existing.name}` : ""}: saving updates it.
        </p>
      )}
      {discovering && (
        <div className="candidates-box">
          <Candidates bpnl={discovering} current={address.trim() || null} onUse={canEdit ? setAddress : null} />
        </div>
      )}
      <ErrorAlert error={error} />
    </section>
  );
}

function SetupRow({
  partner,
  canDiscover,
  canEdit,
  onChanged,
}: {
  partner: Partner;
  canDiscover: boolean;
  canEdit: boolean;
  onChanged: () => void;
}) {
  const [discovering, setDiscovering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Partners from the own twins come back on the next sync; only hand-added ones can be removed.
  const addedHere = partner.roles.length === 0;

  const run = async (action: () => Promise<unknown>) => {
    setError(null);
    try {
      await action();
      onChanged();
    } catch (e) {
      setError(message(e));
    }
  };

  return (
    <>
      <tr className={discovering ? "row-expanded" : undefined}>
        <td>
          <div className="part-link">
            <strong>{partner.name ?? "Unnamed partner"}</strong>
            <span className="cell-id">{partner.bpnl}</span>
          </div>
        </td>
        <td>
          <div className="badges">
            {addedHere ? (
              <span className="badge badge-outline">Added here</span>
            ) : (
              partner.roles.map((role) => (
                <span key={role} className={`badge ${role === "supplier" ? "badge-v3" : "badge-v4"}`}>
                  {role === "supplier" ? "Supplier" : "Customer"}
                </span>
              ))
            )}
          </div>
        </td>
        <td>
          {partner.connector_address ? (
            <div className="part-link">
              <span className="cell-id">{partner.connector_address}</span>
              <span className="sub">{partner.connector_source === "api" ? "set here" : "from settings"}</span>
            </div>
          ) : (
            <span className="badge badge-warn">Missing</span>
          )}
          <ErrorAlert error={error} />
        </td>
        <td>
          <div className="actions" style={{ flexWrap: "nowrap" }}>
            <button
              type="button"
              className="btn btn-secondary"
              aria-expanded={discovering}
              disabled={!canDiscover}
              title={canDiscover ? "Find the connectors registered for this BPNL" : "No Discovery Finder configured"}
              onClick={() => setDiscovering((v) => !v)}
            >
              Discover
            </button>
            {addedHere && canEdit && (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => {
                  if (window.confirm(`Remove ${partner.name ?? partner.bpnl}?`)) void run(() => api.removePartner(partner.bpnl));
                }}
              >
                Remove
              </button>
            )}
          </div>
        </td>
      </tr>
      {discovering && (
        <tr className="health-row">
          <td colSpan={4}>
            <Candidates
              bpnl={partner.bpnl}
              current={partner.connector_address}
              onUse={
                canEdit
                  ? (address) => void run(() => api.updatePartner(partner.bpnl, { connector_address: address }))
                  : null
              }
            />
          </td>
        </tr>
      )}
    </>
  );
}

export function Setup({
  health,
  me,
  dataVersion,
  lastRun,
  syncing,
  onSync,
  onHealthChange,
}: {
  health: Health | null;
  me: Me | null;
  dataVersion: number;
  lastRun: SyncReport | null;
  syncing: boolean;
  onSync: () => void;
  onHealthChange: () => void;
}) {
  const tests = useConnectionTests();
  // Changing partners needs an admin once the admin login is set up.
  const canEdit = !me?.login_enabled || Boolean(me.admin);
  const canConfigure = Boolean(me?.admin && me.config_editable);
  const [editing, setEditing] = useState<ConfigGroup | "all" | null>(null);
  const edit = canConfigure ? (group: ConfigGroup | "all") => setEditing(group) : null;
  const [partners, setPartners] = useState<Partner[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const reload = () => setVersion((v) => v + 1);
  const canDiscover = Boolean(health?.can_discover_connectors);
  const canLookUp = Boolean(health?.can_look_up_names);
  const missing = partners?.filter((p) => !p.connector_address).length ?? 0;
  const unnamed = partners?.filter((p) => !p.name).length ?? 0;
  const [naming, setNaming] = useState(false);
  const [namingSummary, setNamingSummary] = useState<string | null>(null);

  const fillNames = async () => {
    setNaming(true);
    setError(null);
    setNamingSummary(null);
    try {
      const results = await api.fillPartnerNames();
      const count = (status: string) => results.filter((r) => r.status === status).length;
      const failed = results.filter((r) => r.status === "failed");
      setNamingSummary(
        [`${count("named")} named`, count("not_found") && `${count("not_found")} not in BPDM`, failed.length && `${failed.length} failed`]
          .filter(Boolean)
          .join(", ") + ".",
      );
      if (failed.length) setError(failed.map((r) => r.message).join(" · "));
      reload();
    } catch (e) {
      setError(message(e));
    } finally {
      setNaming(false);
    }
  };

  useEffect(() => {
    api.partners().then(setPartners, (e: Error) => setError(e.message));
  }, [dataVersion, version]);

  return (
    <>
      <div className="page-head">
        <h1>Setup</h1>
        <p>Your own participant, and the partners whose connectors the app talks to.</p>
      </div>
      <ErrorAlert error={error} />

      {health && partners && (
        <Checklist
          health={health}
          me={me}
          partners={partners}
          lastRun={lastRun}
          syncing={syncing}
          onSync={onSync}
          tests={tests}
          onFill={edit}
        />
      )}
      {editing && canConfigure && (
        <ConfigEditor
          focus={editing === "all" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(checks) => {
            tests.show(checks);
            onHealthChange();
            reload();
          }}
        />
      )}
      {health && <Participant health={health} me={me} tests={tests} onEdit={edit && (() => edit("all"))} />}
      {partners && (
        <AddPartner
          partners={partners}
          canDiscover={canDiscover}
          canLookUp={canLookUp}
          canEdit={canEdit}
          onAdded={reload}
        />
      )}

      <section className="setup-partners" id="setup-partners" aria-labelledby="setup-partners-title">
        <div className="card-head">
          <h2 id="setup-partners-title">Partner connectors</h2>
          {partners && partners.length > 0 && (
            <div className="actions" style={{ alignItems: "center" }}>
              <span className="sub">
                {missing === 0
                  ? "Every partner has a connector address."
                  : `${missing} of ${partners.length} without a connector address`}
              </span>
              {unnamed > 0 && (
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={!canLookUp || naming || !canEdit}
                  title={
                    canLookUp ? "Name unnamed partners after their legal name in the BPDM Pool" : "No BPDM Pool configured"
                  }
                  onClick={fillNames}
                >
                  {naming ? "Looking up…" : `Fill ${unnamed} name${unnamed === 1 ? "" : "s"} from BPDM`}
                </button>
              )}
            </div>
          )}
        </div>
        {namingSummary && <div className="alert alert-info">{namingSummary}</div>}
        <div className="table-box">
          <table>
            <thead>
              <tr>
                <th scope="col">Partner</th>
                <th scope="col">Source</th>
                <th scope="col">Connector (DSP)</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {partners?.map((partner) => (
                <SetupRow
                  key={partner.bpnl}
                  partner={partner}
                  canDiscover={canDiscover}
                  canEdit={canEdit}
                  onChanged={reload}
                />
              ))}
              {partners && partners.length === 0 && (
                <tr>
                  <td colSpan={4} className="muted">
                    No partners yet. Add one above, or sync your own twins: partners come from your BoM and usage
                    aspects.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
