"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/**
 * What the page becomes once the planet has risen out of the way.
 *
 * These sections scroll over the pinned scene, so every surface here is a
 * translucent wash rather than a solid panel — the sky and the globe's limb
 * stay faintly visible behind the copy, which is what keeps the landing
 * page reading as one continuous place rather than a second screen.
 */

/** How SatQuery works: the three core steps. */
const PIPELINE = [
  {
    step: "01",
    title: "Understand",
    body: "SatQuery understands your question and identifies what needs to be analyzed.",
  },
  {
    step: "02",
    title: "Analyze",
    body: "It selects the right satellite imagery and analysis methods.",
  },
  {
    step: "03",
    title: "Explain",
    body: "You get a clear result backed by the imagery used for the analysis.",
  },
];

/** The capabilities worth naming on a landing page. */
const CAPABILITIES = [
  {
    label: "Change over time",
    detail: "See what changed between two dates.",
    description: "Compare satellite imagery from two dates and surface meaningful change patterns across a landscape.",
    tag: "Temporal view",
    preview:
      "linear-gradient(135deg, rgba(71, 118, 147, 0.65), rgba(7, 24, 31, 0.9)), linear-gradient(90deg, rgba(121, 220, 212, 0.24), rgba(255, 180, 117, 0.18))",
  },
  {
    label: "Land cover",
    detail: "Understand how land use has changed.",
    description: "Map vegetation, bare ground, water, built structures, and other land classes from a single image.",
    tag: "Classification",
    preview:
      "linear-gradient(135deg, rgba(34, 51, 69, 0.8), rgba(10, 30, 43, 0.88)), linear-gradient(90deg, rgba(83, 201, 154, 0.55), rgba(110, 148, 184, 0.35), rgba(171, 141, 102, 0.45))",
  },
  {
    label: "Object detection",
    detail: "Identify and count relevant objects in a scene.",
    description: "Spot vehicles, structures, and other notable objects at a glance and estimate what stands out in context.",
    tag: "Feature scan",
    preview:
      "linear-gradient(135deg, rgba(18, 34, 49, 0.9), rgba(15, 22, 36, 0.82)), radial-gradient(circle at 25% 30%, rgba(92, 210, 220, 0.7), transparent 22%), radial-gradient(circle at 72% 52%, rgba(255, 182, 120, 0.7), transparent 18%)",
  },
  {
    label: "Scene analysis",
    detail: "Explore what is visible in satellite imagery.",
    description: "Read the broader story of a place: roads, terrain, built form, and visible patterns in the landscape.",
    tag: "Context map",
    preview:
      "linear-gradient(135deg, rgba(12, 18, 29, 0.82), rgba(18, 38, 52, 0.88)), linear-gradient(120deg, rgba(66, 121, 131, 0.34), rgba(172, 209, 220, 0.2), rgba(143, 130, 110, 0.32))",
  },
];

export default function LandingSections() {
  const router = useRouter();
  const [activeCapability, setActiveCapability] = useState(CAPABILITIES[0]);

  return (
    <div className="relative z-10">
      {/* ── Pipeline ──────────────────────────────────────────────────── */}
      <section className="mx-auto max-w-6xl px-6 pb-24 pt-16 sm:px-10">
        <SectionLabel>How SatQuery AI works</SectionLabel>

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
        <SectionLabel>What can SatQuery AI help you explore?</SectionLabel>

        <div className="mt-10">
          <div className="flex flex-col gap-3 md:flex-row md:items-stretch">
            {CAPABILITIES.map((cap) => {
              const isActive = activeCapability.label === cap.label;

              return (
                <button
                  key={cap.label}
                  type="button"
                  aria-pressed={isActive}
                  aria-label={cap.label}
                  onClick={() => setActiveCapability(cap)}
                  className="group relative flex min-h-[120px] w-full flex-col justify-between overflow-hidden rounded-2xl border px-4 py-4 text-left transition-all duration-300 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/70 focus-visible:ring-offset-2 focus-visible:ring-offset-transparent md:px-5"
                  style={{
                    borderColor: isActive ? "color-mix(in srgb, var(--accent) 60%, var(--hairline))" : "var(--hairline)",
                    background: isActive
                      ? "linear-gradient(180deg, color-mix(in srgb, var(--panel-wash) 78%, var(--accent) 22%), var(--panel-wash))"
                      : "var(--panel-wash)",
                    boxShadow: isActive ? "0 0 0 1px color-mix(in srgb, var(--accent) 28%, transparent), 0 18px 36px rgba(15, 21, 29, 0.18)" : "none",
                    transform: isActive ? "translateY(-1px)" : "translateY(0)",
                    flex: isActive ? "1.4 1 0%" : "1 1 0%",
                    opacity: isActive ? 1 : 0.8,
                  }}
                >
                  <span
                    className="font-mono text-[10px] uppercase tracking-[0.18em]"
                    style={{ color: isActive ? "var(--accent)" : "var(--ink-muted)" }}
                  >
                    {cap.tag}
                  </span>

                  <div className="mt-4">
                    <h3
                      className="text-[15px] font-medium leading-tight"
                      style={{
                        color: "var(--ink-primary)",
                        fontFamily: "var(--font-grotesk-display)",
                      }}
                    >
                      {cap.label}
                    </h3>
                    <p
                      className="mt-1.5 text-[12px] leading-relaxed"
                      style={{ color: isActive ? "var(--ink-primary)" : "var(--ink-muted)" }}
                    >
                      {cap.detail}
                    </p>
                  </div>

                  <div
                    className="mt-4 h-1.5 w-full rounded-full transition-all duration-300"
                    style={{
                      background: isActive
                        ? "linear-gradient(90deg, var(--accent), transparent)"
                        : "rgba(160, 200, 235, 0.12)",
                    }}
                  />
                </button>
              );
            })}
          </div>

          <div
            id={`capability-panel-${activeCapability.label}`}
            className="mt-5 overflow-hidden rounded-[1.75rem] border transition-all duration-300 ease-out"
            style={{
              borderColor: "var(--hairline)",
              background: "linear-gradient(180deg, color-mix(in srgb, var(--panel-wash) 92%, transparent), var(--panel-wash))",
              boxShadow: "inset 0 1px 0 rgba(255,255,255,0.04)",
            }}
          >
            <div className="grid gap-6 px-4 py-5 sm:px-6 sm:py-6 lg:grid-cols-[1.2fr_0.8fr] lg:items-center">
              <div>
                <span
                  className="font-mono text-[10px] uppercase tracking-[0.2em]"
                  style={{ color: "var(--accent)" }}
                >
                  Selected analysis
                </span>

                <h3
                  className="mt-3 text-2xl sm:text-3xl"
                  style={{
                    color: "var(--ink-primary)",
                    fontFamily: "var(--font-grotesk-display)",
                  }}
                >
                  {activeCapability.label}
                </h3>

                <p
                  className="mt-3 max-w-xl text-sm leading-relaxed sm:text-[15px]"
                  style={{ color: "var(--ink-muted)" }}
                >
                  {activeCapability.description}
                </p>

                <button
                  type="button"
                  onClick={() => router.push("/analyze")}
                  className="mt-6 inline-flex cursor-pointer items-center gap-2 rounded-full border px-4 py-2.5 text-sm font-medium transition-all duration-200 hover:-translate-y-0.5 hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/70 focus-visible:ring-offset-2 focus-visible:ring-offset-transparent"
                  style={{
                    borderColor: "color-mix(in srgb, var(--accent) 45%, var(--hairline))",
                    background: "linear-gradient(120deg, var(--accent), color-mix(in srgb, var(--accent) 55%, var(--accent-warm)))",
                    color: "var(--background)",
                    fontFamily: "var(--font-grotesk-display)",
                  }}
                >
                  Try this analysis <span aria-hidden="true">→</span>
                </button>
              </div>

              <div
                className="relative h-52 overflow-hidden rounded-2xl border"
                style={{
                  borderColor: "var(--hairline)",
                  background: activeCapability.preview,
                  boxShadow: "inset 0 1px 0 rgba(255,255,255,0.07)",
                }}
              >
                <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(255,255,255,0.12),transparent_38%)]" />
                <div className="absolute inset-x-6 bottom-5 rounded-xl border border-white/10 bg-black/15 p-3 backdrop-blur-sm">
                  <div className="flex items-center justify-between gap-3">
                    <span
                      className="font-mono text-[10px] uppercase tracking-[0.18em]"
                      style={{ color: "rgba(234, 243, 255, 0.8)" }}
                    >
                      {activeCapability.tag}
                    </span>
                    <span
                      className="font-mono text-[10px] uppercase tracking-[0.18em]"
                      style={{ color: "rgba(234, 243, 255, 0.75)" }}
                    >
                      SatQuery
                    </span>
                  </div>

                  <div className="mt-3 grid grid-cols-3 gap-2">
                    {["", "", ""].map((_, idx) => (
                      <div
                        key={idx}
                        className="h-12 rounded-md border border-white/10"
                        style={{
                          background:
                            idx === 0
                              ? "rgba(92, 210, 220, 0.22)"
                              : idx === 1
                                ? "rgba(145, 180, 120, 0.26)"
                                : "rgba(255, 182, 120, 0.2)",
                        }}
                      />
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
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
          Upload imagery, ask questions, and review the analysis with evidence backed by satellite data.
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
          className="mt-10 cursor-pointer rounded-lg px-8 py-4 text-[15px] font-medium transition-[filter,transform] duration-200 hover:brightness-110 active:scale-[0.98]"
          style={{
            fontFamily: "var(--font-grotesk-display)",
            background:
              "linear-gradient(120deg, var(--accent), color-mix(in srgb, var(--accent) 55%, var(--accent-warm)))",
            color: "var(--background)",
          }}
        >
          Open workspace →
        </button>
      </section>
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
