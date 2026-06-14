import { ICON_NAMES } from "@/components/Icon";

// Per-module visual identity. The orchestrator may pick an `icon`/`accent`, but
// these resolvers guarantee a distinct, deterministic look even when it doesn't —
// so two modules never render identically. The accent set is the trusted palette;
// arbitrary model output is normalized back into it.

export interface AccentTheme {
  /** Palette token (stable id used in ModuleConfig.accent). */
  name: string;
  /** Foreground accent color (fills, rings, highlights). */
  accent: string;
  /** Readable text color when placed on top of `accent`. */
  accentFg: string;
}

export const ACCENTS: Record<string, AccentTheme> = {
  amber: { name: "amber", accent: "#d9a86c", accentFg: "#1c1b1a" },
  emerald: { name: "emerald", accent: "#84c89a", accentFg: "#10201a" },
  sky: { name: "sky", accent: "#8fbce0", accentFg: "#0f1a26" },
  rose: { name: "rose", accent: "#e0a0b4", accentFg: "#2a141b" },
  violet: { name: "violet", accent: "#c0a3e0", accentFg: "#1c1426" },
  coral: { name: "coral", accent: "#e8a285", accentFg: "#2a160f" },
  teal: { name: "teal", accent: "#7fccc0", accentFg: "#0f201d" },
  gold: { name: "gold", accent: "#d8c878", accentFg: "#221f10" },
};

export const ACCENT_NAMES = Object.keys(ACCENTS);

/** Stable, order-independent string hash (djb2-ish) for deterministic fallbacks. */
function hash(seed: string): number {
  let h = 5381;
  for (let i = 0; i < seed.length; i++) h = ((h << 5) + h + seed.charCodeAt(i)) >>> 0;
  return h;
}

export function resolveAccent(name?: string | null, seed = ""): AccentTheme {
  if (name && ACCENTS[name]) return ACCENTS[name];
  return ACCENTS[ACCENT_NAMES[hash(seed) % ACCENT_NAMES.length]];
}

// Title keyword → icon name (for modules with no icon, or to map intent).
const ICON_KEYWORDS: [RegExp, string][] = [
  [/workout|gym|fitness|exercise|lift|train|run|step|weight|cycl/, "activity"],
  [/calorie|meal|food|diet|nutrition|eat|recipe|cook|grocer/, "leaf"],
  [/budget|money|expense|finance|invoice|cost|saving|income|tax|revenue|spend/, "dollar"],
  [/todo|task|checklist|chore|clean/, "check"],
  [/read|book/, "book"],
  [/habit|streak|routine/, "repeat"],
  [/mood|journal|gratitude|feel|diary|reflect/, "smile"],
  [/calendar|schedule|itinerary|timetable/, "calendar"],
  [/travel|trip|flight|vacation|japan|tour/, "plane"],
  [/plant|garden|grow/, "leaf"],
  [/music|song|guitar|band|practice/, "music"],
  [/study|learn|class|course|school|exam|grade|gpa|assignment|semester/, "cap"],
  [/work|project|client|business|job|career|freelanc/, "briefcase"],
  [/water|hydrat/, "droplet"],
  [/sleep|rest/, "moon"],
  [/movie|film|watch|show|tv/, "film"],
  [/shop|cart|subscription/, "cart"],
  [/pet|dog|cat/, "paw"],
  [/goal/, "target"],
  [/photo|gallery|image/, "camera"],
  [/home|apartment|house|moving|move|reno/, "home"],
  [/contact|people|guest|address/, "folder"],
  [/inventory|stock|packing/, "archive"],
  [/wedding|marriage|party|event|birthday|celebrat/, "star"],
  [/health|medical|medication|medicine|pill/, "heart"],
];

// Back-compat: map legacy emoji icons to the new line-icon names.
const EMOJI_MAP: Record<string, string> = {
  "🏋️": "activity", "🍎": "leaf", "💰": "dollar", "💴": "dollar", "💵": "dollar", "🧾": "dollar", "🐷": "dollar",
  "✅": "check", "📚": "book", "🔁": "repeat", "🌙": "moon", "😴": "moon", "🗓️": "calendar", "📅": "calendar",
  "✈️": "plane", "⛩️": "plane", "🎌": "plane", "🇯🇵": "plane", "🌱": "leaf", "🍳": "leaf", "🍽️": "leaf", "🍜": "leaf",
  "🎸": "music", "🎓": "cap", "💼": "briefcase", "💧": "droplet", "🎬": "film", "🎮": "star", "🐾": "paw",
  "🛒": "cart", "⭐": "star", "🔥": "activity", "📌": "star", "🧭": "target", "📝": "pen", "📦": "archive",
  "🎯": "target", "🗂️": "folder", "⚖️": "activity", "👟": "activity", "💊": "heart", "🧹": "check",
  "🎉": "star", "📇": "folder", "🗣️": "smile", "🏢": "home", "💍": "heart",
};

const KNOWN_ICONS = new Set(ICON_NAMES);
const FALLBACK_NAMES = ["sparkles", "star", "folder", "target", "grid", "list", "layers"];

/** Resolve an icon NAME (for the <Icon> component) from a stored value + title. */
export function resolveIconName(icon?: string | null, seed = ""): string {
  if (icon) {
    const t = icon.trim();
    if (KNOWN_ICONS.has(t)) return t;
    if (EMOJI_MAP[t]) return EMOJI_MAP[t];
  }
  const lower = seed.toLowerCase();
  for (const [re, name] of ICON_KEYWORDS) if (re.test(lower)) return name;
  return FALLBACK_NAMES[hash(seed) % FALLBACK_NAMES.length];
}

/** Icon names offered in the per-module / per-page customise pickers. */
export const ICON_CHOICES = [
  "sparkles", "activity", "leaf", "dollar", "check", "book", "repeat", "smile",
  "calendar", "plane", "music", "cap", "briefcase", "droplet", "moon", "film",
  "cart", "star", "target", "list", "grid", "chart", "camera", "heart",
  "home", "folder", "bell", "paw",
];
