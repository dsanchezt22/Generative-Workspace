import type { Component, ComponentType } from "./types";

export const COMPONENT_TYPES: { type: ComponentType; label: string }[] = [
  { type: "text_input", label: "Text" },
  { type: "number_input", label: "Number" },
  { type: "checkbox", label: "Checkbox" },
  { type: "slider", label: "Slider" },
  { type: "progress_bar", label: "Progress bar" },
  { type: "list", label: "List" },
  { type: "metric", label: "Metric" },
  { type: "rating", label: "Rating" },
  { type: "tags", label: "Tags" },
  { type: "kpi", label: "Big number" },
  { type: "date", label: "Date" },
  { type: "table", label: "Table" },
  { type: "calendar", label: "Calendar" },
  { type: "chart", label: "Chart" },
  { type: "dropdown", label: "Dropdown" },
  { type: "choice_chips", label: "Choice chips" },
  { type: "color", label: "Colour" },
  { type: "sparkline", label: "Sparkline" },
  { type: "ring", label: "Progress ring" },
  { type: "timeline", label: "Timeline" },
  { type: "button", label: "Button" },
  { type: "section", label: "Section" },
  { type: "divider", label: "Divider" },
  { type: "kanban", label: "Board" },
  { type: "heatmap", label: "Heatmap" },
  { type: "gauge", label: "Gauge" },
  { type: "checklist", label: "Checklist" },
  { type: "gallery", label: "Gallery" },
  { type: "note", label: "Note" },
  { type: "tracker", label: "Tracker" },
  { type: "feed", label: "Feed" },
];

let counter = 0;

/** Build a sensible default component of a given type with a unique id. */
export function makeComponent(type: ComponentType, label?: string): Component {
  const id = `field_${Date.now().toString(36)}_${counter++}`;
  switch (type) {
    case "text_input":
      return { id, type, label: label ?? "Text field", placeholder: "" };
    case "number_input":
      return { id, type, label: label ?? "Number", min: 0, step: 1 };
    case "checkbox":
      return { id, type, label: label ?? "Checkbox" };
    case "slider":
      return { id, type, label: label ?? "Slider", min: 0, max: 100, step: 1 };
    case "progress_bar":
      return { id, type, label: label ?? "Progress", max: 100 };
    case "list":
      return { id, type, label: label ?? "List", item_label: "Item" };
    case "metric":
      return { id, type, label: label ?? "Total", formula: "sum", source_component_id: "value" };
    case "rating":
      return { id, type, label: label ?? "Rating", max: 5 };
    case "tags":
      return { id, type, label: label ?? "Tags" };
    case "kpi":
      return { id, type, label: label ?? "Headline" };
    case "date":
      return { id, type, label: label ?? "Date" };
    case "table":
      return { id, type, label: label ?? "Table", columns: ["Item", "Value"] };
    case "calendar":
      return { id, type, label: label ?? "Calendar" };
    case "chart":
      return { id, type, label: label ?? "Chart", chart_type: "bar" };
    case "dropdown":
      return { id, type, label: label ?? "Choose", options: ["Option 1", "Option 2", "Option 3"] };
    case "choice_chips":
      return { id, type, label: label ?? "Pick one", options: ["Low", "Medium", "High"] };
    case "color":
      return { id, type, label: label ?? "Colour" };
    case "sparkline":
      return { id, type, label: label ?? "Trend" };
    case "ring":
      return { id, type, label: label ?? "Progress", max: 100 };
    case "timeline":
      return { id, type, label: label ?? "Timeline" };
    case "button":
      return { id, type, label: label ?? "Button", action: "increment" };
    case "section":
      return { id, type, label: label ?? "Section" };
    case "divider":
      return { id, type, label: "" };
    case "kanban":
      return { id, type, label: label ?? "Board", columns: ["To do", "Doing", "Done"] };
    case "heatmap":
      return { id, type, label: label ?? "Activity" };
    case "gauge":
      return { id, type, label: label ?? "Gauge", min: 0, max: 100 };
    case "checklist":
      return { id, type, label: label ?? "Checklist" };
    case "gallery":
      return { id, type, label: label ?? "Gallery" };
    case "note":
      return { id, type, label: label ?? "Notes" };
    case "tracker":
      return { id, type, label: label ?? "Tracker", period: "day" };
    case "feed":
      return { id, type, label: label ?? "Feed", max_items: 20 };
  }
}
