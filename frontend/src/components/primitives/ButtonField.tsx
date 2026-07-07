"use client";

import { useEffect, useRef, useState } from "react";
import type { ActionButton } from "@/lib/types";
import { Icon } from "../Icon";

interface Props {
  spec: ActionButton;
  onAction: () => void; // for increment / add_item
  count?: number;       // live tally shown for counter / add-to-list buttons
}

export function ButtonField({ spec, onAction, count }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  const utility = spec.action === "calculator" || spec.action === "timer";

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const iconName = spec.action === "calculator" ? "calculator" : spec.action === "timer" ? "clock" : "plus";

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => (utility ? setOpen((v) => !v) : onAction())}
        className="press w-full flex items-center justify-center gap-1.5 rounded-md bg-[var(--accent)] text-[var(--accent-fg)] px-3 py-2 text-sm font-medium hover:bg-[var(--accent-hover)] transition"
      >
        <Icon name={iconName} size={15} />
        <span className="truncate">{spec.label}</span>
        {count !== undefined && (
          <span className="ml-1 rounded-full bg-[var(--accent-fg)]/20 px-1.5 text-xs tabular-nums leading-tight">{count}</span>
        )}
      </button>
      {open && utility && (
        <div className="absolute z-20 mt-1 left-0 rounded-xl border border-[var(--border)] bg-[var(--surface)] shadow-2xl shadow-black/30 p-2">
          {spec.action === "calculator" ? <Calculator /> : <Timer />}
        </div>
      )}
    </div>
  );
}

function Calculator() {
  const [display, setDisplay] = useState("0");
  const [prev, setPrev] = useState<number | null>(null);
  const [op, setOp] = useState<string | null>(null);
  const [fresh, setFresh] = useState(true);

  const inputDigit = (d: string) => {
    setDisplay((cur) => (fresh || cur === "0" ? d : cur + d));
    setFresh(false);
  };
  const apply = (a: number, b: number, o: string) =>
    o === "+" ? a + b : o === "−" ? a - b : o === "×" ? a * b : b === 0 ? NaN : a / b;
  const chooseOp = (o: string) => {
    const v = parseFloat(display);
    if (prev !== null && op && !fresh) {
      const r = apply(prev, v, op);
      setPrev(r); setDisplay(String(r));
    } else setPrev(v);
    setOp(o); setFresh(true);
  };
  const equals = () => {
    if (prev === null || !op) return;
    const r = apply(prev, parseFloat(display), op);
    setDisplay(Number.isNaN(r) ? "Err" : String(r));
    setPrev(null); setOp(null); setFresh(true);
  };
  const clear = () => { setDisplay("0"); setPrev(null); setOp(null); setFresh(true); };

  const Btn = ({ children, onClick, cls = "" }: { children: React.ReactNode; onClick: () => void; cls?: string }) => (
    <button type="button" onClick={onClick}
      className={`w-9 h-9 rounded-md text-sm bg-[var(--surface-elevated)] hover:bg-[var(--border)] transition ${cls}`}>{children}</button>
  );

  return (
    <div className="flex flex-col gap-1.5 w-[156px]">
      <div className="rounded-md bg-[var(--surface-elevated)] px-2 py-1.5 text-right text-lg tabular-nums truncate">{display}</div>
      <div className="grid grid-cols-4 gap-1">
        <Btn onClick={clear} cls="col-span-2 !bg-[var(--danger)]/20">C</Btn>
        <Btn onClick={() => chooseOp("÷")}>÷</Btn>
        <Btn onClick={() => chooseOp("×")}>×</Btn>
        {["7", "8", "9"].map((d) => <Btn key={d} onClick={() => inputDigit(d)}>{d}</Btn>)}
        <Btn onClick={() => chooseOp("−")}>−</Btn>
        {["4", "5", "6"].map((d) => <Btn key={d} onClick={() => inputDigit(d)}>{d}</Btn>)}
        <Btn onClick={() => chooseOp("+")}>+</Btn>
        {["1", "2", "3"].map((d) => <Btn key={d} onClick={() => inputDigit(d)}>{d}</Btn>)}
        <Btn onClick={equals} cls="row-span-2 !bg-[var(--accent)] !text-[var(--accent-fg)]">=</Btn>
        <Btn onClick={() => inputDigit("0")} cls="col-span-2">0</Btn>
        <Btn onClick={() => setDisplay((c) => (c.includes(".") ? c : c + "."))}>.</Btn>
      </div>
    </div>
  );
}

function Timer() {
  const [secs, setSecs] = useState(300);
  const [running, setRunning] = useState(false);
  const ref = useRef<number | null>(null);

  useEffect(() => {
    if (running && secs > 0) {
      ref.current = window.setTimeout(() => setSecs((s) => s - 1), 1000);
    } else if (secs === 0) {
      setRunning(false);
    }
    return () => { if (ref.current) window.clearTimeout(ref.current); };
  }, [running, secs]);

  const mm = String(Math.floor(secs / 60)).padStart(2, "0");
  const ss = String(secs % 60).padStart(2, "0");
  const bump = (d: number) => setSecs((s) => Math.max(0, s + d));

  return (
    <div className="flex flex-col gap-2 w-[156px] items-center">
      <div className="text-3xl font-semibold tabular-nums" style={{ color: secs === 0 ? "var(--danger)" : "var(--foreground)" }}>{mm}:{ss}</div>
      {!running && (
        <div className="flex gap-1">
          <button type="button" onClick={() => bump(-60)} className="px-2 py-0.5 rounded bg-[var(--surface-elevated)] text-xs">−1m</button>
          <button type="button" onClick={() => bump(60)} className="px-2 py-0.5 rounded bg-[var(--surface-elevated)] text-xs">+1m</button>
          <button type="button" onClick={() => bump(30)} className="px-2 py-0.5 rounded bg-[var(--surface-elevated)] text-xs">+30s</button>
        </div>
      )}
      <div className="flex gap-1.5">
        <button type="button" onClick={() => setRunning((r) => !r)}
          className="px-3 py-1 rounded-md bg-[var(--accent)] text-[var(--accent-fg)] text-xs font-medium">{running ? "Pause" : "Start"}</button>
        <button type="button" onClick={() => { setRunning(false); setSecs(300); }}
          className="px-3 py-1 rounded-md border border-[var(--border)] text-xs">Reset</button>
      </div>
    </div>
  );
}
