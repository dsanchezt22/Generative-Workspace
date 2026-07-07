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
  | "tracker"
  | "feed";

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
/** V2 SURF: a read-only feed of entries an automation appends to (summarize/draft
 * land here). The one new trusted component — plain-text nodes only, closed badge
 * set, bounded display. `max_items` caps how many rows render. */
export interface Feed extends ComponentBase { type: "feed"; max_items?: number | null; }
/** A single Feed row — mirrors exactly what the backend appends
 * (services/actions.py `_land_feed_entry`): `{ts, title, body, badge}`. `badge` is
 * one of the closed set draft|simulated|failed (or "" for none). */
export interface FeedEntry {
  ts: string;
  title: string;
  body: string;
  badge: string;
}

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
  | Tracker
  | Feed;

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

// Per-surface read-only sharing (SHARE-1..3). Additive, whitelisted shapes —
// the public payload never carries session/owner/page ids, rev, or archived rows
// (see DESIGN-sharing §2). `data_source` is stripped server-side before delivery.
export interface ShareStatus {
  active: boolean;
  token: string | null;
  created_at: string | null;
}
export interface SharedModule {
  id: string;
  config: ModuleConfig;
  updated_at: string;
}
export interface SharedPageResponse {
  page: { name: string; icon: string | null };
  modules: SharedModule[];
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
  /** V2 SURF: a page's accent token (an ACCENTS key), giving each "app" a
   * distinct icon-chip tint. Null → deterministic fallback from the name. */
  accent?: string | null;
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

// ─────────────────────────────────────────────────────────────────────────
// V2 Pulse — server-side runtime automations (the always-on trust spine).
// NOT the client-side `Automation` above (ModuleConfig.automations, an
// intra-module increment/flag rule) — a different concept with its own store.
// Mirrors backend/src/schema_automations.py (DESIGN-autonomy §4.1 + the V2
// reconciled ruling 4). The UI reads action_type/tier_floor/summary/preview;
// the typed `action` union is mirrored so create payloads type-check.
// ─────────────────────────────────────────────────────────────────────────

export interface AutoActionWatch {
  type: "watch";
  provider: "weather" | "nutrition";
  query: Record<string, string | number>;
  module_id: string;
  component_id: string;
  op?: "over" | "under" | null;
  threshold?: number | null;
  feed_module_id?: string | null;
  feed_component_id?: string | null;
}
export interface AutoActionSort {
  type: "sort";
  module_id: string;
  component_id: string;
  by: "date" | "value" | "label";
}
export interface AutoActionTrack {
  type: "track";
  module_id: string;
  component_id: string;
  source_module_id: string;
  source_component_id: string;
  label?: string | null;
}
export interface AutoActionRemind {
  type: "remind";
  module_id: string;
  component_id: string;
  feed_module_id?: string | null;
  feed_component_id?: string | null;
}
export interface AutoActionSummarize {
  type: "summarize";
  module_id: string;
  component_id: string;
  source_module_ids: string[];
}
export interface AutoActionDraft {
  type: "draft";
  module_id: string;
  component_id: string;
  recipient: string;
  instruction: string;
}
export interface AutoActionLearn {
  type: "learn";
  lookback_days: number;
  max_facts: number;
}
export interface AutoActionArchiveModule {
  type: "archive_module";
  module_id: string;
}
export interface AutoActionSendEmail {
  type: "send_email";
  to: string;
  subject: string;
  module_id?: string | null;
  component_id?: string | null;
}
export interface AutoActionMessageHuman {
  type: "message_human";
  to: string;
  text: string;
}
export interface AutoActionPay {
  type: "pay";
  payee: string;
  amount_usd: number;
  memo: string;
}
export interface AutoActionDeleteData {
  type: "delete_data";
  target: "module" | "page";
  target_id: string;
}

// Discriminated on `type` — all 12 action types (reconciled ruling 4).
export type AutoAction =
  | AutoActionWatch
  | AutoActionSort
  | AutoActionTrack
  | AutoActionRemind
  | AutoActionSummarize
  | AutoActionDraft
  | AutoActionLearn
  | AutoActionArchiveModule
  | AutoActionSendEmail
  | AutoActionMessageHuman
  | AutoActionPay
  | AutoActionDeleteData;

export type TierFloor = "autonomous" | "consequential";
export type ScheduleKind = "interval" | "daily";

export interface AutomationOut {
  id: string;
  name: string;
  description: string;
  page_id: string | null;
  action: AutoAction;
  action_type: string;
  tier_floor: TierFloor; // from ACTION_SPECS — display only
  irreversible: boolean; // drives the dial's hard-floor lock line
  trust_dial: number; // 0 ask-always | 1 standard | 2 trusted
  enabled: boolean;
  schedule_kind: ScheduleKind;
  interval_secs: number | null;
  daily_at: string | null;
  next_run_at: string | null;
  last_run_at: string | null;
  created_at: string;
}

export interface AutomationCreate {
  name: string;
  description?: string;
  page_id?: string | null;
  action: AutoAction;
  schedule_kind?: ScheduleKind;
  interval_secs?: number | null; // backend bounds 300..604800 (reconciled ruling 4)
  daily_at?: string | null;
  trust_dial?: number; // creation can never exceed 1 (AUT-3)
}

export interface AutomationPatch {
  name?: string | null;
  enabled?: boolean | null;
  trust_dial?: number | null; // the ONLY dial writer
}

export interface PreviewField {
  label: string;
  value: string;
}

// Trusted-render only — flat text, never markup.
export interface PreviewPayload {
  title: string;
  fields: PreviewField[];
  body?: string | null; // e.g. a full draft, mono-rendered
  simulated: boolean; // SEAM-1 badge
}

export type ApprovalStatus = "pending" | "approved" | "rejected" | "expired" | "failed";

export interface ApprovalOut {
  id: string;
  automation_id: string;
  automation_name: string;
  action_type: string;
  summary: string; // future-tense "what it will do" (server-composed, frozen)
  preview: PreviewPayload | null;
  status: ApprovalStatus;
  expires_at: string;
  created_at: string;
  decided_at: string | null;
  executed_at: string | null;
}

export type ActivityKind =
  | "ran"
  | "held"
  | "approved"
  | "rejected"
  | "expired"
  | "failed"
  | "skipped";

export interface ActivityEntry {
  id: string;
  kind: ActivityKind;
  summary: string;
  automation_id: string | null;
  automation_name: string | null;
  approval_id: string | null;
  module_id?: string | null; // deep-link target (zoom-to-module)
  page_id?: string | null;
  simulated: boolean;
  created_at: string;
}

// ─────────────────────────────────────────────────────────────────────────
// V2 SURF — self-composing "structure of surfaces" (ONB-1) + app-tile overview.
// A structure proposal is a set of app pages (each with its tools) plus the
// automations that will run on them. Confirmed → real pages/modules/automations
// on the canvas. Mirrors the backend structure schema (DESIGN-surfaces §1) as
// amended by reconciled ruling 4 (automations carry `action_type`, NO `tier` —
// the card derives the chip client-side) and ruling 2 (no 'proposed' status —
// confirmed structures create real, enabled automations).
// ─────────────────────────────────────────────────────────────────────────

export interface StructurePage {
  name: string;
  icon?: string | null;
  accent?: string | null;
  purpose?: string | null; // plain-language "what this page is for"
  modules: ModuleConfig[]; // the tools that populate it
}

export interface StructureAutomation {
  name: string;
  description: string; // plain-language "exactly what it does"
  action_type: "watch" | "summarize" | "track" | "remind" | "draft";
  page_index: number; // index into the proposal's pages (never a name/id)
  schedule?: "hourly" | "daily" | "weekly" | null;
  // Optional composer hints carried on the wire (the card doesn't render these).
  provider?: string | null;
  query?: Record<string, string | number> | null;
  op?: "over" | "under" | null;
  threshold?: number | null;
  instruction?: string | null;
  source_component_id?: string | null;
}

export interface StructureProposal {
  plan?: string | null; // the rationale paragraph
  pages: StructurePage[];
  automations: StructureAutomation[];
}

export interface InsertStructureResponse {
  pages: Page[];
  modules: StoredModule[];
  automation_ids: string[];
  dropped: string[]; // names of tools/automations that couldn't be built
}

// One grouped, owner-scoped overview per page (GET /api/pages/overview) — real
// data from day one (reconciled ruling 6): module + automation counts and the
// most recent automation run (null until an automation has run).
export interface PageOverview {
  modules: number;
  automations: number;
  last_run_at: string | null;
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
