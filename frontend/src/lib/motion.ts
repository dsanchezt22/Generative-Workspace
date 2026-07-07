// The single reduced-motion gate for V2 motion. The in-app override wins first
// (html[data-motion], set by lib/appearance.tsx): "reduced" is always off,
// "full" is always on; otherwise fall back to the OS prefers-reduced-motion
// query. Mirrors the shape the module-assembly gate has always used so the
// canvas zoom, the Pulse construct-in, and the module build all agree.
export function prefersReducedMotion(): boolean {
  const m =
    typeof document !== "undefined" ? document.documentElement.dataset.motion : undefined;
  if (m === "reduced") return true;
  if (m === "full") return false;
  return (
    typeof window !== "undefined" &&
    !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
  );
}
