// R-104: turning raw per-owner prompt history (from GET /api/suggestions) into
// clean "build me a tool" chips for the EmptyState.
//
// The suggestions endpoint draws from this owner's generation cache + message
// history, which also contains rows that make poor starter chips (noted in the
// 2b-2 review). We filter them at render:
//   1. File-upload log lines — the file path prefixes each with "📎".
//   2. Terse fragments (< 3 words) — usually a stray word, not a tool idea.
//   3. Refine instructions — PromptBar builds a "refine the preview" prompt by
//      joining the original and the tweak with " — " (see PromptBar.submit), and
//      refine imperatives ("make it…", "change the…") are follow-ups on an
//      existing tool, not fresh build ideas. Both get dropped.
// Anything surviving is deduped case-insensitively. If NOTHING survives (new
// owner, or all rows filtered), the caller falls back to the static starter chips.

// The em-dash join PromptBar uses when refining a preview ("original — tweak").
const REFINE_JOIN = " — ";
// Leading verbs that mark a tweak to something that already exists, not a build.
const REFINE_PREFIXES = ["make it", "make the", "change ", "turn it", "also add", "remove the", "rename "];

export function filterSuggestions(prompts: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of prompts) {
    const p = raw.trim();
    if (!p) continue;
    if (p.startsWith("📎")) continue; // file-upload log line
    if (p.split(/\s+/).length < 3) continue; // too terse to be a build idea
    if (p.includes(REFINE_JOIN)) continue; // refine-combined preview prompt
    const lower = p.toLowerCase();
    if (REFINE_PREFIXES.some((pre) => lower.startsWith(pre))) continue; // refine imperative
    if (seen.has(lower)) continue; // dedupe
    seen.add(lower);
    out.push(p);
  }
  return out;
}

/**
 * A short chip label derived from a build prompt: strips the leading
 * "create/make/build a…" so "Create a habit tracker" reads as "Habit tracker"
 * (matching the hand-written static chips), truncates long prompts, and
 * capitalises the first letter. The full prompt is still what gets submitted.
 */
export function suggestionLabel(prompt: string, max = 30): string {
  let p = prompt
    .trim()
    // Article alternatives are longest-first and whole-word so "an" isn't
    // partially eaten as "a" (which would leave a stray "n …").
    .replace(/^(?:create|make|build|add|generate|set up|track)\s+(?:me\s+)?(?:(?:the|my|an|a)\s+)?/i, "");
  if (!p) p = prompt.trim();
  if (p.length > max) p = p.slice(0, max - 1).trimEnd() + "…";
  return p.charAt(0).toUpperCase() + p.slice(1);
}
