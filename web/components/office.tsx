"use client";

import { Settings2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { BrainUnreachable, DemoBrain, HttpBrain, LOCAL, savedBrainUrl, type Brain } from "@/lib/brain";
import type { Device, DeviceChange, OfficeState, Run } from "@/lib/types";
import { DeviceIcon, ModeIcon } from "./icons";
import { LightSheet } from "./light-sheet";
import { SettingsSheet } from "./settings-sheet";
import { buzz, Switch, Toast, type ToastMessage } from "./ui";

type Reach = "loading" | "ok" | "unreachable";
type Overrides = Record<string, { change: DeviceChange; until: number }>;
type LightSheetState = { id: string | null; open: boolean };

const POLL_MS = 2500;

function makeBrain(url: string): Brain {
  return url ? new HttpBrain(url) : new DemoBrain();
}

function joinNames(names: string[]) {
  return names.length < 3 ? names.join(" and ") : `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
}

function describeRun(run: Run, modeName: string): Omit<ToastMessage, "id"> {
  const failed = run.results.filter((r) => r.status === "failed");
  const skipped = run.results.filter((r) => r.status === "skipped");
  if (failed.length === 1) return { kind: "error", text: `${failed[0].name} ${failed[0].message}` };
  if (failed.length) return { kind: "error", text: `${joinNames(failed.map((r) => r.name))} didn't answer` };
  if (skipped.length) return { kind: "ok", text: `${modeName} is on. ${skipped.length} not set up yet` };
  return { kind: "ok", text: "All set" };
}

function deviceLine(device: Device) {
  if (!device.configured) return "Not set up";
  if (!device.online) return device.error ? `Offline, ${device.error}` : "Offline";
  if (!device.on) return "Off";
  if (device.kind === "keylight") return `${device.brightness}%  ·  ${device.kelvin} K`;
  return "On";
}

export function Office() {
  const [brain, setBrain] = useState<Brain>(() => makeBrain(savedBrainUrl()));
  const [state, setState] = useState<OfficeState | null>(null);
  const [reach, setReach] = useState<Reach>("loading");
  const [running, setRunning] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastMessage | null>(null);
  const [lightSheet, setLightSheet] = useState<LightSheetState>({ id: null, open: false });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [overrides, setOverrides] = useState<Overrides>({});
  const toastId = useRef(0);

  const say = useCallback((message: Omit<ToastMessage, "id">) => {
    toastId.current += 1;
    setToast({ ...message, id: toastId.current });
  }, []);
  const clearToast = useCallback(() => setToast(null), []);

  const refresh = useCallback(async () => {
    try {
      setState(await brain.state());
      setReach("ok");
    } catch (err) {
      if (err instanceof BrainUnreachable) setReach("unreachable");
    }
  }, [brain]);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      if (document.visibilityState === "visible") await refresh();
      if (alive) timer = setTimeout(tick, POLL_MS);
    };
    tick();
    const onVisible = () => document.visibilityState === "visible" && refresh();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      alive = false;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refresh]);

  // While a slider is moving, show what the finger says rather than the last poll.
  const devices = (state?.devices ?? []).map((d) => (overrides[d.id] ? { ...d, ...overrides[d.id].change } : d));
  const modes = state?.modes ?? [];
  const activeMode = running ? null : (state?.activeMode ?? null);
  const activeName = modes.find((m) => m.id === activeMode)?.name;
  const runningName = modes.find((m) => m.id === running)?.name;
  const light = devices.find((d) => d.id === lightSheet.id) ?? null;

  const hold = (id: string, change: DeviceChange, ms = 3000) => {
    const until = Date.now() + ms;
    setOverrides((o) => ({ ...o, [id]: { change: { ...o[id]?.change, ...change }, until } }));
    setTimeout(() => {
      setOverrides((o) => {
        if (!o[id] || o[id].until > Date.now()) return o;
        const rest = { ...o };
        delete rest[id];
        return rest;
      });
    }, ms + 50);
  };

  async function runMode(id: string) {
    if (running || reach !== "ok") return;
    buzz();
    setRunning(id);
    try {
      const { run, state: next } = await brain.runMode(id);
      setState(next);
      setOverrides({});
      say(describeRun(run, modes.find((m) => m.id === id)?.name ?? "Mode"));
    } catch (err) {
      say({ kind: "error", text: err instanceof Error ? err.message : "Something went wrong" });
    } finally {
      setRunning(null);
    }
  }

  async function setDevice(device: Device, change: DeviceChange) {
    hold(device.id, change);
    try {
      const { result, state: next } = await brain.setDevice(device.id, change);
      setState(next);
      if (result.status === "failed") say({ kind: "error", text: `${device.name} ${result.message}` });
    } catch (err) {
      say({ kind: "error", text: err instanceof Error ? err.message : "Something went wrong" });
    }
  }

  function connect(url: string) {
    setBrain(makeBrain(url));
    setState(null);
    setReach("loading");
    setOverrides({});
  }

  let status = "Connecting";
  if (reach === "unreachable") status = "Can't reach the Mac mini";
  else if (runningName) status = `Switching to ${runningName}`;
  else if (activeName) status = `${activeName} is on`;
  else if (state) status = "No mode on";

  const disabled = reach !== "ok" || running !== null;

  return (
    <main className="mx-auto min-h-dvh max-w-[480px] px-4 pt-[max(env(safe-area-inset-top),16px)] pb-[calc(max(env(safe-area-inset-bottom),16px)+72px)]">
      <header className="flex items-start justify-between pt-5">
        <div className="min-w-0">
          <h1 className="wide text-[34px] leading-none font-semibold tracking-[-0.01em]">{state?.name ?? "Office"}</h1>
          <p className="mt-2.5 truncate text-[15px] text-muted">
            {brain.demo && <span className="text-white">Demo · </span>}
            {status}
          </p>
        </div>
        <button
          onClick={() => setSettingsOpen(true)}
          aria-label="Settings"
          className="press -mr-1 grid h-11 w-11 shrink-0 place-items-center rounded-full bg-surface text-white active:bg-surface-2"
        >
          <Settings2 size={20} strokeWidth={1.7} />
        </button>
      </header>

      {reach === "unreachable" && (
        <div className="appear mt-7 rounded-[24px] border border-line p-5">
          <p className="text-[16px] font-medium">Can&apos;t reach the Mac mini</p>
          <p className="mt-1 text-[14px] leading-snug text-muted">
            {LOCAL ? "Check that this phone is on the office Wi-Fi, then try again." : "Check that Tailscale is on, then try again."}
          </p>
          <button
            onClick={() => {
              setReach("loading");
              refresh();
            }}
            className="press mt-4 h-10 rounded-full bg-white px-5 text-[14px] font-semibold text-black"
          >
            Try again
          </button>
        </div>
      )}

      <section aria-label="Modes" className="mt-8 grid grid-cols-2 gap-2.5">
        {modes.length === 0 &&
          Array.from({ length: 4 }, (_, i) => <div key={i} className="h-[136px] animate-pulse rounded-[24px] bg-surface" />)}
        {modes.map((mode) => {
          const active = mode.id === activeMode;
          const busy = mode.id === running;
          return (
            <button
              key={mode.id}
              onClick={() => runMode(mode.id)}
              disabled={disabled && !busy}
              aria-pressed={active}
              className={`press relative flex h-[136px] flex-col justify-between overflow-hidden rounded-[24px] p-4 text-left disabled:opacity-40 ${
                active || busy ? "bg-white text-black" : "bg-surface text-white"
              }`}
            >
              <ModeIcon id={mode.id} size={24} />
              <span>
                <span className="semiwide block text-[18px] leading-tight font-semibold">{mode.name}</span>
                <span className={`mt-1 block text-[13px] leading-snug ${active || busy ? "text-black/55" : "text-muted"}`}>
                  {busy ? "Switching" : mode.note}
                </span>
              </span>
              {busy && (
                <span className="absolute inset-x-0 bottom-0 h-[3px] overflow-hidden bg-black/10">
                  <span className="sweep block h-full w-2/5 bg-black" />
                </span>
              )}
            </button>
          );
        })}
      </section>

      <section aria-label="Devices" className="mt-9">
        <h2 className="mb-2.5 px-1 text-[14px] text-muted">Devices</h2>
        <div className="divide-y divide-line overflow-hidden rounded-[24px] bg-surface">
          {devices.length === 0 &&
            Array.from({ length: 5 }, (_, i) => <div key={i} className="h-[72px] animate-pulse" />)}
          {devices.map((device) => {
            const usable = device.configured && device.online && reach === "ok";
            const isLight = device.kind === "keylight";
            return (
              <div key={device.id} className="flex h-[72px] items-center gap-3.5 px-4">
                <button
                  onClick={() => isLight && usable && setLightSheet({ id: device.id, open: true })}
                  disabled={!isLight || !usable}
                  className="flex min-w-0 flex-1 items-center gap-3.5 text-left"
                >
                  <span
                    className={`grid h-10 w-10 shrink-0 place-items-center rounded-full transition-colors duration-300 ${
                      device.on && usable ? "bg-white text-black" : "bg-surface-2 text-muted"
                    } ${!device.configured ? "border border-dashed border-faint bg-transparent" : ""}`}
                  >
                    <DeviceIcon device={device} size={19} />
                  </span>
                  <span className="min-w-0">
                    <span className={`block truncate text-[16px] font-medium ${device.configured ? "" : "text-muted"}`}>
                      {device.name}
                    </span>
                    <span className="mt-0.5 block truncate text-[13px] text-muted tabular-nums">{deviceLine(device)}</span>
                  </span>
                </button>
                <Switch
                  label={device.name}
                  checked={Boolean(device.on) && usable}
                  disabled={!usable}
                  onChange={(on) => {
                    buzz();
                    setDevice(device, { on });
                  }}
                />
              </div>
            );
          })}
        </div>
      </section>

      <LightSheet
        light={light}
        open={lightSheet.open}
        onClose={() => setLightSheet((s) => ({ ...s, open: false }))}
        onChange={(change) => light && hold(light.id, change, 4000)}
        send={(change) => (light ? setDevice(light, change) : Promise.resolve())}
      />
      <SettingsSheet
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        demo={brain.demo}
        reach={reach}
        officeName={state?.name}
        schedule={state?.schedule ?? []}
        onConnect={connect}
      />
      <Toast toast={toast} onDone={clearToast} />
    </main>
  );
}
