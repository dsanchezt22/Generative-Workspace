import { gsap } from "gsap";

/**
 * The signature Trus "module build" — six sequenced beats that read as
 * ASSEMBLY, never a fade (design ethos §06). Each tile is constructed in front
 * of the user: it seeds in, its border traces itself, the surface fills, a light
 * band sweeps across, the label wipes in, then it micro-settles.
 *
 * Beats (target ≈1.7s/tile): seed → border draw → surface fill → scan sweep →
 * label wipe → micro-settle. Tiles stagger ~100ms by index.
 *
 * Reduced motion is handled by the caller (it simply doesn't invoke this and the
 * final state renders instantly). All inline props are cleared on completion so
 * the card's hover/drag transforms keep working.
 */
const STAGGER = 0.1;            // ~100ms between tiles
const MAX_STAGGER_TILES = 5;    // cap the cascade so late tiles don't lag

export function runAssembly(card: HTMLElement, index = 0): () => void {
  const pick = (name: string) => card.querySelector(`[data-assembly="${name}"]`);
  const svg = pick("border-svg") as SVGSVGElement | null;
  const rect = pick("border") as SVGRectElement | null;
  const scan = pick("scan") as HTMLElement | null;
  const label = pick("label") as HTMLElement | null;
  const body = pick("body") as HTMLElement | null;

  const tl = gsap.timeline({ delay: Math.min(index, MAX_STAGGER_TILES) * STAGGER });

  // 1 · Seed — drops in from scale .94 / y 12 / opacity 0.
  tl.fromTo(card,
    { opacity: 0, scale: 0.94, y: 12 },
    { opacity: 1, scale: 1, y: 0, duration: 0.26, ease: "power3.out" }, 0);

  // 2 · Border draws — the rounded rect traces itself clockwise.
  if (svg && rect) {
    const w = card.clientWidth || card.offsetWidth;
    const h = card.clientHeight || card.offsetHeight;
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    rect.setAttribute("x", "0.75");
    rect.setAttribute("y", "0.75");
    rect.setAttribute("width", String(Math.max(0, w - 1.5)));
    rect.setAttribute("height", String(Math.max(0, h - 1.5)));
    let len = (w + h) * 2;
    try { len = rect.getTotalLength() || len; } catch { /* jsdom */ }
    gsap.set(svg, { opacity: 1 });
    gsap.set(rect, { strokeDasharray: len, strokeDashoffset: len });
    tl.to(rect, { strokeDashoffset: 0, duration: 0.26, ease: "power2.inOut" }, 0.05);
  }

  // 3 · Surface fill — content rises in at ~60% of the trace.
  if (body) tl.fromTo(body,
    { opacity: 0, y: 4 },
    { opacity: 1, y: 0, duration: 0.24, ease: "power1.out" }, 0.2);

  // 4 · Scan sweep — the canonical matte sheen band sweeps L→R (DESIGN-ETHOS §5.2).
  if (scan) tl.fromTo(scan,
    { xPercent: -130, opacity: 1 },
    { xPercent: 330, duration: 0.5, ease: "power2.inOut" }, 0.18);

  // 5 · Label builds — wipes in left→right. Driven via a numeric proxy because
  // GSAP doesn't interpolate clip-path inset() strings reliably.
  if (label) {
    const wipe = { v: 100 };
    label.style.clipPath = "inset(0 100% 0 0)";
    tl.to(wipe, {
      v: 0, duration: 0.2, ease: "power3.out",
      onUpdate: () => { label.style.clipPath = `inset(0 ${wipe.v}% 0 0)`; },
    }, 0.3);
    // 5b · Title sheen — a matte sheen sweeps over the revealed label, echoing the
    // hero wordmark sheen (DESIGN-ETHOS §5.4). Driven by GSAP (not a CSS animation)
    // so the timeline outlives the sweep and finalize() can't truncate it; the
    // class supplies the text-clipped gradient, the tween moves it across.
    tl.fromTo(label,
      { backgroundPosition: "200% 0" },
      { backgroundPosition: "-50% 0", duration: 0.5, ease: "power2.out",
        onStart: () => label.classList.add("title-sheen") }, 0.5);
  }

  // 6 · Micro-settle — a tiny overshoot, then clear every inline prop.
  tl.to(card, { scale: 1.015, duration: 0.08, ease: "power1.out" }, 0.42)
    .to(card, { scale: 1, duration: 0.14, ease: "back.out(2)" });

  const finalize = () => {
    if (svg) gsap.set(svg, { opacity: 0 });
    if (scan) gsap.set(scan, { opacity: 0 });
    gsap.set(card, { clearProps: "transform,opacity" });
    if (label) {
      label.style.clipPath = "";
      label.classList.remove("title-sheen");
      gsap.set(label, { clearProps: "backgroundPosition" });
    }
    if (body) gsap.set(body, { clearProps: "transform,opacity" });
  };
  tl.eventCallback("onComplete", finalize);

  // If interrupted (unmount, or React Strict Mode's setup→cleanup→setup in dev),
  // jump straight to the final visible state so a tile is never left hidden.
  return () => { tl.kill(); finalize(); };
}
