// Connection settings entered by an admin. Values set by the deployment are shown locked.
import { useEffect, useRef, useState } from "react";
import { api, ApiError, formatDateTime, type ConfigField, type ConfigGroup, type ConnectionCheck } from "./api";
import { ErrorAlert } from "./ui";

export const GROUPS: { key: ConfigGroup; title: string; intro: string }[] = [
  {
    key: "registry",
    title: "Your digital twin registry",
    intro: "Where your registry is and how the app signs in to it. Leave the sign-in fields empty if it needs none.",
  },
  {
    key: "connector",
    title: "Your connector (EDC)",
    intro: "The management API of your connector. Fill in an API key, an OAuth client, or both — whatever it expects.",
  },
  {
    key: "notifications",
    title: "Receive quality notifications",
    intro: "How your connector reaches this app, and the key that protects the app's notification inbox.",
  },
  {
    key: "services",
    title: "Dataspace services (optional)",
    intro: "A technical user of the Catena-X identity provider, to find partners' connectors and names by BPNL.",
  },
  {
    key: "names",
    title: "Partner names through your connector (optional)",
    intro:
      "Where your dataspace offers the golden record only through its connector — such as the Cofinity-X " +
      "Business Partner Explorer, after subscribing to it — your connector fetches partners' legal names from " +
      "there. Your accepted usage policies must include the explorer's policy. Used instead of the BPDM Pool.",
  },
];

function message(e: unknown): string {
  if (e instanceof ApiError && e.status === 401) return "Your admin session has ended — sign in again.";
  return e instanceof ApiError ? e.message : String(e);
}

const UUID_URN = /urn:uuid:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;

/** How many twin IDs the server will take from ``text`` (same rule as the backend). */
function countTwinIds(text: string): number {
  const urns = text.match(UUID_URN);
  const ids = urns ?? text.split(/[\s,;]+/).filter(Boolean);
  return new Set(ids.map((id) => (urns ? id.toLowerCase() : id))).size;
}

function FieldInput({
  field,
  value,
  changing,
  removed,
  onChange,
  onChangeSecret,
  onRemove,
}: {
  field: ConfigField;
  value: string;
  changing: boolean;
  removed: boolean;
  onChange: (value: string) => void;
  onChangeSecret: () => void;
  onRemove: () => void;
}) {
  const id = `cfg-${field.key}`;
  if (field.locked) {
    return (
      <div className="config-field">
        <label htmlFor={id}>{field.label}</label>
        <input
          id={id}
          className="input mono"
          disabled
          value={field.secret ? (field.is_set ? "••••••••" : "") : (field.value ?? "")}
        />
        <span className="sub">
          Set by the deployment (<span className="mono">{field.variable}</span>) — change it there.
        </span>
      </div>
    );
  }
  const stored = field.secret && field.is_set && !field.unreadable && !changing && !removed;
  if (field.twin_ids) {
    const count = countTwinIds(value);
    return (
      <div className="config-field wide">
        <label htmlFor={id}>{field.label}</label>
        <textarea
          id={id}
          className="input mono twin-ids"
          rows={5}
          spellCheck={false}
          placeholder={removed ? "Removed — saved on Save" : "urn:uuid:… (one per line, or paste a CSV)"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
        <span className="sub">
          {count > 0 ? `${count} twin${count === 1 ? "" : "s"} listed — only these and their own children are loaded. ` : ""}
          {field.hint}
        </span>
      </div>
    );
  }
  return (
    <div className="config-field">
      <label htmlFor={id}>{field.label}</label>
      {stored ? (
        <div className="input-row">
          <span className="secret-set">
            •••••••• saved
            {field.updated_by && ` by ${field.updated_by}`}
            {field.updated_at && `, ${formatDateTime(field.updated_at)}`}
          </span>
          <button type="button" className="btn btn-secondary" onClick={onChangeSecret}>
            Change
          </button>
          <button type="button" className="btn btn-secondary" onClick={onRemove}>
            Remove
          </button>
        </div>
      ) : (
        <input
          id={id}
          className={`input${field.secret || field.url ? " mono" : ""}`}
          type={field.secret ? "password" : "text"}
          autoComplete={field.secret ? "new-password" : "off"}
          placeholder={removed ? "Removed — saved on Save" : field.url ? "https://…" : undefined}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      {field.unreadable && (
        <span className="error-text">Saved with another secret key, so it cannot be read — enter it again.</span>
      )}
      {field.hint && <span className="sub">{field.hint}</span>}
    </div>
  );
}

export function ConfigEditor({
  focus,
  onClose,
  onSaved,
}: {
  focus: ConfigGroup | null;
  onClose: () => void;
  onSaved: (checks: ConnectionCheck[]) => void;
}) {
  const [fields, setFields] = useState<ConfigField[] | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [changing, setChanging] = useState<Set<string>>(new Set());
  const [removed, setRemoved] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const root = useRef<HTMLElement>(null);

  const reset = (loaded: ConfigField[]) => {
    setFields(loaded);
    setValues(Object.fromEntries(loaded.map((f) => [f.key, f.secret ? "" : (f.value ?? "")])));
    setChanging(new Set());
    setRemoved(new Set());
  };

  useEffect(() => {
    api.config().then(reset, (e) => setError(message(e)));
  }, []);

  useEffect(() => {
    if (!fields) return;
    const target = focus ? document.getElementById(`cfg-group-${focus}`) : root.current;
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [fields, focus]);

  const changes = (): Record<string, string | null> => {
    const out: Record<string, string | null> = {};
    for (const field of fields ?? []) {
      if (field.locked) continue;
      const value = values[field.key]?.trim() ?? "";
      if (field.secret) {
        if (removed.has(field.key)) out[field.key] = null;
        else if (value) out[field.key] = value;
      } else if (value !== (field.value ?? "")) {
        out[field.key] = value || null;
      }
    }
    return out;
  };

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    const pending = changes();
    setError(null);
    setResult(null);
    if (Object.keys(pending).length === 0) {
      setResult({ ok: true, text: "Nothing has changed." });
      return;
    }
    setSaving(true);
    try {
      const saved = await api.saveConfig(pending);
      reset(saved.fields);
      onSaved(saved.checks);
      const failed = saved.checks.filter((c) => c.status === "failed");
      setResult(
        failed.length
          ? {
              ok: false,
              text: `Saved and applied. ${failed.map((c) => `${c.name}: ${c.detail}`).join(" · ")}`,
            }
          : { ok: true, text: "Saved and applied. Every configured connection works." },
      );
    } catch (e) {
      setError(message(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="card config-editor" ref={root} aria-labelledby="config-title">
      <div className="card-head center">
        <h2 id="config-title">Connection settings</h2>
        <button type="button" className="btn btn-secondary" onClick={onClose}>
          Done
        </button>
      </div>
      <p className="sub card-note">
        Saved settings apply at once, without a restart, and are tested right away. Secrets are stored encrypted and
        never shown again. Settings from the deployment win and are locked here.
      </p>
      <ErrorAlert error={error} />
      {fields && (
        <form className="config-form" onSubmit={save}>
          {GROUPS.map((group) => (
            <fieldset key={group.key} id={`cfg-group-${group.key}`} className="config-group">
              <legend>{group.title}</legend>
              <p className="sub">{group.intro}</p>
              <div className="config-fields">
                {fields
                  .filter((f) => f.group === group.key)
                  .map((field) => (
                    <FieldInput
                      key={field.key}
                      field={field}
                      value={values[field.key] ?? ""}
                      changing={changing.has(field.key)}
                      removed={removed.has(field.key)}
                      onChange={(value) => setValues((v) => ({ ...v, [field.key]: value }))}
                      onChangeSecret={() => setChanging((s) => new Set(s).add(field.key))}
                      onRemove={() => setRemoved((s) => new Set(s).add(field.key))}
                    />
                  ))}
              </div>
            </fieldset>
          ))}
          {result && (
            <div className={`alert ${result.ok ? "alert-info" : "alert-error"}`} role="status">
              {result.text}
            </div>
          )}
          <div className="actions">
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? "Saving and testing…" : "Save and test"}
            </button>
            <button type="button" className="btn btn-secondary" disabled={saving} onClick={() => fields && reset(fields)}>
              Discard changes
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
