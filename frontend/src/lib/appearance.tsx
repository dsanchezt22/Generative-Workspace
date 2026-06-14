"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { ACCENTS } from "@/lib/theme";

export type ThemeMode = "light" | "dark" | "system";
export type Density = "comfortable" | "compact";
export type Scale = "s" | "m" | "l";
export type Motion = "system" | "full" | "reduced";

interface Appearance {
  theme: ThemeMode;
  density: Density;
  accent: string; // palette token name, "" = theme default
  scale: Scale;
  motion: Motion;
  grid: boolean;
  setTheme: (t: ThemeMode) => void;
  setDensity: (d: Density) => void;
  setAccent: (name: string) => void;
  setScale: (s: Scale) => void;
  setMotion: (m: Motion) => void;
  setGrid: (g: boolean) => void;
}

const AppearanceContext = createContext<Appearance | null>(null);

const KEY_THEME = "trus-theme";
const KEY_DENSITY = "trus-density";
const KEY_ACCENT = "trus-accent-name";
const KEY_SCALE = "trus-scale";
const KEY_MOTION = "trus-motion";
const KEY_GRID = "trus-grid";

const SCALE_PX: Record<Scale, string> = { s: "14px", m: "16px", l: "18px" };

function applyScale(s: Scale) {
  document.documentElement.style.fontSize = SCALE_PX[s] ?? "16px";
}
function applyMotion(m: Motion) {
  const el = document.documentElement;
  if (m === "system") el.removeAttribute("data-motion");
  else el.setAttribute("data-motion", m);
}
function applyGrid(g: boolean) {
  document.documentElement.setAttribute("data-grid", g ? "on" : "off");
}

function systemDark() {
  return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function applyTheme(theme: ThemeMode) {
  const dark = theme === "dark" || (theme === "system" && systemDark());
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
}

function applyAccent(name: string) {
  const el = document.documentElement;
  const a = ACCENTS[name];
  if (a) {
    el.style.setProperty("--accent", a.accent);
    el.style.setProperty("--accent-fg", a.accentFg);
    localStorage.setItem("trus-accent", a.accent);
    localStorage.setItem("trus-accent-fg", a.accentFg);
  } else {
    el.style.removeProperty("--accent");
    el.style.removeProperty("--accent-fg");
    localStorage.removeItem("trus-accent");
    localStorage.removeItem("trus-accent-fg");
  }
}

export function AppearanceProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<ThemeMode>("system");
  const [density, setDensityState] = useState<Density>("comfortable");
  const [accent, setAccentState] = useState<string>("");
  const [scale, setScaleState] = useState<Scale>("m");
  const [motion, setMotionState] = useState<Motion>("system");
  const [grid, setGridState] = useState<boolean>(true);

  // Hydrate from localStorage once (the no-FOUC script already applied them to the DOM).
  useEffect(() => {
    setThemeState((localStorage.getItem(KEY_THEME) as ThemeMode) || "system");
    setDensityState((localStorage.getItem(KEY_DENSITY) as Density) || "comfortable");
    setAccentState(localStorage.getItem(KEY_ACCENT) || "");
    setScaleState((localStorage.getItem(KEY_SCALE) as Scale) || "m");
    setMotionState((localStorage.getItem(KEY_MOTION) as Motion) || "system");
    setGridState(localStorage.getItem(KEY_GRID) !== "off");
  }, []);

  // Follow the OS when in system mode.
  useEffect(() => {
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme("system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [theme]);

  const setTheme = useCallback((t: ThemeMode) => {
    setThemeState(t);
    localStorage.setItem(KEY_THEME, t);
    applyTheme(t);
  }, []);

  const setDensity = useCallback((d: Density) => {
    setDensityState(d);
    localStorage.setItem(KEY_DENSITY, d);
    document.documentElement.setAttribute("data-density", d);
  }, []);

  const setAccent = useCallback((name: string) => {
    setAccentState(name);
    localStorage.setItem(KEY_ACCENT, name);
    applyAccent(name);
  }, []);

  const setScale = useCallback((s: Scale) => {
    setScaleState(s);
    localStorage.setItem(KEY_SCALE, s);
    applyScale(s);
  }, []);

  const setMotion = useCallback((m: Motion) => {
    setMotionState(m);
    localStorage.setItem(KEY_MOTION, m);
    applyMotion(m);
  }, []);

  const setGrid = useCallback((g: boolean) => {
    setGridState(g);
    localStorage.setItem(KEY_GRID, g ? "on" : "off");
    applyGrid(g);
  }, []);

  return (
    <AppearanceContext.Provider value={{ theme, density, accent, scale, motion, grid, setTheme, setDensity, setAccent, setScale, setMotion, setGrid }}>
      {children}
    </AppearanceContext.Provider>
  );
}

export function useAppearance(): Appearance {
  const ctx = useContext(AppearanceContext);
  if (!ctx) throw new Error("useAppearance must be used within AppearanceProvider");
  return ctx;
}

/** Inline script that applies saved appearance before first paint (no flash). */
export const NO_FOUC_SCRIPT = `(function(){try{
var t=localStorage.getItem('${KEY_THEME}')||'system';
var d=localStorage.getItem('${KEY_DENSITY}')||'comfortable';
var dark=t==='dark'||(t==='system'&&matchMedia('(prefers-color-scheme: dark)').matches);
var el=document.documentElement;
el.setAttribute('data-theme',dark?'dark':'light');
el.setAttribute('data-density',d);
var a=localStorage.getItem('trus-accent');var af=localStorage.getItem('trus-accent-fg');
if(a){el.style.setProperty('--accent',a);}if(af){el.style.setProperty('--accent-fg',af);}
var sc=localStorage.getItem('${KEY_SCALE}');el.style.fontSize=({s:'14px',m:'16px',l:'18px'})[sc||'m'];
var mo=localStorage.getItem('${KEY_MOTION}');if(mo&&mo!=='system'){el.setAttribute('data-motion',mo);}
if(localStorage.getItem('${KEY_GRID}')==='off'){el.setAttribute('data-grid','off');}
}catch(e){}})();`;
