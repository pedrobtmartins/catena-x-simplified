// Small shared building blocks: chip groups, notification badges, loading and empty states.
import type { ReactNode } from "react";
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

/** A grey bar standing in for content that is loading. */
export function Skeleton({ width, height }: { width?: number | string; height?: number | string }) {
  return <span className="skeleton" style={{ width, height }} aria-hidden="true" />;
}

/** Table rows with the table's shape while its data loads. */
export function SkeletonRows({ rows, cols }: { rows: number; cols: number }) {
  return (
    <>
      {Array.from({ length: rows }, (_, r) => (
        <tr key={r} className="skeleton-row" aria-hidden="true">
          {Array.from({ length: cols }, (_, c) => (
            <td key={c}>
              <Skeleton width={c === 0 ? "70%" : "55%"} />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

/** What an empty list means and what to do about it, inside a table. */
export function EmptyState({ cols, title, children }: { cols: number; title: string; children?: ReactNode }) {
  return (
    <tr className="empty-row">
      <td colSpan={cols}>
        <div className="empty-state">
          <strong>{title}</strong>
          {children && <div className="empty-body">{children}</div>}
        </div>
      </td>
    </tr>
  );
}
