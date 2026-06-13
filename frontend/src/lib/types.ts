export type ComponentType =
  | "text_input"
  | "number_input"
  | "checkbox"
  | "slider"
  | "progress_bar"
  | "list"
  | "metric";

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

export type Component =
  | TextInput
  | NumberInput
  | Checkbox
  | Slider
  | ProgressBar
  | ListField
  | Metric;

export interface ModuleLayout {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface ModuleConfig {
  title: string;
  components: Component[];
  state: Record<string, unknown>;
  layout: ModuleLayout;
  summary_component_id?: string | null;
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
  position: number;
  created_at: string;
}
