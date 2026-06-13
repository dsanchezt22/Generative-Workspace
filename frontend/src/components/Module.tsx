"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  Component,
  ComponentType,
  ModuleConfig,
  StoredModule,
} from "@/lib/types";
import { api } from "@/lib/api";
import { deriveSummary } from "@/lib/summary";
import { COMPONENT_TYPES, makeComponent } from "@/lib/componentFactory";
import { CheckboxField } from "./primitives/CheckboxField";
import { ListFieldComponent } from "./primitives/ListFieldComponent";
import { NumberInputField } from "./primitives/NumberInputField";
import { ProgressBarField } from "./primitives/ProgressBarField";
import { SliderField } from "./primitives/SliderField";
import { TextInputField } from "./primitives/TextInputField";

interface Props {
  module: StoredModule;
  onChange: (updated: StoredModule) => void;
  onDelete: (id: string) => void;
  onUndo: (id: string) => void;
  onSelectForRefine: (id: string) => void;
  onDragStart: (e: React.PointerEvent, moduleId: string) => void;
  onResizeStart: (e: React.PointerEvent, moduleId: string) => void;
}

interface Draft {
  title: string;
  components: Component[];
  summary_component_id?: string | null;
}

export function Module({ module, onChange, onDelete, onUndo, onSelectForRefine, onDragStart, onResizeStart }: Props) {
  const [state, setState] = useState<Record<string, unknown>>(
    module.config.state ?? {},
  );
  const [editing, setEditing] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  // While editing, the title/components live in a local draft so typing never
  // round-trips through the network (which would fight the cursor).
  const [draft, setDraft] = useState<Draft | null>(null);
  const persistTimer = useRef<number | null>(null);

  useEffect(() => {
    setState(module.config.state ?? {});
  }, [module.id, module.config.state]);

  const persistConfig = useCallback(
    async (config: ModuleConfig) => {
      try {
        const saved = await api.patchModule(module.id, config);
        onChange(saved);
      } catch (err) {
        console.error("Failed to persist module config", err);
      }
    },
    [module.id, onChange],
  );

  const schedulePersist = useCallback(
    (config: ModuleConfig, delay = 400) => {
      if (persistTimer.current) window.clearTimeout(persistTimer.current);
      persistTimer.current = window.setTimeout(() => {
        void persistConfig(config);
      }, delay);
    },
    [persistConfig],
  );

  // --- Data entry (view mode) ---
  const setField = useCallback(
    (id: string, value: unknown) => {
      setState((prev) => {
        const next = { ...prev, [id]: value };
        schedulePersist({ ...module.config, state: next });
        return next;
      });
    },
    [module.config, schedulePersist],
  );

  // --- Structure edits (edit mode, against local draft) ---
  const updateDraft = useCallback(
    (mutate: (d: Draft) => Draft, immediate = false) => {
      setDraft((prev) => {
        if (!prev) return prev;
        const next = mutate(prev);
        const config: ModuleConfig = {
          ...module.config,
          state,
          title: next.title,
          components: next.components,
          summary_component_id: next.summary_component_id,
        };
        schedulePersist(config, immediate ? 0 : 400);
        return next;
      });
    },
    [module.config, state, schedulePersist],
  );

  const enterEdit = () => {
    setDraft({
      title: module.config.title,
      components: module.config.components,
      summary_component_id: module.config.summary_component_id,
    });
    setEditing(true);
  };

  const exitEdit = () => {
    if (persistTimer.current) {
      window.clearTimeout(persistTimer.current);
      persistTimer.current = null;
    }
    if (draft) {
      void persistConfig({
        ...module.config,
        state,
        title: draft.title,
        components: draft.components,
        summary_component_id: draft.summary_component_id,
      });
    }
    setEditing(false);
    setDraft(null);
  };

  const renderComponent = (c: Component) => {
    switch (c.type) {
      case "text_input":
        return (
          <TextInputField
            key={c.id}
            spec={c}
            value={(state[c.id] as string) ?? ""}
            onChange={(v) => setField(c.id, v)}
          />
        );
      case "number_input":
        return (
          <NumberInputField
            key={c.id}
            spec={c}
            value={(state[c.id] as number | "") ?? ""}
            onChange={(v) => setField(c.id, v)}
          />
        );
      case "checkbox":
        return (
          <CheckboxField
            key={c.id}
            spec={c}
            value={Boolean(state[c.id])}
            onChange={(v) => setField(c.id, v)}
          />
        );
      case "slider":
        return (
          <SliderField
            key={c.id}
            spec={c}
            value={(state[c.id] as number) ?? c.min}
            onChange={(v) => setField(c.id, v)}
          />
        );
      case "progress_bar": {
        const sourceVal = c.bound_to
          ? (state[c.bound_to] as number) ?? 0
          : (state[c.id] as number) ?? 0;
        return <ProgressBarField key={c.id} spec={c} value={sourceVal} />;
      }
      case "list":
        return (
          <ListFieldComponent
            key={c.id}
            spec={c}
            value={(state[c.id] as string[]) ?? []}
            onChange={(v) => setField(c.id, v)}
          />
        );
    }
  };

  const renderEditRow = (c: Component) => (
    <div
      key={c.id}
      className="flex items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--surface-elevated)] px-2.5 py-2"
    >
      <span className="text-[10px] uppercase tracking-wide text-[var(--muted)] font-mono w-20 shrink-0">
        {c.type.replace("_", " ")}
      </span>
      <input
        value={c.label}
        onChange={(e) =>
          updateDraft((d) => ({
            ...d,
            components: d.components.map((x) =>
              x.id === c.id ? { ...x, label: e.target.value } : x,
            ),
          }))
        }
        className="flex-1 bg-transparent text-sm focus:outline-none border-b border-transparent focus:border-[var(--accent)]"
        aria-label={`Rename ${c.label}`}
      />
      <button
        type="button"
        onClick={() =>
          updateDraft(
            (d) => ({
              ...d,
              components: d.components.filter((x) => x.id !== c.id),
              summary_component_id:
                d.summary_component_id === c.id ? null : d.summary_component_id,
            }),
            true,
          )
        }
        className="text-[var(--muted)] hover:text-[var(--danger)] transition text-sm shrink-0"
        aria-label={`Remove ${c.label}`}
      >
        Remove
      </button>
    </div>
  );

  const addComponent = (type: ComponentType) =>
    updateDraft(
      (d) => ({ ...d, components: [...d.components, makeComponent(type)] }),
      true,
    );

  const { layout } = module.config;
  const iconBtn =
    "text-xs text-[var(--muted)] hover:text-[var(--foreground)] transition px-1.5 h-6 flex items-center justify-center rounded";

  const components = editing && draft ? draft.components : module.config.components;
  const title = editing && draft ? draft.title : module.config.title;

  return (
    <div
      className="absolute rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-lg shadow-black/30 flex flex-col"
      style={{
        left: layout.x,
        top: layout.y,
        width: layout.width,
        minHeight: collapsed ? undefined : layout.height,
      }}
    >
      <div
        className="absolute bottom-1 right-1 w-4 h-4 cursor-se-resize opacity-0 hover:opacity-100 transition-opacity flex items-end justify-end"
        style={{ touchAction: "none" }}
        onPointerDown={(e) => onResizeStart(e, module.id)}
        aria-label="Resize module"
        title="Resize"
      >
        <svg width="8" height="8" viewBox="0 0 8 8" fill="none" aria-hidden>
          <circle cx="6" cy="6" r="1" fill="currentColor" className="text-[var(--muted)]"/>
          <circle cx="3" cy="6" r="1" fill="currentColor" className="text-[var(--muted)]"/>
          <circle cx="6" cy="3" r="1" fill="currentColor" className="text-[var(--muted)]"/>
        </svg>
      </div>
      <div className="flex items-center gap-1.5 px-3 py-3 border-b border-[var(--border)]">
        <button
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          className={iconBtn}
          aria-label={collapsed ? "Expand" : "Collapse"}
        >
          <span
            className="inline-block transition-transform text-sm"
            style={{ transform: collapsed ? "rotate(-90deg)" : "none" }}
          >
            ▾
          </span>
        </button>

        {editing ? (
          <input
            value={title}
            onChange={(e) =>
              updateDraft((d) => ({ ...d, title: e.target.value }))
            }
            className="flex-1 bg-transparent text-sm font-semibold tracking-tight focus:outline-none border-b border-[var(--accent)]"
            aria-label="Module title"
          />
        ) : (
          <h3
            className="flex-1 text-sm font-semibold tracking-tight cursor-grab active:cursor-grabbing select-none truncate"
            onPointerDown={(e) => onDragStart(e, module.id)}
            title={title}
          >
            {title}
          </h3>
        )}

        <button
          type="button"
          onClick={() => onUndo(module.id)}
          className={iconBtn}
          aria-label="Undo last change"
          title="Undo last change"
        >
          ↶
        </button>
        <button
          type="button"
          onClick={() => onSelectForRefine(module.id)}
          className={iconBtn}
          aria-label="Refine with AI"
          title="Refine with AI"
        >
          ✦
        </button>
        <button
          type="button"
          onClick={() => (editing ? exitEdit() : enterEdit())}
          className={`${iconBtn} ${editing ? "text-[var(--accent)]" : ""}`}
          aria-label={editing ? "Done editing" : "Edit module"}
        >
          {editing ? "Done" : "Edit"}
        </button>
        <button
          type="button"
          onClick={() => onDelete(module.id)}
          className={`${iconBtn} hover:text-[var(--danger)]`}
          aria-label="Delete module"
        >
          ✕
        </button>
      </div>

      {collapsed ? (
        <div className="px-4 py-3 text-xs text-[var(--muted)] font-mono">
          {deriveSummary(module.config, state)}
        </div>
      ) : editing ? (
        <div className="p-3 flex flex-col gap-2">
          {components.map(renderEditRow)}
          {components.length === 0 && (
            <p className="text-xs text-[var(--muted)] italic px-1">
              No fields. Add one below.
            </p>
          )}
          <div className="flex flex-wrap gap-1.5 pt-2 border-t border-[var(--border)] mt-1">
            <span className="text-[10px] uppercase tracking-wide text-[var(--muted)] w-full">
              Add field
            </span>
            {COMPONENT_TYPES.map((t) => (
              <button
                key={t.type}
                type="button"
                onClick={() => addComponent(t.type)}
                className="rounded-md border border-[var(--border)] px-2 py-1 text-xs hover:border-[var(--accent)] hover:text-[var(--accent)] transition"
              >
                + {t.label}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="p-4 flex flex-col gap-4">
          {components.map(renderComponent)}
        </div>
      )}
    </div>
  );
}
