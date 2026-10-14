// Small shared building blocks: chip groups and notification badges.
import { severityLabel, STATUS_LABEL, TYPE_LABEL, type NotificationType, type Severity, type Status } from "./api";

export function ChipGroup<T>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { label: string; value: T }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="chip-group" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.label}
          type="button"
          className="chip"
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function TypeBadge({ type }: { type: NotificationType }) {
  return <span className={`badge badge-type-${type}`}>{TYPE_LABEL[type]}</span>;
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <span className={`badge badge-sev-${severity.toLowerCase()}`}>{severityLabel(severity)}</span>;
}

export function StatusBadge({ status }: { status: Status }) {
  return <span className={`badge badge-status-${status.toLowerCase()}`}>{STATUS_LABEL[status]}</span>;
}

export function ErrorAlert({ error }: { error: string | null }) {
  return error ? (
    <div className="alert alert-error" role="alert">
      {error}
    </div>
  ) : null;
}
