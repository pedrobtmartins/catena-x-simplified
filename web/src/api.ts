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

export interface PartPage {
  items: Part[];
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

export interface SyncReport {
  started_at: string;
  finished_at: string | null;
  twins: number;
  parts: number;
  relation_sets: number;
  unsupported_submodels: number;
  removed_parts: number;
  complete: boolean;
  issues: { global_asset_id: string; semantic_id: string | null; message: string }[];
}

export interface Health {
  status: string;
  own_bpnl: string;
  dtr_configured: boolean;
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

export const api = {
  health: () => request<Health>("/api/health"),
  parts: (params: { search?: string; limit: number; offset: number }) => {
    const query = new URLSearchParams({ limit: String(params.limit), offset: String(params.offset) });
    if (params.search) query.set("search", params.search);
    return request<PartPage>(`/api/parts?${query}`);
  },
  tree: (id: string) => request<PartTree>(`/api/parts/${encodeURIComponent(id)}/tree`),
  sync: () => request<SyncReport>("/api/sync", { method: "POST" }),
  lastSync: () => request<SyncReport>("/api/sync/last"),
};

/** "urn:samm:io.catenax.serial_part:3.0.0#SerialPart" → "SerialPart 3.0.0" */
export function aspectLabel(semanticId: string): string {
  const match = /:([\d.]+)#(\w+)$/.exec(semanticId);
  return match ? `${match[2]} ${match[1]}` : semanticId;
}
