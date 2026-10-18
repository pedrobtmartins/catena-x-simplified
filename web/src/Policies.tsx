// Setup: the usage policies the app accepts when it negotiates. The deployment's are locked; an
// admin adds more, typed in or taken from what a connector offers for an asset.
import { useEffect, useState } from "react";
import { api, ApiError, BPNL_PATTERN, type OfferedPolicy, type Partner, type Policies as PoliciesData, type PolicyEntry } from "./api";
import { ErrorAlert } from "./ui";

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : String(e);
}

function PolicyRow({
  entry,
  locked,
  onRemove,
}: {
  entry: PolicyEntry;
  locked: boolean;
  onRemove?: () => void;
}) {
  return (
    <li className="policy-row">
      <div className="stack-tight">
        <span className="policy-text">{entry.description}</span>
        <details className="policy-json">
          <summary>ODRL</summary>
          <pre>{JSON.stringify(entry.policy, null, 2)}</pre>
        </details>
      </div>
      <div className="actions nowrap">
        <span className="badge badge-outline">{locked ? "Deployment" : "Added here"}</span>
        {onRemove && (
          <button type="button" className="btn btn-secondary btn-sm" onClick={onRemove}>
            Remove
          </button>
        )}
      </div>
    </li>
  );
}

/** Reads a connector's catalog for one asset and lists the policies it offers. */
function OfferFinder({
  ownBpnl,
  partners,
  canAccept,
  onAccept,
}: {
  ownBpnl: string;
  partners: Partner[];
  canAccept: boolean;
  onAccept: (policy: Record<string, unknown>) => Promise<void>;
}) {
  const [bpnl, setBpnl] = useState(ownBpnl);
  const [address, setAddress] = useState("");
  const [assetId, setAssetId] = useState("");
  const [offers, setOffers] = useState<OfferedPolicy[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const choose = (value: string) => {
    setBpnl(value);
    // A partner's known address fills in; the own connector's depends on the asset.
    setAddress(partners.find((p) => p.bpnl === value)?.connector_address ?? "");
    setOffers(null);
  };

  const read = async () => {
    setBusy(true);
    setError(null);
    setOffers(null);
    setConfirming(null);
    try {
      setOffers(
        await api.offeredPolicies({
          bpnl,
          connector_address: address.trim() || undefined,
          asset_id: assetId.trim() || undefined,
        }),
      );
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="offer-finder">
      <h3>Find the policy a connector offers</h3>
      <p className="muted">
        When a negotiation fails because no offered policy is accepted, read that connector's catalog for the asset and
        accept the policy as it is offered. Only the catalog is read; nothing is negotiated.
      </p>
      <div className="offer-form">
        <label className="field">
          <span>Connector of</span>
          <select className="input" value={bpnl} onChange={(e) => choose(e.target.value)}>
            <option value={ownBpnl}>Your own connector ({ownBpnl})</option>
            {partners.map((p) => (
              <option key={p.bpnl} value={p.bpnl}>
                {p.name ?? p.bpnl}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>DSP address</span>
          <input
            className="input mono"
            placeholder="https://edc.example/api/v1/dsp"
            value={address}
            onChange={(e) => setAddress(e.target.value)}
          />
          <span className="sub">
            Empty: the partner's known address. For your own submodels, the dspEndpoint in their descriptor.
          </span>
        </label>
        <label className="field">
          <span>Asset ID</span>
          <input
            className="input mono"
            placeholder="e.g. vehicle_bundle_sp"
            value={assetId}
            onChange={(e) => setAssetId(e.target.value)}
          />
          <span className="sub">Empty: the connector's Digital Twin Registry offer.</span>
        </label>
      </div>
      <div className="actions">
        <button
          type="button"
          className="btn btn-secondary"
          disabled={busy || !BPNL_PATTERN.test(bpnl)}
          onClick={read}
        >
          {busy ? "Reading the catalog…" : "Read offered policies"}
        </button>
      </div>
      <ErrorAlert error={error} />
      {offers && offers.length === 0 && <p className="muted card-gap">The catalog offers no matching asset.</p>}
      {offers && offers.length > 0 && (
        <ul className="policy-list">
          {offers.map((offer, i) => (
            <li key={`${offer.asset_id}-${i}`} className="policy-row">
              <div className="stack-tight">
                <span className="policy-text">{offer.description}</span>
                <span className="sub mono">{offer.asset_id}</span>
                <details className="policy-json">
                  <summary>ODRL</summary>
                  <pre>{JSON.stringify(offer.policy, null, 2)}</pre>
                </details>
              </div>
              <div className="actions nowrap">
                {offer.accepted ? (
                  <span className="badge badge-ok">Accepted</span>
                ) : confirming === i ? (
                  <>
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      onClick={async () => {
                        try {
                          await onAccept(offer.policy);
                          setOffers(offers.map((o) => (o === offer ? { ...o, accepted: true } : o)));
                          setConfirming(null);
                        } catch (e) {
                          setError(message(e));
                        }
                      }}
                    >
                      Accept for every negotiation
                    </button>
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => setConfirming(null)}>
                      Cancel
                    </button>
                  </>
                ) : (
                  <>
                    <span className="badge badge-warn">Not accepted</span>
                    {canAccept && (
                      <button type="button" className="btn btn-secondary btn-sm" onClick={() => setConfirming(i)}>
                        Accept…
                      </button>
                    )}
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Policies({
  ownBpnl,
  partners,
  canConfigure,
  canReadOffers,
  dataVersion,
}: {
  ownBpnl: string;
  partners: Partner[];
  canConfigure: boolean;
  canReadOffers: boolean;
  dataVersion: number;
}) {
  const [data, setData] = useState<PoliciesData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pasted, setPasted] = useState("");

  useEffect(() => {
    api.policies().then(setData, (e: Error) => setError(e.message));
  }, [dataVersion]);

  const canEdit = canConfigure && Boolean(data?.editable);
  const added = data?.added.map((a) => a.policy) ?? [];

  const save = async (next: Record<string, unknown>[]) => {
    setError(null);
    setData(await api.savePolicies(next));
  };

  const addPasted = async () => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(pasted);
    } catch {
      setError("Not valid JSON.");
      return;
    }
    const list = Array.isArray(parsed) ? parsed : [parsed];
    try {
      await save([...added, ...(list as Record<string, unknown>[])]);
      setPasted("");
    } catch (e) {
      setError(message(e));
    }
  };

  return (
    <section className="card" aria-labelledby="policies-title">
      <div className="card-head center">
        <h2 id="policies-title">Accepted usage policies</h2>
        {data && (
          <span className="badge badge-outline">
            {data.deployment.length + data.added.length} accepted
          </span>
        )}
      </div>
      <p className="muted card-gap">
        The app only negotiates for an offer whose usage policy means the same as one of these, however the connector
        spells it (Saturn or Jupiter). The deployment's policies (CXS_ACCEPTED_POLICIES) are locked; those added here
        apply at once, without a restart.
      </p>
      {data?.accept_any && (
        <div className="alert alert-warn card-gap" role="status">
          CXS_ACCEPT_ANY_POLICY is on: every offered policy is accepted. Development only.
        </div>
      )}
      <ErrorAlert error={error} />
      {data && data.deployment.length + data.added.length === 0 && (
        <p className="card-gap">
          No policies are accepted yet, so nothing can be negotiated. Add the policies your company agreed to, or take
          them from a connector's offer below.
        </p>
      )}
      {data && (
        <ul className="policy-list">
          {data.deployment.map((entry, i) => (
            <PolicyRow key={`d${i}`} entry={entry} locked />
          ))}
          {data.added.map((entry, i) => (
            <PolicyRow
              key={`a${i}`}
              entry={entry}
              locked={false}
              onRemove={
                canEdit
                  ? () => save(added.filter((_, j) => j !== i)).catch((e) => setError(message(e)))
                  : undefined
              }
            />
          ))}
        </ul>
      )}
      {!canConfigure && (
        <p className="sub card-gap">
          <a href="#/login">Sign in as admin</a> to add or remove policies.
        </p>
      )}
      {canEdit && (
        <details className="paste-policy card-gap">
          <summary>Add a policy as ODRL JSON</summary>
          <textarea
            className="textarea mono"
            rows={8}
            placeholder='{"permission": {"action": "use", "constraint": {"and": [ … ]}}}'
            value={pasted}
            onChange={(e) => setPasted(e.target.value)}
          />
          <div className="actions card-gap">
            <button type="button" className="btn btn-secondary" disabled={!pasted.trim()} onClick={addPasted}>
              Add
            </button>
          </div>
        </details>
      )}
      {canReadOffers && data && (
        <OfferFinder
          ownBpnl={ownBpnl}
          partners={partners}
          canAccept={canEdit}
          onAccept={(policy) => save([...added, policy])}
        />
      )}
    </section>
  );
}
