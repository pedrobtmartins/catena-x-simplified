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

export interface Health {
  status: string;
  own_bpnl: string;
  dtr_configured: boolean;
  dtr_url: string | null;
  sync_interval_seconds: number;
  supported_aspects: string[];
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
    const query = new URLSearchParams({ limit: String(q.limit), offset: String(q.offset) });
    if (q.search) query.set("search", q.search);
    if (q.kind) query.set("kind", q.kind);
    if (q.aspectMajor) query.set("aspect_major", String(q.aspectMajor));
    return request<PartPage>(`/api/parts?${query}`);
  },
  tree: (id: string) => request<PartTree>(`/api/parts/${encodeURIComponent(id)}/tree`),
  sync: () => request<SyncReport>("/api/sync", { method: "POST" }),
  lastSync: () => request<SyncReport>("/api/sync/last"),
  syncRuns: (limit = 20) => request<{ items: SyncReport[] }>(`/api/sync/runs?limit=${limit}`),
};

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
