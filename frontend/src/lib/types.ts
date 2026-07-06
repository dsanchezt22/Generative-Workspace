export type ComponentType =
  | "text_input"
  | "number_input"
  | "checkbox"
  | "slider"
  | "progress_bar"
  | "list"
  | "metric"
  | "rating"
  | "tags"
  | "kpi"
  | "date"
  | "table"
  | "calendar"
  | "chart"
  | "dropdown"
  | "choice_chips"
  | "color"
  | "sparkline"
  | "ring"
  | "timeline"
  | "button"
  | "section"
  | "divider"
  | "kanban"
  | "heatmap"
  | "gauge"
  | "checklist"
  | "gallery"
  | "note"
  | "tracker";

export interface ComponentBase {
  id: string;
  label: string;
  type: ComponentType;
  span?: "full" | "half" | null;
  /** Visual weight, mapped to existing --accent intensity (no new colour). */
  emphasis?: "normal" | "primary" | "muted" | null;
}

/** A live external-data binding for a single-value display component
 * (R-701/R-704): Metric/Kpi/Ring/Gauge/ProgressBar may carry one. Mirrors
 * backend/src/schema.py's DataSource. */
export interface DataSource {
  provider: "weather" | "nutrition";
  query: Record<string, string | number>;
  refresh_secs?: number;
  label?: string | null;
}

/** The `GET /api/live/{provider}` response shape (R-701/R-704, `routes/live.py`).
 * `as_of` stays snake_case to match the wire payload exactly — `useLiveValue`
 * maps it to `asOf`. */
export interface LiveValuePayload {
  value: number | null;
  unit: string | null;
  as_of: string | null;
  source: string;
  stale: boolean;
  error: string | null;
  /** Structured off-mode marker (TRUS_LIVE_DATA=off): present-and-true only on
   * the backend's disabled payload. THIS boolean is the off-mode signal — never
   * the error string, which is free to be reworded (R-701 hardening). */
  disabled?: boolean;
}

export interface TextInput extends ComponentBase {
  type: "text_input";
  placeholder?: string | null;
}

export interface NumberInput extends ComponentBase {
  type: "number_input";
  min?: number | null;
  max?: number | null;
  step?: number | null;
  unit?: string | null;
}

export interface Checkbox extends ComponentBase {
  type: "checkbox";
}

export interface Slider extends ComponentBase {
  type: "slider";
  min: number;
  max: number;
  step: number;
  unit?: string | null;
}

export interface ProgressBar extends ComponentBase {
  type: "progress_bar";
  max: number;
  bound_to?: string | null;
  source_module_id?: string | null;
  data_source?: DataSource | null;
}

export interface Metric extends ComponentBase {
  type: "metric";
  formula: "sum" | "count" | "avg" | "max" | "min";
  source_component_id: string;
  unit?: string | null;
  data_source?: DataSource | null;
}

export interface ListField extends ComponentBase {
  type: "list";
  item_label: string;
  placeholder?: string | null;
}

export interface Rating extends ComponentBase {
  type: "rating";
  max?: number;
}

export interface Tags extends ComponentBase {
  type: "tags";
  placeholder?: string | null;
}

export interface Kpi extends ComponentBase {
  type: "kpi";
  unit?: string | null;
  data_source?: DataSource | null;
}

export interface DatePicker extends ComponentBase {
  type: "date";
  include_time?: boolean;
}

export interface TableField extends ComponentBase {
  type: "table";
  columns: string[];
}

export interface CalendarField extends ComponentBase {
  type: "calendar";
}

export interface ChartField extends ComponentBase {
  type: "chart";
  chart_type?: "bar" | "line" | "area" | "pie";
  unit?: string | null;
}

export interface Dropdown extends ComponentBase {
  type: "dropdown";
  options: string[];
}

export interface ChoiceChips extends ComponentBase {
  type: "choice_chips";
  options: string[];
}

export interface ColorField extends ComponentBase {
  type: "color";
}

export interface Sparkline extends ComponentBase {
  type: "sparkline";
  unit?: string | null;
}

export interface Ring extends ComponentBase {
  type: "ring";
  max: number;
  bound_to?: string | null;
  data_source?: DataSource | null;
}

export interface Timeline extends ComponentBase {
  type: "timeline";
}

export interface ActionButton extends ComponentBase {
  type: "button";
  action: "calculator" | "timer" | "increment" | "add_item";
  target?: string | null;
}

export interface Section extends ComponentBase { type: "section"; }
export interface Divider extends ComponentBase { type: "divider"; }
export interface Kanban extends ComponentBase { type: "kanban"; columns: string[]; }
export interface Heatmap extends ComponentBase { type: "heatmap"; unit?: string | null; }
export interface Gauge extends ComponentBase { type: "gauge"; min: number; max: number; unit?: string | null; data_source?: DataSource | null; }
export interface Checklist extends ComponentBase { type: "checklist"; }
export interface Gallery extends ComponentBase { type: "gallery"; }
export interface Note extends ComponentBase { type: "note"; placeholder?: string | null; }
export interface Tracker extends ComponentBase { type: "tracker"; period?: "day" | "week"; goal?: number | null; }

export type Component =
  | TextInput
  | NumberInput
  | Checkbox
  | Slider
  | ProgressBar
  | ListField
  | Metric
  | Rating
  | Tags
  | Kpi
  | DatePicker
  | TableField
  | CalendarField
  | ChartField
  | Dropdown
  | ChoiceChips
  | ColorField
  | Sparkline
  | Ring
  | Timeline
  | ActionButton
  | Section
  | Divider
  | Kanban
  | Heatmap
  | Gauge
  | Checklist
  | Gallery
  | Note
  | Tracker;

export interface ModuleLayout {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Automation {
  id: string;
  when_id: string;
  when: "checked" | "over" | "under" | "changes";
  when_value?: number | null;
  then: "increment" | "flag";
  then_id: string;
  then_value?: number | null;
}

export interface ModuleConfig {
  title: string;
  components: Component[];
  state: Record<string, unknown>;
  layout: ModuleLayout;
  summary_component_id?: string | null;
  icon?: string | null;
  accent?: string | null;
  density?: "comfortable" | "compact" | null;
  automations?: Automation[];
  columns?: number;
  /** Constrained design layer (closed-enum, no raw CSS) — used by screenshot captures. */
  radius?: "sharp" | "rounded" | "pill" | null;
  type_scale?: "compact" | "regular" | "large" | null;
  /** When true, the captured `accent` hue is honored (a themed import); else brand default. */
  theme_opt_in?: boolean;
}

export interface StoredModule {
  id: string;
  config: ModuleConfig;
  created_at: string;
  updated_at: string;
  page_id?: string | null;
  archived: boolean;
  rev: number;
}

// A functional commit: the next config is derived from the CURRENT one inside
// the parent's state update, so same-tick edits chain off fresh state rather
// than a stale props snapshot (R-602 same-tick hardening).
export type ModuleConfigUpdater = (prev: ModuleConfig) => ModuleConfig;
export type CommitModule = (
  id: string,
  config: ModuleConfig | ModuleConfigUpdater,
  delay?: number,
) => void;

export interface Page {
  id: string;
  session_id: string;
  name: string;
  icon?: string | null;
  parent_id?: string | null;
  position: number;
  /** R-502/R-504: this child page's portal placement (world coords) on its
   * parent's canvas. Null until dragged — the frontend then auto-places it. */
  portal_x?: number | null;
  portal_y?: number | null;
  /** R-504 completion: the page's own saved viewport (pan offset + zoom), so
   * the view resumes across devices. Null until first saved. */
  view_x?: number | null;
  view_y?: number | null;
  view_zoom?: number | null;
  created_at: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  text: string;
  module_id?: string | null;
  page_id?: string | null;
  created_at: string;
}

export interface Snapshot {
  id: string;
  page_id?: string | null;
  label: string;
  module_count: number;
  created_at: string;
}

// The "remembers you" profile store (R-801). Mirrors backend UserProfileEntry.
export type ProfileKind = "goal" | "preference" | "pattern" | "fact";

export interface UserProfileEntry {
  id: string;
  owner: string;
  kind: ProfileKind;
  text: string;
  source: "interview" | "prompt" | "activity" | "manual";
  created_at: string;
  updated_at: string;
}

// Layout Studio — a use-case-indexed library of candidate layouts.
export interface StudioUseCase {
  key: string;
  title: string;
  icon?: string | null;
  accent?: string | null;
  apps: string[];
  count: number;
}

export interface StudioLayout {
  id?: string;
  use_case: string;
  label: string;
  inspired_by?: string | null;
  config: ModuleConfig;
  created_at?: string;
  /** Screenshot-capture metadata (capture endpoint only). */
  capture_meta?: Record<string, unknown> | null;
  confidence?: number | null;
}
