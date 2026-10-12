import { useEffect, useState } from "react";
import { api, aspectLabel, type Part, type PartTree, type TreeNode } from "./api";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children ?? "—"}</dd>
    </>
  );
}

function PartFields({ part }: { part: Part }) {
  return (
    <dl className="fields">
      <Field label="Catena-X ID">
        <code>{part.global_asset_id}</code>
      </Field>
      <Field label="Kind">{part.kind}</Field>
      <Field label="Aspect model">{aspectLabel(part.semantic_id)}</Field>
      <Field label="Manufacturer">{part.manufacturer_id}</Field>
      <Field label="Manufacturer part ID">{part.manufacturer_part_id}</Field>
      <Field label="Customer part ID">{part.customer_part_id}</Field>
      <Field label="Name at manufacturer">{part.name_at_manufacturer}</Field>
      <Field label="Name at customer">{part.name_at_customer}</Field>
      <Field label="Local identifiers">
        {Object.entries(part.local_identifiers)
          .map(([k, v]) => `${k}: ${v}`)
          .join(", ") || null}
      </Field>
      <Field label="Production date">{part.production_date}</Field>
      <Field label="Country">{part.country}</Field>
      <Field label="Sites">{part.site_ids.join(", ") || null}</Field>
      <Field label="Classification">
        {part.classifications.map((c) => `${c.standard} ${c.id}`).join(", ") || null}
      </Field>
    </dl>
  );
}

function Relations({
  title,
  partnerLabel,
  nodes,
  onNavigate,
}: {
  title: string;
  partnerLabel: string;
  nodes: TreeNode[];
  onNavigate: (id: string) => void;
}) {
  return (
    <section>
      <h3>
        {title} <span className="muted">({nodes.length})</span>
      </h3>
      <table>
        <thead>
          <tr>
            <th>Catena-X ID</th>
            <th>Name</th>
            <th>{partnerLabel}</th>
            <th>Quantity</th>
            <th>Declared in</th>
          </tr>
        </thead>
        <tbody>
          {nodes.map((node) => (
            <tr
              key={node.global_asset_id}
              className={node.part ? "clickable" : undefined}
              onClick={node.part ? () => onNavigate(node.global_asset_id) : undefined}
            >
              <td>
                <code>{node.global_asset_id}</code>
              </td>
              <td>{node.part?.name_at_manufacturer ?? <span className="muted">not in cache</span>}</td>
              <td>{node.business_partner ?? "—"}</td>
              <td>{node.quantity !== null ? `${node.quantity} ${node.unit?.replace("unit:", "") ?? ""}` : "—"}</td>
              <td>
                {node.declared_in.join(", ")}
                {node.is_only_potential_parent && " (potential)"}
              </td>
            </tr>
          ))}
          {nodes.length === 0 && (
            <tr>
              <td colSpan={5} className="muted">
                None
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  );
}

export function PartDetail({ id, onNavigate }: { id: string; onNavigate: (id: string | null) => void }) {
  const [tree, setTree] = useState<PartTree | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setTree(null);
    setError(null);
    api.tree(id).then(setTree, (e: Error) => setError(e.message));
  }, [id]);

  return (
    <section>
      <button className="link" onClick={() => onNavigate(null)}>
        ← All parts
      </button>
      {error && <div className="error">{error}</div>}
      {tree && (
        <>
          <h2>{tree.part.name_at_manufacturer ?? tree.part.global_asset_id}</h2>
          <PartFields part={tree.part} />
          <Relations
            title="Used in (parents)"
            partnerLabel="Customer"
            nodes={tree.parents}
            onNavigate={onNavigate}
          />
          <Relations
            title="Built from (children)"
            partnerLabel="Supplier"
            nodes={tree.children}
            onNavigate={onNavigate}
          />
        </>
      )}
    </section>
  );
}
