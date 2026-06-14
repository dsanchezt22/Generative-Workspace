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
  | "note";

export interface ComponentBase {
  id: string;
  label: string;
  type: ComponentType;
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
}

export interface Metric extends ComponentBase {
  type: "metric";
  formula: "sum" | "count" | "avg" | "max" | "min";
  source_component_id: string;
  unit?: string | null;
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
export interface Gauge extends ComponentBase { type: "gauge"; min: number; max: number; unit?: string | null; }
export interface Checklist extends ComponentBase { type: "checklist"; }
export interface Gallery extends ComponentBase { type: "gallery"; }
export interface Note extends ComponentBase { type: "note"; placeholder?: string | null; }

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
  | Note;

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
}

export interface StoredModule {
  id: string;
  config: ModuleConfig;
  created_at: string;
  updated_at: string;
  page_id?: string | null;
}

export interface Page {
  id: string;
  session_id: string;
  name: string;
  icon?: string | null;
  parent_id?: string | null;
  position: number;
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
