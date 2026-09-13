import type { Metadata } from "next";
import { Instrument_Serif, Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";

import SpaceBackdrop from "@/components/app/SpaceBackdrop";
import ThemeSync from "@/components/app/ThemeSync";

/**
 * The display face for the headline.
 *
 * next/font downloads and self-hosts the files at build time, so this keeps
 * the original "no font CDN at runtime" constraint — nothing is fetched from
 * a third party when the page loads, and there's no layout shift or
 * render-blocking stylesheet. A real high-contrast serif rather than
 * whatever serif the OS happens to supply.
 *
 * Both cuts ship: the headline's second line is set in the true italic, and
 * a real italic is a different drawing of the letters — not the upright
 * sheared over, which is what the browser synthesises if the cut is absent.
 */
const display = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  display: "swap",
  variable: "--font-display",
});

/**
 * The masthead face. A geometric grotesque with a tall x-height, set very
 * large and tight — it is what carries the centred hero, while the serif
 * above stays available for editorial moments.
 *
 * Variable weight, so 500/700 cost nothing extra over 400: one file covers
 * the whole range instead of a request per cut.
 */
const sans = Plus_Jakarta_Sans({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans-display",
});

export const metadata: Metadata = {
  title: "SatQuery — Ask satellite imagery anything",
  description:
    "An agentic vision-language assistant for remote-sensing imagery. Natural-language queries planned, routed to specialist models, and answered with grounded visual evidence.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`h-full antialiased ${display.variable} ${sans.variable}`}
    >
      <body className="h-full">
        {/* Both live in the root layout so they persist across navigation:
            the theme must be applied before any route paints, and the sky
            has to be the same DOM node on every screen or it visibly cuts
            when you move between them. */}
        <ThemeSync />
        <SpaceBackdrop />
        {children}
      </body>
    </html>
  );
}
