"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Automation, Component, ComponentType, ModuleConfig, StoredModule } from "@/lib/types";
import { api } from "@/lib/api";
import { COMPONENT_TYPES, makeComponent } from "@/lib/componentFactory";
import { ACCENTS, ACCENT_NAMES, ICON_CHOICES, resolveAccent, resolveIconName } from "@/lib/theme";
import { Icon } from "./Icon";

interface Props {
  module: StoredModule;
  onChange: (m: StoredModule) => void;
  onClose: () => void;
  onRefine: (id: string) => void;
  onDelete: (id: string) => void;
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

export function Inspector({ module, onChange, onClose, onRefine, onDelete, onDuplicate, onArchive }: Props) {
  const [draft, setDraft] = useState<Draft>(() => fromModule(module));
  const [dragId, setDragId] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

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

  const persist = useCallback(
    (d: Draft, delay: number) => {
      if (timer.current) window.clearTimeout(timer.current);
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
      timer.current = window.setTimeout(async () => {
        try {
          const saved = await api.patchModule(module.id, config);
          onChange(saved);
        } catch (err) {
          console.error("Failed to persist inspector change", err);
        }
      }, delay);
    },
    [module.id, module.config, onChange],
  );

  const update = useCallback(
    (mutate: (d: Draft) => Draft, immediate = false) => {
      setDraft((prev) => {
        const next = mutate(prev);
        persist(next, immediate ? 0 : 400);
        return next;
      });
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
          <span className="text-[10px] uppercase tracking-wide text-[var(--muted)]">Colour</span>
          <div className="flex flex-wrap gap-1.5">
            {ACCENT_NAMES.map((name) => (
              <button key={name} type="button" onClick={() => update((d) => ({ ...d, accent: name }), true)}
                className="w-5 h-5 rounded-full transition hover:scale-110"
                style={{ background: ACCENTS[name].accent, outline: (draft.accent ?? theme.name) === name ? "2px solid var(--foreground)" : "none", outlineOffset: "1px" }}
                aria-label={`Set colour ${name}`} title={name} />
            ))}
          </div>
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
              <select
                value={c.type}
                onChange={(e) => update((d) => ({ ...d, components: d.components.map((x) => x.id === c.id ? convertType(x, e.target.value as ComponentType) : x) }), true)}
                className="bg-[var(--surface)] border border-[var(--border)] rounded text-xs px-1.5 py-1 text-[var(--muted)] ml-4"
                aria-label="Field type"
              >
                {COMPONENT_TYPES.map((t) => <option key={t.type} value={t.type}>{t.label}</option>)}
              </select>
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
                <select value={a.when_id} onChange={(e) => update((d) => ({ ...d, automations: d.automations.map((x) => x.id === a.id ? { ...x, when_id: e.target.value } : x) }), true)}
                  className="bg-[var(--surface)] border border-[var(--border)] rounded px-1 py-0.5 max-w-[90px]">
                  {draft.components.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
                </select>
                <select value={a.when} onChange={(e) => update((d) => ({ ...d, automations: d.automations.map((x) => x.id === a.id ? { ...x, when: e.target.value as Automation["when"] } : x) }), true)}
                  className="bg-[var(--surface)] border border-[var(--border)] rounded px-1 py-0.5">
                  <option value="checked">is checked</option>
                  <option value="changes">changes</option>
                  <option value="over">goes over</option>
                  <option value="under">goes under</option>
                </select>
                {(a.when === "over" || a.when === "under") && (
                  <input type="number" value={a.when_value ?? ""} onChange={(e) => update((d) => ({ ...d, automations: d.automations.map((x) => x.id === a.id ? { ...x, when_value: e.target.value === "" ? null : Number(e.target.value) } : x) }))}
                    className="w-14 bg-[var(--surface)] border border-[var(--border)] rounded px-1 py-0.5" placeholder="0" />
                )}
              </div>
              <div className="flex items-center gap-1 flex-wrap">
                <span className="text-[var(--muted)]">then</span>
                <select value={a.then} onChange={(e) => update((d) => ({ ...d, automations: d.automations.map((x) => x.id === a.id ? { ...x, then: e.target.value as Automation["then"] } : x) }), true)}
                  className="bg-[var(--surface)] border border-[var(--border)] rounded px-1 py-0.5">
                  <option value="increment">add 1 to</option>
                  <option value="flag">flag red</option>
                </select>
                <select value={a.then_id} onChange={(e) => update((d) => ({ ...d, automations: d.automations.map((x) => x.id === a.id ? { ...x, then_id: e.target.value } : x) }), true)}
                  className="bg-[var(--surface)] border border-[var(--border)] rounded px-1 py-0.5 max-w-[90px]">
                  {draft.components.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
                </select>
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
          className="w-full rounded-md bg-[var(--accent)] text-[var(--accent-fg)] px-3 py-1.5 text-sm font-medium hover:brightness-110 transition">✦ Edit with AI</button>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => onDuplicate(module.id)}
            className="flex-1 rounded-md border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--muted)] hover:text-[var(--foreground)] transition">Duplicate</button>
          <button type="button" onClick={() => onArchive(module.id)}
            className="flex-1 rounded-md border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--muted)] hover:text-[var(--foreground)] transition">Archive</button>
          <button type="button" onClick={() => onDelete(module.id)}
            className="flex-1 rounded-md border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--muted)] hover:text-[var(--danger)] hover:border-[var(--danger)] transition">Delete</button>
        </div>
      </div>
    </aside>
  );
}
