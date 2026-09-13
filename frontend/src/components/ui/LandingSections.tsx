"use client";

import { useRouter } from "next/navigation";

/**
 * What the page becomes once the planet has risen out of the way.
 *
 * These sections scroll over the pinned scene, so every surface here is a
 * translucent wash rather than a solid panel — the sky and the globe's limb
 * stay faintly visible behind the copy, which is what keeps the landing
 * page reading as one continuous place rather than a second screen.
 */

/** What the system actually does, in the order it does it. */
const PIPELINE = [
  {
    step: "01",
    title: "Plan",
    body: "A question in plain language is decomposed into the steps that answer it — which scenes, which window in time, which comparison.",
  },
  {
    step: "02",
    title: "Route",
    body: "Each step goes to the model built for it: change detection, land-cover segmentation, object counting, or a vision-language read of the scene.",
  },
  {
    step: "03",
    title: "Ground",
    body: "Every claim comes back attached to the imagery and the model that produced it, so an answer can be checked rather than taken on trust.",
  },
];

/** The capabilities worth naming on a landing page. */
const CAPABILITIES = [
  { label: "Change over time", detail: "Two dates, one scene, what moved." },
  { label: "Land cover", detail: "Segmented and quantified by class." },
  { label: "Object counts", detail: "Vessels, aircraft, structures, plots." },
  { label: "Scene search", detail: "Find the imagery worth looking at." },
];

export default function LandingSections() {
  const router = useRouter();

  return (
    <div className="relative z-10">
      {/* ── Pipeline ──────────────────────────────────────────────────── */}
      <section className="mx-auto max-w-6xl px-6 pb-24 pt-16 sm:px-10">
        <SectionLabel>How an answer gets made</SectionLabel>

        <div className="mt-10 grid gap-4 md:grid-cols-3">
          {PIPELINE.map((item) => (
            <article
              key={item.step}
              className="rounded-2xl border p-6 backdrop-blur-md"
              style={{
                borderColor: "var(--hairline)",
                background: "var(--panel-wash)",
              }}
            >
              <span
                className="font-mono text-[10px] tracking-[0.2em]"
                style={{ color: "var(--accent)" }}
              >
                {item.step}
              </span>
              <h3
                className="mt-3 text-xl font-medium tracking-[-0.01em]"
                style={{
                  color: "var(--ink-primary)",
                  fontFamily: "var(--font-grotesk-display)",
                }}
              >
                {item.title}
              </h3>
              <p
                className="mt-2 text-sm leading-relaxed"
                style={{ color: "var(--ink-muted)" }}
              >
                {item.body}
              </p>
            </article>
          ))}
        </div>
      </section>

      {/* ── Capabilities ──────────────────────────────────────────────── */}
      <section className="mx-auto max-w-6xl px-6 pb-28 sm:px-10">
        <SectionLabel>What you can ask it</SectionLabel>

        <div className="mt-10 grid gap-px overflow-hidden rounded-2xl border sm:grid-cols-2 lg:grid-cols-4"
          style={{ borderColor: "var(--hairline)", background: "var(--hairline)" }}
        >
          {CAPABILITIES.map((cap) => (
            <div
              key={cap.label}
              className="p-6 backdrop-blur-md"
              style={{ background: "var(--panel-wash)" }}
            >
              <h3
                className="text-[15px] font-medium"
                style={{
                  color: "var(--ink-primary)",
                  fontFamily: "var(--font-grotesk-display)",
                }}
              >
                {cap.label}
              </h3>
              <p
                className="mt-1.5 text-[13px] leading-relaxed"
                style={{ color: "var(--ink-muted)" }}
              >
                {cap.detail}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Closing call to action ────────────────────────────────────── */}
      <section className="mx-auto max-w-3xl px-6 pb-32 text-center sm:px-10">
        <h2
          className="text-balance text-4xl font-medium leading-[1.05] tracking-[-0.03em] sm:text-5xl"
          style={{
            color: "var(--ink-primary)",
            fontFamily: "var(--font-grotesk-display)",
          }}
        >
          Put a question to the planet.
        </h2>
        <p
          className="mx-auto mt-5 max-w-md text-pretty text-sm leading-relaxed sm:text-base"
          style={{ color: "var(--ink-muted)" }}
        >
          The workspace is where the imagery, the agent trace and the evidence
          all land together.
        </p>

        {/*
          A plain push rather than the hero's flying exit: by the time anyone
          reads this the planet is long off-screen, and animating a departure
          for something nobody can see is just latency before the click
          resolves.
        */}
        <button
          type="button"
          onClick={() => router.push("/analyze")}
          className="mt-10 cursor-pointer rounded-full px-8 py-4 text-[15px] font-medium transition-[filter,transform] duration-200 hover:brightness-110 active:scale-[0.98]"
          style={{
            fontFamily: "var(--font-grotesk-display)",
            background:
              "linear-gradient(120deg, var(--accent), color-mix(in srgb, var(--accent) 55%, var(--accent-warm)))",
            color: "var(--background)",
          }}
        >
          Open the workspace →
        </button>
      </section>

      {/* ── Status strip ──────────────────────────────────────────────── */}
      <footer
        className="flex flex-wrap items-center justify-between gap-2 border-t px-6 py-4 font-mono text-[10px] backdrop-blur-md sm:px-10"
        style={{
          borderColor: "var(--hairline)",
          background: "var(--footer-wash)",
          color: "var(--ink-faint)",
        }}
      >
        <span>EVIDENCE-GROUNDED · MODEL PROVENANCE EXPOSED</span>
        <span>SIH 2026 · SIH26167 · SPACE TECHNOLOGY</span>
      </footer>
    </div>
  );
}

/** Shared eyebrow for the sections below the fold. */
function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <span
      className="font-mono text-[10px] uppercase tracking-[0.2em]"
      style={{ color: "var(--ink-muted)" }}
    >
      {children}
    </span>
  );
}
