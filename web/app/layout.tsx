import type { Metadata, Viewport } from "next";
import { Archivo } from "next/font/google";
import "./globals.css";

// Archivo is a 19th century American grotesque cut for technical use. Its wide width reads like the
// labels stamped on lighting and camera gear, which suits a control panel.
const archivo = Archivo({
  subsets: ["latin"],
  axes: ["wdth"],
  variable: "--font-archivo",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Office",
  description: "One tap modes for the office lights, lamps and camera.",
  applicationName: "Office",
  // A plain file in public/, so the Mac mini's copy of the app has it too.
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "Office", statusBarStyle: "black-translucent" },
  formatDetection: { telephone: false },
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
  themeColor: "#000000",
  colorScheme: "dark",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={archivo.variable}>
      <body className="min-h-dvh font-sans">{children}</body>
    </html>
  );
}
