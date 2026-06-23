"use client";

import type { TableField as TableSpec } from "@/lib/types";

interface Props {
  spec: TableSpec;
  value: string[][];
  onChange: (v: string[][]) => void;
}

export function TableField({ spec, value, onChange }: Props) {
  const cols = spec.columns?.length ? spec.columns : ["Item", "Value"];
  // Normalise to string[][] — stale state from a type conversion (or odd model
  // output) can hand us non-array rows, which would crash the cell spread below.
  const rows: string[][] = (Array.isArray(value) ? value : []).map((row) =>
    Array.isArray(row) ? row.map((cell) => (cell == null ? "" : String(cell))) : [],
  );

  const setCell = (r: number, c: number, val: string) => {
    const next = rows.map((row) => [...row]);
    while (next[r].length < cols.length) next[r].push("");
    next[r][c] = val;
    onChange(next);
  };
  const addRow = () => onChange([...rows, cols.map(() => "")]);
  const removeRow = (r: number) => onChange(rows.filter((_, i) => i !== r));

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs uppercase tracking-wide text-[var(--muted)]">{spec.label}</span>
      <div className="overflow-x-auto rounded-none border border-[var(--border)]">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-[var(--surface-elevated)]">
              {cols.map((c, i) => (
                <th key={i} className="text-left font-medium text-[var(--muted)] text-xs px-2 py-1.5 border-b border-[var(--border)]">{c}</th>
              ))}
              <th className="w-6 border-b border-[var(--border)]" />
            </tr>
          </thead>
          <tbody>
            {rows.map((row, r) => (
              <tr key={r} className="group">
                {cols.map((_, c) => (
                  <td key={c} className="border-b border-[var(--border)] p-0">
                    <input
                      value={row[c] ?? ""}
                      onChange={(e) => setCell(r, c, e.target.value)}
                      className="w-full bg-transparent px-2 py-1.5 text-sm focus:outline-none focus:bg-[var(--surface-elevated)]"
                    />
                  </td>
                ))}
                <td className="border-b border-[var(--border)] text-center">
                  <button type="button" onClick={() => removeRow(r)}
                    className="text-[var(--muted)] hover:text-[var(--danger)] text-xs opacity-0 group-hover:opacity-100" aria-label="Remove row">×</button>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={cols.length + 1} className="px-2 py-2 text-xs text-[var(--muted)] italic">No rows yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <button type="button" onClick={addRow}
        className="self-start text-xs text-[var(--muted)] hover:text-[var(--accent)] transition">+ Add row</button>
    </div>
  );
}
