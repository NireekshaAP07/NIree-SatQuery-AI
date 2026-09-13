/**
 * Scroll position of the landing page, shared with the WebGL scene.
 *
 * This is module-level mutable state rather than React state on purpose.
 * The globe reads it inside `useFrame`, which runs on every animation
 * frame; routing a scroll position through `useState` would re-render the
 * whole hero subtree dozens of times a second to move one Three.js group.
 * The scroll handler writes a number, the frame loop reads it, and React
 * is not involved at all.
 *
 * `raw` is where the page actually is. `eased` is what the scene follows —
 * it chases `raw` a little behind, which is what keeps a trackpad flick
 * from snapping the planet instead of carrying it.
 */
export const heroScroll = {
  /** 0 at the top of the page, 1 once the hero has been scrolled fully past. */
  raw: 0,
  /** Damped follower of `raw`; this is the value the scene should use. */
  eased: 0,
};

/** How much of the viewport you scroll through before the planet has fully
 *  risen. Just under one screen: the planet is clear of the frame about
 *  when the first section finishes arriving, so the sections below are read
 *  against open sky rather than against a planet still sweeping past. */
const TRAVEL_FRACTION = 0.95;

/** Per-second approach rate of `eased` toward `raw`. High enough to feel
 *  directly connected to the wheel, low enough to smooth the steps. */
const FOLLOW_RATE = 6.5;

function read() {
  const travel = window.innerHeight * TRAVEL_FRACTION;
  if (travel <= 0) {
    heroScroll.raw = 0;
    return;
  }
  heroScroll.raw = Math.min(1, Math.max(0, window.scrollY / travel));
}

/**
 * Start tracking page scroll. Returns the matching teardown, so a caller can
 * hand it straight back from `useEffect`.
 *
 * The listener only stores a number — no layout reads beyond `scrollY` and
 * `innerHeight`, both cheap — so it stays passive and never blocks the
 * scroll thread.
 */
export function trackHeroScroll(): () => void {
  read();
  // Coming back to the hero via the browser's back button restores a scroll
  // offset before this runs; seeding `eased` from `raw` means the planet is
  // already where that offset says it should be instead of flying up to it.
  heroScroll.eased = heroScroll.raw;

  const onScroll = () => read();
  const onResize = () => read();

  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onResize, { passive: true });

  return () => {
    window.removeEventListener("scroll", onScroll);
    window.removeEventListener("resize", onResize);
  };
}

/** Advance the damped follower. Call once per frame with the frame delta. */
export function stepHeroScroll(delta: number): number {
  const k = 1 - Math.exp(-FOLLOW_RATE * delta);
  heroScroll.eased += (heroScroll.raw - heroScroll.eased) * k;
  return heroScroll.eased;
}

/** Reset to the top. Used when the hero remounts after a route change. */
export function resetHeroScroll() {
  heroScroll.raw = 0;
  heroScroll.eased = 0;
}
