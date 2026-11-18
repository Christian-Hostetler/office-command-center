"use client";

import { Check, CircleAlert, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

export function buzz() {
  try {
    navigator.vibrate?.(8);
  } catch {}
}

export function Switch({
  checked,
  disabled,
  onChange,
  label,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: (next: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative h-[31px] w-[51px] shrink-0 rounded-full transition-colors duration-300 disabled:opacity-30 ${
        checked ? "bg-white" : "bg-surface-2"
      }`}
    >
      <span
        className={`absolute top-[3px] left-[3px] h-[25px] w-[25px] rounded-full transition-[transform,background-color] duration-300 ease-[var(--snap)] ${
          checked ? "translate-x-5 bg-black" : "translate-x-0 bg-muted"
        }`}
      />
    </button>
  );
}

// A bottom sheet that slides up, and slides back down when you drag its top edge or tap outside.
export function Sheet({ open, onClose, children }: { open: boolean; onClose: () => void; children: ReactNode }) {
  const [mounted, setMounted] = useState(open);
  const [closing, setClosing] = useState(false);
  const [drag, setDrag] = useState(0);
  const [dragging, setDragging] = useState(false);
  const start = useRef(0);

  // Adjusting state while rendering is React's pattern for reacting to a prop change.
  if (open && (!mounted || closing)) {
    setMounted(true);
    setClosing(false);
  }
  if (!open && mounted && !closing) setClosing(true);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!mounted) return null;

  return (
    <div className="fixed inset-0 z-40" role="dialog" aria-modal="true">
      <div
        className={`absolute inset-0 bg-black/70 backdrop-blur-[2px] ${closing ? "backdrop-out" : "backdrop-in"}`}
        onClick={onClose}
      />
      <div
        className={`absolute inset-x-0 bottom-0 mx-auto max-w-[480px] ${closing ? "sheet-out" : "sheet-in"}`}
        onAnimationEnd={() => {
          if (closing) {
            setMounted(false);
            setClosing(false);
            setDrag(0);
          }
        }}
      >
        <div
          className="rounded-t-[30px] border-t border-line bg-[#0c0c0c] pb-[max(env(safe-area-inset-bottom),20px)]"
          style={{ transform: `translateY(${drag}px)`, transition: dragging ? "none" : "transform 300ms var(--snap)" }}
        >
          <div
            className="flex h-7 cursor-grab touch-none items-center justify-center"
            onPointerDown={(e) => {
              start.current = e.clientY;
              setDragging(true);
              e.currentTarget.setPointerCapture(e.pointerId);
            }}
            onPointerMove={(e) => dragging && setDrag(Math.max(0, e.clientY - start.current))}
            onPointerUp={() => {
              setDragging(false);
              if (drag > 110) onClose();
              else setDrag(0);
            }}
          >
            <span className="h-[5px] w-10 rounded-full bg-faint" />
          </div>
          {children}
        </div>
      </div>
    </div>
  );
}

// A row of tick marks you drag along, after the IKEA Home smart brightness control.
export function Ladder({
  value,
  min,
  max,
  step = 1,
  ticks,
  vertical,
  format,
  label,
  onChange,
  onCommit,
}: {
  value: number;
  min: number;
  max: number;
  step?: number;
  ticks: number;
  vertical?: boolean;
  format: (value: number) => string;
  label: string;
  onChange: (value: number) => void;
  onCommit: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const share = (value - min) / (max - min);

  const valueAt = (e: React.PointerEvent) => {
    const box = ref.current!.getBoundingClientRect();
    const t = vertical ? 1 - (e.clientY - box.top) / box.height : (e.clientX - box.left) / box.width;
    const raw = min + Math.min(1, Math.max(0, t)) * (max - min);
    return Math.round(raw / step) * step;
  };

  const set = (next: number) => {
    const clamped = Math.min(max, Math.max(min, next));
    if (clamped !== value) onChange(clamped);
  };

  return (
    <div
      ref={ref}
      role="slider"
      tabIndex={0}
      aria-label={label}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={value}
      aria-valuetext={format(value)}
      aria-orientation={vertical ? "vertical" : "horizontal"}
      className={`relative touch-none outline-none ${vertical ? "h-full w-full" : "h-14 w-full"}`}
      onPointerDown={(e) => {
        dragging.current = true;
        e.currentTarget.setPointerCapture(e.pointerId);
        set(valueAt(e));
      }}
      onPointerMove={(e) => dragging.current && set(valueAt(e))}
      onPointerUp={() => {
        dragging.current = false;
        onCommit();
      }}
      onKeyDown={(e) => {
        const big = (max - min) / 20;
        const delta = { ArrowUp: big, ArrowRight: big, ArrowDown: -big, ArrowLeft: -big }[e.key];
        if (delta !== undefined) {
          e.preventDefault();
          set(Math.round((value + delta) / step) * step);
          onCommit();
        }
      }}
    >
      <div className={`flex h-full w-full ${vertical ? "flex-col-reverse justify-between" : "items-end justify-between"}`}>
        {Array.from({ length: ticks }, (_, i) => {
          const lit = i / (ticks - 1) <= share + 1e-9;
          return vertical ? (
            <span
              key={i}
              className={`ml-auto block h-[3px] rounded-full transition-[width,background-color] duration-200 ${
                lit ? "w-full bg-white" : "w-1/2 bg-faint"
              }`}
            />
          ) : (
            <span
              key={i}
              className={`block w-[3px] rounded-full transition-[height,background-color] duration-200 ${
                lit ? "h-7 bg-white" : "h-4 bg-faint"
              }`}
            />
          );
        })}
      </div>
      <span
        className="pointer-events-none absolute rounded-full bg-white px-3 py-1.5 text-[14px] font-semibold text-black tabular-nums shadow-[0_0_0_4px_#0c0c0c]"
        style={
          vertical
            ? { right: "calc(100% + 12px)", bottom: `${share * 100}%`, transform: "translateY(50%)" }
            : { left: `${share * 100}%`, bottom: "calc(1.75rem + 12px)", transform: "translateX(-50%)" }
        }
      >
        {format(value)}
      </span>
    </div>
  );
}

export type ToastMessage = { kind: "ok" | "error"; text: string; id: number };

export function Toast({ toast, onDone }: { toast: ToastMessage | null; onDone: () => void }) {
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(onDone, toast.kind === "ok" ? 2600 : 6000);
    return () => clearTimeout(timer);
  }, [toast, onDone]);

  if (!toast) return null;
  const Icon = toast.kind === "ok" ? Check : CircleAlert;
  return (
    <div className="pointer-events-none fixed inset-x-0 top-[calc(max(env(safe-area-inset-top),12px)+8px)] z-50 flex justify-center px-4">
      <button
        key={toast.id}
        onClick={onDone}
        className="toast-in pointer-events-auto flex min-h-12 max-w-full items-center gap-2.5 rounded-full bg-white py-3 pr-5 pl-4 text-left text-[15px] font-medium text-black shadow-[0_8px_40px_rgba(0,0,0,0.6)]"
      >
        <Icon size={19} strokeWidth={2.2} className="shrink-0" />
        <span>{toast.text}</span>
      </button>
    </div>
  );
}

export function CloseButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      aria-label="Close"
      className="press grid h-9 w-9 place-items-center rounded-full bg-surface-2 text-muted active:text-white"
    >
      <X size={18} strokeWidth={2} />
    </button>
  );
}
