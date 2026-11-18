import type { Device, DeviceChange, OfficeState, Run, StepResult } from "./types";

export interface Brain {
  readonly demo: boolean;
  state(): Promise<OfficeState>;
  runMode(id: string): Promise<{ run: Run; state: OfficeState }>;
  setDevice(id: string, change: DeviceChange): Promise<{ result: StepResult; state: OfficeState }>;
}

export class BrainUnreachable extends Error {}

const STORAGE_KEY = "occ.brain";

// The copy of the app the Mac mini serves on the office Wi-Fi (deploy.sh builds it). It talks to the
// mini that served it, so there's no address to type.
export const LOCAL = process.env.NEXT_PUBLIC_LOCAL === "1";

export function savedBrainUrl(): string {
  if (LOCAL) return window.location.origin;
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved !== null) return saved;
  } catch {}
  return process.env.NEXT_PUBLIC_BRAIN_URL ?? "";
}

export function saveBrainUrl(url: string) {
  try {
    localStorage.setItem(STORAGE_KEY, url);
  } catch {}
}

export function cleanBrainUrl(raw: string): string {
  const url = raw.trim().replace(/\/+$/, "");
  if (!url) return "";
  return /^https?:\/\//.test(url) ? url : `https://${url}`;
}

export class HttpBrain implements Brain {
  readonly demo = false;
  constructor(private readonly url: string) {}

  private async call<T>(path: string, body?: object, timeoutMs = 6000): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let response: Response;
    try {
      response = await fetch(this.url + path, {
        method: body ? "POST" : "GET",
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
        cache: "no-store",
        signal: controller.signal,
      });
    } catch {
      throw new BrainUnreachable("Can't reach the Mac mini");
    } finally {
      clearTimeout(timer);
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error ?? `The brain answered ${response.status}`);
    return data as T;
  }

  state() {
    return this.call<OfficeState>("/api/state", undefined, 5000);
  }

  runMode(id: string) {
    // A mode fades the lights and gives the camera a few seconds, so it can take a while.
    return this.call<{ run: Run; state: OfficeState }>(`/api/modes/${id}`, {}, 25000);
  }

  setDevice(id: string, change: DeviceChange) {
    return this.call<{ result: StepResult; state: OfficeState }>(`/api/devices/${id}`, change, 10000);
  }
}

// Demo: a pretend office that runs in the browser, so the app can be tried before the brain is connected.

type Target = "on" | "off" | { brightness: number; kelvin: number };

const DEMO_MODES: { id: string; name: string; note: string; set: Record<string, Target> }[] = [
  {
    id: "deep-work",
    name: "Deep Work",
    note: "Lamps only",
    set: { main: "off", fill: "off", bookshelf: "on", camera: "off" },
  },
  {
    id: "meetings",
    name: "Meetings",
    note: "Soft light, webcam",
    set: {
      main: { brightness: 60, kelvin: 4000 },
      fill: { brightness: 30, kelvin: 4000 },
      bookshelf: "on",
      camera: "off",
    },
  },
  {
    id: "filming",
    name: "Filming",
    note: "Warm side, camera on",
    set: {
      main: { brightness: 45, kelvin: 5200 },
      fill: { brightness: 20, kelvin: 2900 },
      bookshelf: "on",
      camera: "on",
    },
  },
  {
    id: "shutdown",
    name: "Shutdown",
    note: "Everything off",
    set: { main: "off", fill: "off", bookshelf: "off", camera: "off" },
  },
];

function demoDevice(id: string, name: string, kind: Device["kind"], on: boolean): Device {
  return {
    id,
    name,
    kind,
    configured: true,
    online: true,
    on,
    brightness: kind === "keylight" ? 60 : null,
    kelvin: kind === "keylight" ? 4000 : null,
    error: null,
    lastSeen: Date.now() / 1000,
  };
}

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export class DemoBrain implements Brain {
  readonly demo = true;
  private devices: Device[] = [
    demoDevice("main", "Main light", "keylight", false),
    demoDevice("fill", "Fill light", "keylight", false),
    demoDevice("bookshelf", "Backlights", "plug", true),
    demoDevice("camera", "Camera", "plug", false),
  ];
  private lastMode: string | null = "deep-work";
  private lastRun: Run | null = null;

  private matches(mode: (typeof DEMO_MODES)[number]) {
    return Object.entries(mode.set).every(([id, target]) => {
      const device = this.devices.find((d) => d.id === id)!;
      if (target === "on" || target === "off") return device.on === (target === "on");
      return device.on && device.brightness === target.brightness && device.kelvin === target.kelvin;
    });
  }

  private snapshot(): OfficeState {
    const matching = DEMO_MODES.filter((m) => this.matches(m)).map((m) => m.id);
    return {
      name: "Office",
      time: new Date().toISOString(),
      devices: this.devices.map((d) => ({ ...d })),
      modes: DEMO_MODES.map(({ id, name, note }) => ({ id, name, note })),
      activeMode: matching.includes(this.lastMode ?? "") ? this.lastMode : (matching[0] ?? null),
      lastMode: this.lastMode,
      running: null,
      lastRun: this.lastRun,
    };
  }

  async state() {
    return this.snapshot();
  }

  async runMode(id: string) {
    const mode = DEMO_MODES.find((m) => m.id === id);
    if (!mode) throw new Error(`No mode called ${id}`);
    await wait(900);
    const results: StepResult[] = Object.entries(mode.set).map(([deviceId, target]) => {
      const device = this.devices.find((d) => d.id === deviceId)!;
      if (target === "on" || target === "off") device.on = target === "on";
      else Object.assign(device, { on: true, brightness: target.brightness, kelvin: target.kelvin });
      return { device: deviceId, name: device.name, status: "ok", ms: 40 };
    });
    this.lastMode = id;
    this.lastRun = { mode: id, ok: true, at: new Date().toISOString(), ms: 900, results };
    return { run: this.lastRun, state: this.snapshot() };
  }

  async setDevice(id: string, change: { on?: boolean; brightness?: number; kelvin?: number }) {
    const device = this.devices.find((d) => d.id === id);
    if (!device) throw new Error(`No device called ${id}`);
    await wait(60);
    device.on = change.on ?? true;
    if (change.brightness !== undefined) device.brightness = change.brightness;
    if (change.kelvin !== undefined) device.kelvin = change.kelvin;
    return { result: { device: id, name: device.name, status: "ok" as const, ms: 60 }, state: this.snapshot() };
  }
}
