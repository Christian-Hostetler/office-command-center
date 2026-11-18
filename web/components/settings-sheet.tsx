"use client";

import { useState } from "react";
import { BrainUnreachable, cleanBrainUrl, HttpBrain, LOCAL, saveBrainUrl, savedBrainUrl } from "@/lib/brain";
import type { ScheduleEntry } from "@/lib/types";
import { CloseButton, Sheet } from "./ui";

type Check = { state: "idle" | "checking" | "ok" | "failed"; message: string };

function clock(at: string) {
  const [hour, minute] = at.split(":").map(Number);
  return `${hour % 12 || 12}:${String(minute).padStart(2, "0")} ${hour < 12 ? "am" : "pm"}`;
}

export function SettingsSheet({
  open,
  onClose,
  demo,
  reach,
  officeName,
  schedule,
  onConnect,
}: {
  open: boolean;
  onClose: () => void;
  demo: boolean;
  reach: "loading" | "ok" | "unreachable";
  officeName?: string;
  schedule: ScheduleEntry[];
  onConnect: (url: string) => void;
}) {
  const [url, setUrl] = useState("");
  const [check, setCheck] = useState<Check>({ state: "idle", message: "" });
  const [wasOpen, setWasOpen] = useState(false);

  // Each time the sheet opens, start from the address that's saved on this phone.
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setUrl(savedBrainUrl());
      setCheck({ state: "idle", message: "" });
    }
  }

  const adopt = (address: string) => {
    saveBrainUrl(address);
    onConnect(address);
  };

  async function connect() {
    const address = cleanBrainUrl(url);
    setUrl(address);
    if (!address) {
      adopt("");
      setCheck({ state: "ok", message: "Using the demo" });
      return;
    }
    setCheck({ state: "checking", message: "Checking" });
    try {
      const state = await new HttpBrain(address).state();
      adopt(address);
      setCheck({ state: "ok", message: `Connected to ${state.name}` });
    } catch (err) {
      const message =
        err instanceof BrainUnreachable ? "Couldn't reach it. Is Tailscale on?" : err instanceof Error ? err.message : "";
      setCheck({ state: "failed", message });
    }
  }

  let connection = "Demo. Nothing is connected yet.";
  if (!demo && reach === "ok") connection = `Connected to ${officeName ?? "the Mac mini"}`;
  else if (!demo && reach === "unreachable")
    connection = LOCAL ? "Can't reach the Mac mini. Are you on the office Wi-Fi?" : "Can't reach the Mac mini right now";
  else if (!demo) connection = "Connecting";

  return (
    <Sheet open={open} onClose={onClose}>
      <div className="px-5 pt-1 pb-2">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="semiwide text-[22px] leading-tight font-semibold">Settings</h2>
            <p className="mt-1 text-[14px] text-muted">{connection}</p>
          </div>
          <CloseButton onClick={onClose} />
        </div>

        {schedule.length > 0 && (
          <section className="mt-8">
            <h3 className="text-[14px] text-muted">Every day</h3>
            <ul className="mt-2 divide-y divide-line rounded-2xl border border-line bg-surface">
              {schedule.map((entry) => (
                <li key={entry.at} className="flex h-13 items-center justify-between px-4 text-[16px]">
                  <span>{entry.name}</span>
                  <span className="text-muted tabular-nums">{clock(entry.at)}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {!LOCAL && (
          <>
        <label htmlFor="brain-url" className="mt-8 block text-[14px] text-muted">
          Mac mini address
        </label>
        <input
          id="brain-url"
          type="url"
          inputMode="url"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          placeholder="mac-mini.your-tailnet.ts.net"
          value={url}
          onChange={(e) => {
            setUrl(e.target.value);
            setCheck({ state: "idle", message: "" });
          }}
          onKeyDown={(e) => e.key === "Enter" && connect()}
          className="mt-2 h-13 w-full rounded-2xl border border-line bg-surface px-4 text-[16px] text-white outline-none placeholder:text-faint focus:border-muted"
        />
        <p className="mt-2 text-[13px] leading-snug text-muted">
          The Tailscale address of the Mac mini. Leave it empty to use the demo.
        </p>

        <button
          onClick={connect}
          disabled={check.state === "checking"}
          className="press mt-6 h-14 w-full rounded-full bg-white text-[16px] font-semibold text-black disabled:opacity-60"
        >
          {check.state === "checking" ? "Checking" : "Save and connect"}
        </button>

        <div className="mt-4 flex min-h-6 items-center justify-center gap-3 text-[14px]">
          {check.state !== "idle" && check.state !== "checking" && (
            <span className={check.state === "failed" ? "text-white" : "text-muted"}>{check.message}</span>
          )}
          {check.state === "failed" && (
            <button onClick={() => adopt(cleanBrainUrl(url))} className="text-muted underline underline-offset-4">
              Save anyway
            </button>
          )}
        </div>
          </>
        )}
      </div>
    </Sheet>
  );
}
