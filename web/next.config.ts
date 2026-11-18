import type { NextConfig } from "next";

// deploy.sh sets OFFICE_LOCAL=1 to build the app as plain files the brain serves on the office Wi-Fi.
const local = process.env.OFFICE_LOCAL === "1";

const nextConfig: NextConfig = {
  // Plain files can't do partial prerendering, and the app runs in the browser anyway.
  ...(local
    ? { output: "export" as const, env: { NEXT_PUBLIC_LOCAL: "1" } }
    : { cacheComponents: true, partialPrefetching: true }),
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
