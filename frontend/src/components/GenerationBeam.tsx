"use client";

/** A light beam that sweeps the canvas while a generation request is in flight —
 * "Trus is reading your intent." Echoes the marketing site's app-grid scan beam.
 *
 * Reduced motion is handled in CSS (globals.css hides `.read-beam`) rather than
 * in JS, so this stays a pure, stateless presentational component. */
export function GenerationBeam({ active }: { active: boolean }) {
  if (!active) return null;
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden z-[5]" aria-hidden>
      <span className="read-beam" />
    </div>
  );
}
