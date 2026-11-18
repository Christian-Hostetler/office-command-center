"use client";

import dynamic from "next/dynamic";

// The app runs only in the browser: it reads the Mac mini's address from this phone and talks to it directly.
export const OfficeLoader = dynamic(() => import("./office").then((m) => m.Office), {
  ssr: false,
  loading: () => <div className="min-h-dvh bg-black" />,
});
