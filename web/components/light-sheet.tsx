"use client";

import { useCallback, useEffect, useRef } from "react";
import type { Device, DeviceChange } from "@/lib/types";
import { buzz, CloseButton, Ladder, Sheet } from "./ui";

// Sends the newest value as soon as the last one lands, so dragging feels live without flooding the light.
function useLatestSender(send: (change: DeviceChange) => Promise<void>) {
  const inflight = useRef(false);
  const queued = useRef<DeviceChange | null>(null);
  const sendRef = useRef(send);
  useEffect(() => {
    sendRef.current = send;
  });

  return useCallback((change: DeviceChange) => {
    const pump = async (next: DeviceChange) => {
      inflight.current = true;
      try {
        await sendRef.current(next);
      } finally {
        inflight.current = false;
        const waiting = queued.current;
        queued.current = null;
        if (waiting) pump(waiting);
      }
    };
    if (inflight.current) queued.current = { ...queued.current, ...change };
    else pump(change);
  }, []);
}

// The light itself, drawn as a panel that glows as brightly as the real one.
function Panel({ level }: { level: number }) {
  const t = level / 100;
  return (
    <div className="flex flex-col items-center" aria-hidden>
      <div
        className="h-[96px] w-[150px] rounded-[20px] border transition-[background-color,box-shadow,border-color] duration-300"
        style={{
          background: level ? `rgba(255,255,255,${0.14 + 0.86 * t})` : "var(--surface-2)",
          borderColor: level ? "transparent" : "var(--line)",
          boxShadow: level ? `0 0 ${24 + 90 * t}px ${4 + 26 * t}px rgba(255,255,255,${0.05 + 0.2 * t})` : "none",
        }}
      />
      <div className="h-[68px] w-[3px] bg-faint" />
      <div className="h-[3px] w-[72px] rounded-full bg-faint" />
    </div>
  );
}

export function LightSheet({
  light,
  open,
  onClose,
  onChange,
  send,
}: {
  light: Device | null;
  open: boolean;
  onClose: () => void;
  onChange: (change: DeviceChange) => void;
  send: (change: DeviceChange) => Promise<void>;
}) {
  const sendLatest = useLatestSender(send);

  const change = (next: DeviceChange) => {
    onChange(next);
    sendLatest(next);
  };

  const on = Boolean(light?.on);
  const brightness = light?.brightness ?? 50;
  const kelvin = light?.kelvin ?? 4500;

  return (
    <Sheet open={open} onClose={onClose}>
      {light && (
        <div className="px-5 pt-1">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="semiwide text-[22px] leading-tight font-semibold">{light.name}</h2>
              <p className="mt-1 text-[14px] text-muted tabular-nums">{on ? `${brightness}%, ${kelvin} K` : "Off"}</p>
            </div>
            <CloseButton onClick={onClose} />
          </div>

          <div className="mt-6 flex h-[300px] gap-5">
            <div className="flex flex-1 items-center justify-center">
              <Panel level={on ? brightness : 0} />
            </div>
            <div className="w-[92px] py-1.5">
              <Ladder
                vertical
                label="Brightness"
                value={on ? brightness : 3}
                min={3}
                max={100}
                ticks={26}
                format={(v) => `${v}%`}
                onChange={(v) => change({ on: true, brightness: v })}
                onCommit={buzz}
              />
            </div>
          </div>

          <div className="mt-10">
            <Ladder
              label="Color temperature"
              value={kelvin}
              min={2900}
              max={7000}
              step={100}
              ticks={36}
              format={(v) => `${v} K`}
              onChange={(v) => change({ on: true, kelvin: v })}
              onCommit={buzz}
            />
            <div className="mt-2.5 flex justify-between text-[13px] text-muted">
              <span>Warm</span>
              <span>Cool</span>
            </div>
          </div>

          <button
            onClick={() => {
              buzz();
              change({ on: !on });
            }}
            className={`press mt-7 h-14 w-full rounded-full text-[16px] font-semibold ${
              on ? "border border-white/25 text-white" : "bg-white text-black"
            }`}
          >
            {on ? "Turn off" : "Turn on"}
          </button>
        </div>
      )}
    </Sheet>
  );
}
