// The guided setup: what the app needs, in plain language, and what to ask the IT team for.
import { useState } from "react";
import type { ConfigGroup, Health, Me, Partner, SyncReport } from "./api";
import { CheckIcon, ChevronIcon } from "./icons";
import type { Checks, useConnectionTests } from "./Setup";

type StepState = "done" | "todo" | "failed" | "optional";

interface Step {
  key: string;
  title: string;
  optional?: boolean;
  state: StepState;
  /** One line: where this step stands now. */
  status: string;
  /** What it is, for someone who has never heard of it. */
  what: string;
  /** What to ask the IT team or the connector provider for. */
  ask: string[];
  /** The settings the IT team fills in. */
  settings: string[];
  action?: "test" | "sync" | "partners";
  /** The settings group an admin can fill in on this page. */
  group?: ConfigGroup;
}

function fromCheck(check: Checks[keyof Checks], configured: boolean): { state: StepState; status?: string } {
  if (!configured) return { state: "todo" };
  if (check?.status === "failed") return { state: "failed", status: check.detail };
  return { state: "done" };
}

function steps(health: Health, partners: Partner[], lastRun: SyncReport | null, checks: Checks | null): Step[] {
  const dtr = fromCheck(checks?.dtr, health.dtr_configured);
  const edc = fromCheck(checks?.edc, health.edc_configured);
  const assets = health.notification_assets;
  const missing = partners.filter((p) => !p.connector_address).length;
  const servicesFailed = [checks?.central_idp, checks?.discovery, checks?.bpdm, checks?.bp_explorer].find(
    (c) => c?.status === "failed",
  );
  const services = health.can_discover_connectors || health.can_look_up_names;

  return [
    {
      key: "company",
      title: "Your company",
      state: "done",
      status: `Your Business Partner Number (BPNL) is ${health.own_bpnl}.`,
      what: "The BPNL identifies your company in Catena-X. Your company received it when it joined the dataspace.",
      ask: ["Your company's BPNL (from the Catena-X onboarding)"],
      settings: ["CXS_OWN_BPNL"],
    },
    {
      key: "dtr",
      title: "Your digital twin registry",
      ...dtr,
      status:
        dtr.status ??
        (health.dtr_configured
          ? `Connected to ${health.dtr_url ?? "your registry"}${checks?.dtr?.status === "ok" ? " — tested." : "."}`
          : "Not set up yet."),
      what: "The registry lists the digital twins of the parts you make. The app reads your parts from it.",
      ask: [
        "The address (URL) of your digital twin registry",
        "How the app signs in to it: an OAuth client (token URL, client ID and secret) — or nothing, if the registry is only reachable inside your network",
      ],
      settings: [
        "CXS_DTR_BASE_URL",
        "CXS_OAUTH_TOKEN_URL (or CXS_OAUTH_URL + CXS_OAUTH_REALM for Keycloak)",
        "CXS_OAUTH_CLIENT_ID",
        "CXS_OAUTH_CLIENT_SECRET",
        "CXS_OAUTH_SCOPE (if your identity provider needs one)",
      ],
      action: "test",
      group: "registry",
    },
    {
      key: "parts",
      title: "Load your parts",
      state: lastRun?.complete ? "done" : "todo",
      status: lastRun
        ? lastRun.complete
          ? `${lastRun.parts} parts loaded from ${lastRun.twins} twins` +
            (health.sync_subset > 0 ? ` (a test subset: ${health.sync_subset} twins listed).` : ".")
          : "The last sync did not finish — see Sync history."
        : "Your parts have not been loaded yet.",
      what: "Reading your twins once shows your parts and finds your direct suppliers and customers.",
      ask: [],
      settings: [],
      action: health.dtr_configured ? "sync" : undefined,
    },
    {
      key: "edc",
      title: "Your connector (EDC)",
      ...(health.dev_direct ? { state: "done" as const } : edc),
      status: health.dev_direct
        ? "Not needed in development mode."
        : (edc.status ??
          (health.edc_configured
            ? `Connected${checks?.edc?.status === "ok" ? " — tested." : "."}`
            : "Not set up yet.")),
      what:
        "Your connector exchanges data with your partners: it reads their twins and sends your quality alerts. " +
        "It is usually run by your IT team or a service provider.",
      ask: [
        "The address of your connector's management API (often ending in /management)",
        "How the app signs in to it: an API key, an OAuth client (token URL, client ID, secret and scope), or both",
      ],
      settings: [
        "CXS_EDC_MANAGEMENT_URL",
        "CXS_EDC_MANAGEMENT_PATH",
        "CXS_EDC_API_KEY",
        "CXS_EDC_OAUTH_TOKEN_URL",
        "CXS_EDC_OAUTH_CLIENT_ID",
        "CXS_EDC_OAUTH_CLIENT_SECRET",
        "CXS_EDC_OAUTH_SCOPE",
      ],
      action: "test",
      group: "connector",
    },
    {
      key: "notifications",
      title: "Receive quality notifications",
      state: health.dev_direct || assets.state === "published" ? "done" : assets.state === "failed" ? "failed" : "todo",
      status: health.dev_direct
        ? "Not needed in development mode."
        : assets.state === "published"
          ? "Your partners can send you alerts and investigations."
          : assets.state === "failed"
            ? `The app could not register its inbox in your connector: ${assets.message ?? "unknown error"}`
            : "Your partners cannot send you notifications yet.",
      what:
        "So that partners can send you alerts, your connector offers this app's notification inbox. " +
        "The app registers that offer by itself once it knows how your connector reaches it.",
      ask: [
        "The address at which your connector reaches this app, inside your network",
        "A secret key that protects the inbox (your IT team chooses one)",
      ],
      settings: ["CXS_NOTIFICATION_BASE_URL", "CXS_NOTIFICATION_API_KEY"],
      group: "notifications",
    },
    {
      key: "partners",
      title: "Your partners' connectors",
      state: partners.length > 0 && missing === 0 ? "done" : "todo",
      status:
        partners.length === 0
          ? "No partners yet."
          : missing === 0
            ? `All ${partners.length} partners have a connector address.`
            : `${missing} of ${partners.length} partners have no connector address.`,
      what:
        "To talk to a partner, the app needs the address of its connector. Partners in your parts data appear on " +
        "their own; you can add others by their BPNL.",
      ask: ["Each partner's connector address (DSP endpoint) — unless the dataspace services below find it"],
      settings: [],
      action: "partners",
    },
    {
      key: "services",
      title: "Dataspace services",
      optional: true,
      state: servicesFailed ? "failed" : services ? "done" : "optional",
      status: servicesFailed
        ? servicesFailed.detail
        : services
          ? [
              health.can_discover_connectors && "Connector addresses are found by BPNL",
              health.can_look_up_names && `partner names come from the ${health.names_source ?? "BPDM Pool"}`,
            ]
              .filter(Boolean)
              .join("; ") + "."
          : "Optional: find partners' connectors and names automatically.",
      what:
        "With a technical user of the Catena-X identity provider, the app finds partners' connector addresses and " +
        "company names from their BPNL, so nobody has to type them.",
      ask: [
        "A technical user for the Catena-X central identity provider (client ID and secret) — your company admin " +
          "requests it in the Catena-X portal",
        "The addresses of the BPDM Pool and of the Discovery Finder — or of the EDC Discovery directly — of your " +
          "dataspace (from its operating company)",
        "Or, where the golden record is offered only through a connector (Cofinity-X: subscribe to the Business " +
          "Partner Explorer), its DSP endpoint and BPN — names are then read through your connector",
      ],
      settings: [
        "CXS_CENTRAL_IDP_URL",
        "CXS_CENTRAL_IDP_REALM",
        "CXS_CENTRAL_IDP_CLIENT_ID",
        "CXS_CENTRAL_IDP_CLIENT_SECRET",
        "CXS_DISCOVERY_FINDER_URL",
        "CXS_EDC_DISCOVERY_URL",
        "CXS_BPDM_POOL_URL",
        "CXS_BP_EXPLORER_ADDRESS",
        "CXS_BP_EXPLORER_BPNL",
        "CXS_BP_EXPLORER_ASSET_ID",
      ],
      action: "test",
      group: "services",
    },
  ];
}

/** A message for the IT team listing what the open steps need. */
function requestText(open: Step[]): string {
  const lines = [
    "Hello,",
    "",
    "to set up the Catena-X traceability app I need the following. Please put the values in the app's " +
      "configuration (environment variables, .env file or Helm values) and restart it:",
  ];
  for (const step of open) {
    if (step.ask.length === 0) continue;
    lines.push("", `${step.title}${step.optional ? " (optional)" : ""}:`);
    step.ask.forEach((a) => lines.push(`- ${a}`));
    if (step.settings.length) lines.push(`  Settings: ${step.settings.join(", ")}`);
  }
  lines.push("", "The settings are described in backend/README.md. Thank you!");
  return lines.join("\n");
}

const STATE_LABEL: Record<StepState, string> = { done: "Done", todo: "To do", failed: "Needs attention", optional: "Optional" };

export function Checklist({
  health,
  me,
  partners,
  lastRun,
  syncing,
  onSync,
  tests,
  onFill,
}: {
  health: Health;
  me: Me | null;
  partners: Partner[];
  lastRun: SyncReport | null;
  syncing: boolean;
  onSync: () => void;
  tests: ReturnType<typeof useConnectionTests>;
  /** Opens the settings form at a group; null when the user cannot enter settings here. */
  onFill: ((group: ConfigGroup) => void) | null;
}) {
  const all = steps(health, partners, lastRun, tests.checks);
  const required = all.filter((s) => !s.optional);
  const done = required.filter((s) => s.state === "done").length;
  const complete = done === required.length;
  const open = all.filter((s) => s.state !== "done");
  const [expanded, setExpanded] = useState<string | null>(() => open.find((s) => !s.optional)?.key ?? null);
  const [hidden, setHidden] = useState(complete);
  const [copied, setCopied] = useState<"ok" | "failed" | null>(null);

  const copyRequest = async () => {
    try {
      await navigator.clipboard.writeText(requestText(open));
      setCopied("ok");
    } catch {
      setCopied("failed");
    }
  };

  if (hidden) {
    return (
      <div className="checklist-done">
        <span className="badge badge-ok">
          <CheckIcon />
          Setup complete
        </span>
        <button type="button" className="link-btn" onClick={() => setHidden(false)}>
          Show the setup steps
        </button>
      </div>
    );
  }

  return (
    <section className="card checklist" aria-labelledby="checklist-title">
      <div className="card-head" style={{ alignItems: "center" }}>
        <div>
          <h2 id="checklist-title">{complete ? "Setup complete" : "Get started"}</h2>
          <p className="sub card-note">
            {done} of {required.length} steps done.{" "}
            {complete
              ? "The app is ready to use."
              : "Most values come from your IT team or your connector provider — the app tells you what to ask for."}
          </p>
        </div>
        <div className="actions">
          {open.some((s) => s.ask.length > 0) && (
            <button type="button" className="btn btn-secondary" onClick={copyRequest}>
              {copied === "ok" ? "Copied" : "Copy request for IT"}
            </button>
          )}
          {complete && (
            <button type="button" className="btn btn-secondary" onClick={() => setHidden(true)}>
              Hide
            </button>
          )}
        </div>
      </div>
      <div className="setup-progress" role="progressbar" aria-valuemin={0} aria-valuemax={required.length} aria-valuenow={done}>
        <span style={{ width: `${(done / required.length) * 100}%` }} />
      </div>
      {copied === "failed" && (
        <div className="alert alert-error" role="alert">
          The browser did not allow copying. Select the text below and copy it yourself.
          <pre className="request-text">{requestText(open)}</pre>
        </div>
      )}

      <ol className="setup-steps">
        {all.map((step, index) => {
          const isOpen = expanded === step.key;
          return (
            <li key={step.key} className={`setup-step setup-step-${step.state}`}>
              <button
                type="button"
                className="setup-step-head"
                aria-expanded={isOpen}
                onClick={() => setExpanded(isOpen ? null : step.key)}
              >
                <span className="setup-step-marker" aria-hidden="true">
                  {step.state === "done" ? <CheckIcon /> : step.state === "failed" ? "!" : index + 1}
                </span>
                <span className="setup-step-text">
                  <strong>
                    {step.title}
                    {step.optional && <span className="sub"> · optional</span>}
                  </strong>
                  <span className="sub">{step.status}</span>
                </span>
                <span className="sr-only">{STATE_LABEL[step.state]}</span>
                <span className="chevron">
                  <ChevronIcon />
                </span>
              </button>
              {isOpen && (
                <div className="setup-step-body">
                  <p>{step.what}</p>
                  {step.ask.length > 0 && (
                    <>
                      <p className="overline">{onFill ? "You need" : "Ask your IT team for"}</p>
                      <ul>
                        {step.ask.map((a) => (
                          <li key={a}>{a}</li>
                        ))}
                      </ul>
                    </>
                  )}
                  {step.settings.length > 0 && (
                    <details>
                      <summary>Where your IT team puts it</summary>
                      <p className="sub">
                        In the app's configuration (environment variables, the .env file or the Helm values), then
                        restart the app:
                      </p>
                      <ul className="mono settings-list">
                        {step.settings.map((s) => (
                          <li key={s}>{s}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                  {step.group && me?.login_enabled && !onFill && (
                    <p className="sub">
                      Or an admin fills it in here: <a href="#/login">sign in as admin</a>.
                    </p>
                  )}
                  <div className="actions">
                    {step.group && onFill && (
                      <button type="button" className="btn btn-primary" onClick={() => onFill(step.group!)}>
                        Fill it in here
                      </button>
                    )}
                    {step.action === "test" && (
                      <button type="button" className="btn btn-secondary" disabled={tests.testing} onClick={tests.test}>
                        {tests.testing ? "Testing…" : "Test connections"}
                      </button>
                    )}
                    {step.action === "sync" && (
                      <button type="button" className="btn btn-primary" disabled={syncing} onClick={onSync}>
                        {syncing ? "Loading…" : "Load my parts now"}
                      </button>
                    )}
                    {step.action === "partners" && (
                      <button
                        type="button"
                        className="btn btn-secondary"
                        onClick={() => document.getElementById("setup-partners")?.scrollIntoView({ behavior: "smooth" })}
                      >
                        Go to partner connectors
                      </button>
                    )}
                  </div>
                  {tests.error && step.action === "test" && <p className="error-text">{tests.error}</p>}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
