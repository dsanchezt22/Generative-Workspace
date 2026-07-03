"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Automation, Component, ComponentType, ModuleConfig, StoredModule } from "@/lib/types";
import { COMPONENT_TYPES, makeComponent } from "@/lib/componentFactory";
import { ICON_CHOICES, resolveAccent, resolveIconName } from "@/lib/theme";
import { Icon } from "./Icon";
import { Select } from "./Select";
import { FieldOptions } from "./FieldOptions";

interface Props {
  module: StoredModule;
  onCommit: (id: string, config: ModuleConfig, delay?: number) => void;
  onClose: () => void;
  onRefine: (id: string) => void;
  onDuplicate: (id: string) => void;
  onArchive: (id: string) => void;
}

interface Draft {
  title: string;
  components: Component[];
  accent?: string | null;
  icon?: string | null;
  density?: "comfortable" | "compact" | null;
  summary_component_id?: string | null;
  automations: Automation[];
  columns: number;
}

function convertType(c: Component, type: ComponentType): Component {
  if (c.type === type) return c;
  return { ...makeComponent(type, c.label), id: c.id };
}

export function Inspector({ module, onCommit, onClose, onRefine, onDuplicate, onArchive }: Props) {
  const [draft, setDraft] = useState<Draft>(() => fromModule(module));
  // Always-fresh handle on `draft` so `update` can compute the next draft
  // WITHOUT doing so inside the setDraft functional updater — that kept the
  // side-effecting persist() out of the reducer, where StrictMode's double
  // invoke would otherwise fire it twice (7d).
  const draftRef = useRef(draft);
  useEffect(() => { draftRef.current = draft; }, [draft]);
  const [dragId, setDragId] = useState<string | null>(null);
  // Field ids whose type changed — their stored value is from the old type and
  // is dropped on the next save so the new renderer starts from a clean default.
  const resetIds = useRef<Set<string>>(new Set());

  useEffect(() => {
    setDraft(fromModule(module));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [module.id]);

  function fromModule(m: StoredModule): Draft {
    return {
      title: m.config.title,
      components: m.config.components,
      accent: m.config.accent,
      icon: m.config.icon,
      density: m.config.density,
      summary_component_id: m.config.summary_component_id,
      automations: m.config.automations ?? [],
      columns: m.config.columns ?? 1,
    };
  }

  // Build the full config from the draft and commit it upward. The single saver
  // owns debouncing/coalescing/retry — the inspector no longer PATCHes directly.
  // `delay` (0 for structural edits, 400 for typing) is forwarded to the saver.
  const persist = useCallback(
    (d: Draft, delay: number) => {
      const config: ModuleConfig = {
        ...module.config,
        title: d.title,
        components: d.components,
        accent: d.accent,
        icon: d.icon,
        density: d.density,
        summary_component_id: d.summary_component_id,
        automations: d.automations,
        columns: d.columns,
      };
      if (resetIds.current.size) {
        const state = { ...(module.config.state ?? {}) };
        for (const id of resetIds.current) delete state[id];
        config.state = state;
        resetIds.current.clear();
      }
      onCommit(module.id, config, delay);
    },
    [module.id, module.config, onCommit],
  );

  const update = useCallback(
    (mutate: (d: Draft) => Draft, immediate = false) => {
      // Compute next from the fresh ref, set it, THEN persist — persist stays
      // outside the setDraft updater so it can't double-fire under StrictMode.
      const next = mutate(draftRef.current);
      setDraft(next);
      persist(next, immediate ? 0 : 400);
    },
    [persist],
  );

  const theme = resolveAccent(draft.accent, draft.title);
  const iconName = resolveIconName(draft.icon, draft.title);

  const seg = "flex-1 text-xs px-2 py-1 rounded-md transition capitalize";
  const segOn = "bg-[var(--accent)] text-[var(--accent-fg)]";
  const segOff = "text-[var(--muted)] hover:text-[var(--foreground)]";

  return (
    <aside className="fixed top-0 right-0 h-screen w-[320px] max-w-[85vw] z-30 bg-[var(--surface)] border-l border-[var(--border)] shadow-2xl shadow-black/30 flex flex-col animate-slide-right"
      style={{ ["--accent" as string]: theme.accent, ["--accent-fg" as string]: theme.accentFg } as React.CSSProperties}>
      <header className="flex items-center gap-2 px-4 h-14 border-b border-[var(--border)] shrink-0">
        <span className="leading-none" style={{ color: "var(--accent)" }}><Icon name={iconName} size={18} /></span>
        <span className="text-sm font-semibold tracking-tight truncate flex-1">{draft.title || "Untitled"}</span>
        <button type="button" onClick={onClose} aria-label="Close inspector"
          className="text-[var(--muted)] hover:text-[var(--foreground)] w-6 h-6 grid place-items-center rounded">✕</button>
      </header>

      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-5">
        {/* Name */}
        <section className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase tracking-wide text-[var(--muted)]">Name</label>
          <input
            value={draft.title}
            onChange={(e) => update((d) => ({ ...d, title: e.target.value }))}
            className="rounded-md border border-[var(--border)] bg-[var(--surface-elevated)] px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40"
            aria-label="Module name"
          />
        </section>

        {/* Look */}
        <section className="flex flex-col gap-2.5">
          <span className="text-[10px] uppercase tracking-wide text-[var(--muted)] mt-1">Icon</span>
          <div className="flex flex-wrap gap-1">
            {ICON_CHOICES.map((n) => (
              <button key={n} type="button" onClick={() => update((d) => ({ ...d, icon: n }), true)}
                className={`w-7 h-7 grid place-items-center rounded transition hover:bg-[var(--surface-elevated)] ${iconName === n ? "ring-1 ring-[var(--accent)] bg-[var(--surface-elevated)] text-[var(--accent)]" : "text-[var(--muted)]"}`}
                aria-label={`Set icon ${n}`}><Icon name={n} size={16} /></button>
            ))}
          </div>
          <span className="text-[10px] uppercase tracking-wide text-[var(--muted)] mt-1">Density</span>
          <div className="flex gap-1 rounded-lg bg-[var(--surface-elevated)] p-1">
            {(["comfortable", "compact"] as const).map((dn) => (
              <button key={dn} type="button" onClick={() => update((d) => ({ ...d, density: dn }), true)}
                className={`${seg} ${(draft.density ?? "comfortable") === dn ? segOn : segOff}`}>{dn}</button>
            ))}
          </div>
          <span className="text-[10px] uppercase tracking-wide text-[var(--muted)] mt-1">Layout</span>
          <div className="flex gap-1 rounded-lg bg-[var(--surface-elevated)] p-1">
            {[1, 2].map((n) => (
              <button key={n} type="button" onClick={() => update((d) => ({ ...d, columns: n }), true)}
                className={`${seg} ${(draft.columns ?? 1) === n ? segOn : segOff}`}>{n === 1 ? "1 column" : "2 columns"}</button>
            ))}
          </div>
        </section>

        {/* Fields */}
        <section className="flex flex-col gap-2">
          <span className="text-[10px] uppercase tracking-wide text-[var(--muted)]">Building blocks</span>
          {draft.components.map((c) => (
            <div
              key={c.id}
              draggable
              onDragStart={() => setDragId(c.id)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => {
                if (!dragId || dragId === c.id) return;
                update((d) => {
                  const list = d.components.filter((x) => x.id !== dragId);
                  const idx = list.findIndex((x) => x.id === c.id);
                  const moved = d.components.find((x) => x.id === dragId)!;
                  list.splice(idx, 0, moved);
                  return { ...d, components: list };
                }, true);
                setDragId(null);
              }}
              className="rounded-md border border-[var(--border)] bg-[var(--surface-elevated)] px-2 py-2 flex flex-col gap-1.5"
            >
              <div className="flex items-center gap-1.5">
                <span className="cursor-grab text-[var(--muted)] text-xs select-none" title="Drag to reorder">⠿</span>
                <input
                  value={c.label}
                  onChange={(e) => update((d) => ({ ...d, components: d.components.map((x) => x.id === c.id ? { ...x, label: e.target.value } : x) }))}
                  className="flex-1 min-w-0 bg-transparent text-sm focus:outline-none border-b border-transparent focus:border-[var(--accent)]"
                  aria-label="Field label"
                />
                <button type="button"
                  onClick={() => update((d) => ({ ...d, components: d.components.filter((x) => x.id !== c.id), summary_component_id: d.summary_component_id === c.id ? null : d.summary_component_id }), true)}
                  className="text-[var(--muted)] hover:text-[var(--danger)] text-xs shrink-0" aria-label={`Remove ${c.label}`}>✕</button>
              </div>
              <div className="ml-4 flex items-center gap-1.5 flex-wrap">
                <Select
                  value={c.type}
                  ariaLabel="Field type"
                  options={COMPONENT_TYPES.map((t) => ({ value: t.type, label: t.label }))}
                  onChange={(v) => {
                    if (v !== c.type) resetIds.current.add(c.id);
                    update((d) => ({ ...d, components: d.components.map((x) => x.id === c.id ? convertType(x, v as ComponentType) : x) }), true);
                  }}
                />
                {draft.columns === 2 && (
                  <Select
                    value={c.span ?? "auto"}
                    ariaLabel="Field width"
                    options={[{ value: "auto", label: "Auto width" }, { value: "half", label: "Half width" }, { value: "full", label: "Full width" }]}
                    onChange={(v) => update((d) => ({ ...d, components: d.components.map((x) => x.id === c.id ? { ...x, span: v === "auto" ? null : (v as "half" | "full") } : x) }), true)}
                  />
                )}
              </div>
              <FieldOptions
                c={c}
                components={draft.components}
                onPatch={(patch) => update((d) => ({ ...d, components: d.components.map((x) => x.id === c.id ? ({ ...x, ...patch } as Component) : x) }), true)}
              />
            </div>
          ))}
          {draft.components.length === 0 && <p className="text-xs text-[var(--muted)] italic">No fields. Add one below.</p>}
          <div className="flex flex-wrap gap-1.5 pt-1">
            {COMPONENT_TYPES.map((t) => (
              <button key={t.type} type="button"
                onClick={() => update((d) => ({ ...d, components: [...d.components, makeComponent(t.type)] }), true)}
                className="rounded-md border border-[var(--border)] px-2 py-1 text-xs hover:border-[var(--accent)] hover:text-[var(--accent)] transition">+ {t.label}</button>
            ))}
          </div>
        </section>

        {/* Automations */}
        <section className="flex flex-col gap-2">
          <span className="text-[10px] uppercase tracking-wide text-[var(--muted)]">Automations</span>
          {draft.automations.map((a) => (
            <div key={a.id} className="rounded-md border border-[var(--border)] bg-[var(--surface-elevated)] p-2 flex flex-col gap-1.5 text-xs">
              <div className="flex items-center gap-1 flex-wrap">
                <span className="text-[var(--muted)]">When</span>
                <Select value={a.when_id} ariaLabel="When field" className="max-w-[96px]"
                  options={draft.components.map((c) => ({ value: c.id, label: c.label }))}
                  onChange={(v) => update((d) => ({ ...d, automations: d.automations.map((x) => x.id === a.id ? { ...x, when_id: v } : x) }), true)} />
                <Select value={a.when} ariaLabel="Condition"
                  options={[{ value: "checked", label: "is checked" }, { value: "changes", label: "changes" }, { value: "over", label: "goes over" }, { value: "under", label: "goes under" }]}
                  onChange={(v) => update((d) => ({ ...d, automations: d.automations.map((x) => x.id === a.id ? { ...x, when: v as Automation["when"] } : x) }), true)} />
                {(a.when === "over" || a.when === "under") && (
                  <input type="number" value={a.when_value ?? ""} onChange={(e) => update((d) => ({ ...d, automations: d.automations.map((x) => x.id === a.id ? { ...x, when_value: e.target.value === "" ? null : Number(e.target.value) } : x) }))}
                    className="w-14 bg-[var(--surface)] border border-[var(--border)] rounded px-1 py-0.5" placeholder="0" />
                )}
              </div>
              <div className="flex items-center gap-1 flex-wrap">
                <span className="text-[var(--muted)]">then</span>
                <Select value={a.then} ariaLabel="Action"
                  options={[{ value: "increment", label: "add 1 to" }, { value: "flag", label: "flag red" }]}
                  onChange={(v) => update((d) => ({ ...d, automations: d.automations.map((x) => x.id === a.id ? { ...x, then: v as Automation["then"] } : x) }), true)} />
                <Select value={a.then_id} ariaLabel="Target field" className="max-w-[96px]"
                  options={draft.components.map((c) => ({ value: c.id, label: c.label }))}
                  onChange={(v) => update((d) => ({ ...d, automations: d.automations.map((x) => x.id === a.id ? { ...x, then_id: v } : x) }), true)} />
                <button type="button" onClick={() => update((d) => ({ ...d, automations: d.automations.filter((x) => x.id !== a.id) }), true)}
                  className="ml-auto text-[var(--muted)] hover:text-[var(--danger)]" aria-label="Remove rule">✕</button>
              </div>
            </div>
          ))}
          {draft.components.length > 0 && (
            <button type="button"
              onClick={() => update((d) => {
                const first = d.components[0]?.id ?? "";
                const num = d.components.find((c) => ["number_input", "kpi", "slider", "ring"].includes(c.type))?.id ?? first;
                return { ...d, automations: [...d.automations, { id: `r_${Date.now()}`, when_id: first, when: "checked", then: "increment", then_id: num }] };
              }, true)}
              className="self-start rounded-md border border-[var(--border)] px-2 py-1 text-xs hover:border-[var(--accent)] hover:text-[var(--accent)] transition">+ Add rule</button>
          )}
        </section>
      </div>

      <div className="p-3 border-t border-[var(--border)] flex flex-col gap-2 shrink-0">
        <button type="button" onClick={() => onRefine(module.id)}
          className="press w-full rounded-md bg-[var(--accent)] text-[var(--accent-fg)] px-3 py-1.5 text-sm font-medium hover:brightness-110 transition">✦ Edit with AI</button>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => onDuplicate(module.id)}
            className="flex-1 rounded-md border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--muted)] hover:text-[var(--foreground)] transition">Duplicate</button>
          <button type="button" onClick={() => onArchive(module.id)} aria-label="Archive"
            className="flex-1 rounded-md border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--muted)] hover:text-[var(--foreground)] transition">Archive</button>
        </div>
      </div>
    </aside>
  );
}
