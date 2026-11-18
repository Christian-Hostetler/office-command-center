import { Camera, Circle, Clapperboard, Focus, Lamp, LampFloor, Power, Video, type LucideProps } from "lucide-react";
import type { Device } from "@/lib/types";

// An Elgato Key Light from the side: a flat panel on a pole.
export function KeyLightIcon({ size = 24, strokeWidth = 1.6, ...props }: LucideProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <rect x="4" y="3" width="16" height="10" rx="2.5" />
      <path d="M12 13v8M8.5 21h7" />
    </svg>
  );
}

const MODE_ICONS: Record<string, typeof Focus> = {
  "deep-work": Focus,
  meetings: Video,
  filming: Clapperboard,
  shutdown: Power,
};

export function ModeIcon({ id, ...props }: { id: string } & LucideProps) {
  const Icon = MODE_ICONS[id] ?? Circle;
  return <Icon strokeWidth={1.6} {...props} />;
}

export function DeviceIcon({ device, ...props }: { device: Device } & LucideProps) {
  if (device.kind === "keylight") return <KeyLightIcon {...props} />;
  if (device.id === "camera") return <Camera strokeWidth={1.6} {...props} />;
  if (device.id === "floor") return <LampFloor strokeWidth={1.6} {...props} />;
  return <Lamp strokeWidth={1.6} {...props} />;
}
