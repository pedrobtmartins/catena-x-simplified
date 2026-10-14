// Types mirror backend/src/catenax_simplified/api/schemas.py.

export interface Classification {
  standard: string;
  id: string;
  description: string | null;
}

export interface Part {
  global_asset_id: string;
  kind: "serial" | "batch";
  semantic_id: string;
  manufacturer_id: string | null;
  is_own: boolean;
  manufacturer_part_id: string | null;
  customer_part_id: string | null;
  name_at_manufacturer: string | null;
  name_at_customer: string | null;
  local_identifiers: Record<string, string>;
  production_date: string | null;
  country: string | null;
  site_ids: string[];
  classifications: Classification[];
  synced_at: string;
}

export interface PartListItem extends Part {
  parents_count: number;
  children_count: number;
}

export interface PartPage {
  items: PartListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface TreeNode {
  global_asset_id: string;
  part: Part | null;
  business_partner: string | null;
  quantity: number | null;
  unit: string | null;
  is_only_potential_parent: boolean;
  declared_in: string[];
}

export interface PartTree {
  part: Part;
  parents: TreeNode[];
  children: TreeNode[];
}

export interface SyncIssue {
  global_asset_id: string;
  semantic_id: string | null;
  message: string;
}

export interface SyncReport {
  id: number | null;
  started_at: string;
  finished_at: string | null;
  twins: number;
  parts: number;
  relation_sets: number;
  unsupported_submodels: number;
  removed_parts: number;
  complete: boolean;
  issues: SyncIssue[];
}

export interface Stats {
  own_parts: number;
  own_parts_by_kind: Record<string, number>;
  own_parts_by_semantic_id: Record<string, number>;
  supplier_links: number;
  suppliers: number;
  customer_links: number;
  customers: number;
}

export interface NotificationAssets {
  state: "not_configured" | "publishing" | "published" | "failed";
  message: string | null;
  at: string | null;
  asset_ids: string[];
}

export interface Health {
  status: string;
  own_bpnl: string;
  dtr_configured: boolean;
  edc_configured: boolean;
  can_send_notifications: boolean;
  dev_direct: boolean;
  notification_assets: NotificationAssets;
  dtr_url: string | null;
  sync_interval_seconds: number;
  supported_aspects: string[];
}

export interface Partner {
  bpnl: string;
  name: string | null;
  roles: ("supplier" | "customer")[];
  linked_twins: number;
  cached_parts: number;
  connector_address: string | null;
  connector_source: "api" | "settings" | null;
  last_sync_at: string | null;
  last_status: "ok" | "partial" | "failed" | "no_connector" | null;
  last_message: string | null;
  twins_found: number;
  twins_missing: number;
}

export interface PartnerSyncResult {
  bpnl: string;
  roles: string[];
  linked_twins: number;
  twins_found: number;
  twins_missing: number;
  removed_parts: number;
  status: string;
  issues: string[];
}

export interface PartnerSyncReport {
  started_at: string;
  finished_at: string | null;
  partners: PartnerSyncResult[];
}

export type NotificationType = "alert" | "investigation";
export type Severity = "MINOR" | "MAJOR" | "CRITICAL" | "LIFE-THREATENING";
export type Status = "CREATED" | "SENT" | "RECEIVED" | "ACKNOWLEDGED" | "ACCEPTED" | "DECLINED" | "CLOSED";
export const SEVERITIES: Severity[] = ["MINOR", "MAJOR", "CRITICAL", "LIFE-THREATENING"];

export interface Notification {
  id: number;
  notification_id: string;
  type: NotificationType;
  direction: "inbound" | "outbound";
  partner_bpnl: string;
  status: Status;
  severity: Severity;
  description: string | null;
  affected_items: string[];
  expected_response_by: string | null;
  related_message_id: string | null;
  forwarded_from_id: number | null;
  api_version: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface NotificationPage {
  items: Notification[];
  total: number;
  limit: number;
  offset: number;
}

export interface NotificationMessage {
  direction: "inbound" | "outbound";
  operation: "receive" | "update";
  message_id: string;
  status: Status | null;
  information: string | null;
  at: string;
}

export interface NotificationDetail extends Notification {
  items: { global_asset_id: string; part: Part | null }[];
  messages: NotificationMessage[];
  forwarded_from: Notification | null;
  forwarded_to: Notification[];
  actions: string[]; // "send" and/or target statuses
}

export interface NotificationSummary {
  inbound_open: number;
  inbound_new: number;
  outbound_open: number;
}

export interface Plan {
  type: NotificationType;
  recipients: Record<string, string[]>;
  unmatched: string[];
}

export interface ForwardPlan extends Plan {
  source_id: number;
  own_parts: string[];
}

export interface NotificationCreate {
  type: NotificationType;
  affected_items: string[];
  severity: Severity;
  description: string;
  expected_response_by?: string | null;
  forwarded_from?: number | null;
  send: boolean;
}

export interface NotificationQuery {
  direction?: "inbound" | "outbound";
  openOnly?: boolean;
  limit: number;
  offset: number;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      // keep the status text
    }
    throw new ApiError(response.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return response.json() as Promise<T>;
}

export interface PartQuery {
  search?: string;
  kind?: "serial" | "batch";
  aspectMajor?: number;
  limit: number;
  offset: number;
}

export const api = {
  health: () => request<Health>("/api/health"),
  stats: () => request<Stats>("/api/stats"),
  parts: (q: PartQuery) => {
    // The parts page lists own parts; partner parts appear in the tree of the part they belong to.
    const query = new URLSearchParams({ limit: String(q.limit), offset: String(q.offset), own_only: "true" });
    if (q.search) query.set("search", q.search);
    if (q.kind) query.set("kind", q.kind);
    if (q.aspectMajor) query.set("aspect_major", String(q.aspectMajor));
    return request<PartPage>(`/api/parts?${query}`);
  },
  tree: (id: string) => request<PartTree>(`/api/parts/${encodeURIComponent(id)}/tree`),
  sync: () => request<SyncReport>("/api/sync", { method: "POST" }),
  lastSync: () => request<SyncReport>("/api/sync/last"),
  syncRuns: (limit = 20) => request<{ items: SyncReport[] }>(`/api/sync/runs?limit=${limit}`),

  partners: () => request<Partner[]>("/api/partners"),
  updatePartner: (bpnl: string, update: { name?: string | null; connector_address?: string | null }) =>
    request<Partner>(`/api/partners/${encodeURIComponent(bpnl)}`, json("PUT", update)),
  syncPartners: (bpnl?: string) =>
    request<PartnerSyncReport>(`/api/partners/sync${bpnl ? `?bpnl=${encodeURIComponent(bpnl)}` : ""}`, {
      method: "POST",
    }),

  notifications: (q: NotificationQuery) => {
    const query = new URLSearchParams({ limit: String(q.limit), offset: String(q.offset) });
    if (q.direction) query.set("direction", q.direction);
    if (q.openOnly) query.set("open_only", "true");
    return request<NotificationPage>(`/api/notifications?${query}`);
  },
  notificationSummary: () => request<NotificationSummary>("/api/notifications/summary"),
  notification: (id: number) => request<NotificationDetail>(`/api/notifications/${id}`),
  plan: (type: NotificationType, affected_items: string[]) =>
    request<Plan>("/api/notifications/plan", json("POST", { type, affected_items })),
  forwardPlan: (id: number) => request<ForwardPlan>(`/api/notifications/${id}/forward-plan`),
  createNotifications: (body: NotificationCreate) =>
    request<Notification[]>("/api/notifications", json("POST", body)),
  sendNotification: (id: number) => request<Notification>(`/api/notifications/${id}/send`, { method: "POST" }),
  changeStatus: (id: number, status: Status, information?: string) =>
    request<Notification>(`/api/notifications/${id}/status`, json("POST", { status, information: information || null })),
};

function json(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

export const TYPE_LABEL: Record<NotificationType, string> = { alert: "Quality alert", investigation: "Investigation" };

export const STATUS_LABEL: Record<Status, string> = {
  CREATED: "Draft",
  SENT: "Sending",
  RECEIVED: "Received",
  ACKNOWLEDGED: "Acknowledged",
  ACCEPTED: "Accepted",
  DECLINED: "Declined",
  CLOSED: "Closed",
};

export function severityLabel(severity: Severity): string {
  return severity === "LIFE-THREATENING" ? "Life-threatening" : severity[0] + severity.slice(1).toLowerCase();
}

/** "urn:samm:io.catenax.serial_part:3.0.0#SerialPart" → { name: "SerialPart", version: "3.0.0", major: 3 } */
export function parseSemanticId(semanticId: string): { name: string; version: string; major: number | null } {
  const match = /:(\d+)\.(\d+)\.(\d+)(?:#(\w+))?$/.exec(semanticId);
  if (!match) return { name: semanticId, version: "", major: null };
  const name = match[4] ?? semanticId.split(":").slice(-2, -1)[0] ?? semanticId;
  return { name, version: `${match[1]}.${match[2]}.${match[3]}`, major: Number(match[1]) };
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "medium" });
}

/** "urn:uuid:aaaaaaaa-0000-4000-8000-000000000002" → "urn:uuid:aaaaaaaa-…-000000000002" */
export function shortId(id: string): string {
  const match = /^(urn:uuid:[0-9a-fA-F]{8})-.*-([0-9a-fA-F]{12})$/.exec(id);
  return match ? `${match[1]}-…-${match[2]}` : id;
}

export function localIdentifiers(part: Part): string {
  return Object.values(part.local_identifiers).join(", ");
}

export function syncState(report: SyncReport): "ok" | "warn" | "error" {
  if (!report.complete) return "error";
  return report.issues.length > 0 ? "warn" : "ok";
}
