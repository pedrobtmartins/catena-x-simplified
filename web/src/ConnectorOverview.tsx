// Overview of all partners' connectors by their last health check; each card filters the table.
import { formatDateTime, type CheckStatus, type Partner } from "./api";

// "unchecked": never checked. The filter value null shows every partner.
export type HealthFilter = CheckStatus | "unchecked" | null;

export function healthOf(partner: Partner): Exclude<HealthFilter, null> {
  return partner.last_check?.status ?? "unchecked";
}

const CARDS: { value: Exclude<HealthFilter, null>; label: string; note: string; tone?: string }[] = [
  { value: "healthy", label: "Healthy", note: "Last check passed", tone: "ok" },
  { value: "degraded", label: "Degraded", note: "With warnings", tone: "warn" },
  { value: "failed", label: "Failed", note: "Last check failed", tone: "error" },
  { value: "skipped", label: "Skipped", note: "No EDC (development mode)" },
  { value: "unchecked", label: "Not checked", note: "Never checked" },
];

function latest(partners: Partner[]): string | null {
  const times = partners.flatMap((p) => (p.last_check ? [p.last_check.finished_at] : [])).sort();
  return times[times.length - 1] ?? null;
}

export function ConnectorOverview({
  partners,
  filter,
  onFilter,
}: {
  partners: Partner[];
  filter: HealthFilter;
  onFilter: (filter: HealthFilter) => void;
}) {
  const withConnector = partners.filter((p) => p.connector_address).length;
  const last = latest(partners);
  const cards = CARDS.map((card) => {
    const members = partners.filter((p) => healthOf(p) === card.value);
    return { ...card, members };
  }).filter((card) => card.value !== "skipped" || card.members.length > 0);

  const note = (card: (typeof cards)[number]) => {
    if (card.value === "unchecked") {
      const noAddress = card.members.filter((p) => !p.connector_address).length;
      return noAddress ? `${noAddress} without a DSP address` : card.note;
    }
    return card.note;
  };

  return (
    <div className="stats connector-overview" role="group" aria-label="Connector health">
      <button
        type="button"
        className="stat stat-filter"
        aria-pressed={filter === null}
        title={last ? `Last check ${formatDateTime(last)}` : "No check recorded yet"}
        onClick={() => onFilter(null)}
      >
        <span className="overline">Connectors</span>
        <span className="stat-value">{partners.length}</span>
        <span className="stat-note">
          {withConnector} with a DSP address
        </span>
      </button>
      {cards.map((card) => (
        <button
          key={card.value}
          type="button"
          className={`stat stat-filter${card.tone && card.members.length ? ` stat-${card.tone}` : ""}`}
          aria-pressed={filter === card.value}
          title={filter === card.value ? "Show all partners" : `Show only ${card.label.toLowerCase()} partners`}
          onClick={() => onFilter(filter === card.value ? null : card.value)}
        >
          <span className="overline">{card.label}</span>
          <span className="stat-value">{card.members.length}</span>
          <span className="stat-note">{note(card)}</span>
        </button>
      ))}
    </div>
  );
}
