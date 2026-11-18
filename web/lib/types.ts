// The shapes the brain on the Mac mini sends back. See brain/office_brain/office.py.

export type DeviceKind = "keylight" | "plug";

export type Device = {
  id: string;
  name: string;
  kind: DeviceKind;
  configured: boolean;
  online: boolean;
  on: boolean | null;
  brightness: number | null;
  kelvin: number | null;
  error: string | null;
  lastSeen: number | null;
};

export type Mode = { id: string; name: string; note: string };

export type StepResult = {
  device: string;
  name: string;
  status: "ok" | "failed" | "skipped";
  message?: string;
  ms?: number;
};

export type Run = {
  mode: string;
  ok: boolean;
  at: string;
  ms: number;
  results: StepResult[];
};

export type OfficeState = {
  name: string;
  time: string;
  devices: Device[];
  modes: Mode[];
  activeMode: string | null;
  lastMode: string | null;
  running: string | null;
  lastRun: Run | null;
  schedule?: ScheduleEntry[];
};

export type ScheduleEntry = { at: string; mode: string; name: string };

export type DeviceChange = { on?: boolean; brightness?: number; kelvin?: number };
