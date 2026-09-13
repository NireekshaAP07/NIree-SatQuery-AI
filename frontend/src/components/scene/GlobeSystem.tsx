"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";

import {
  globeDrag,
  stepGlobeDrag,
  useGlobeDragListeners,
} from "@/lib/globeDrag";
import {
  beginHeroEntry,
  globeTravelTransform,
  heroEntry,
  heroEntryEase,
  heroExit,
  heroExitEase,
  resetHeroExit,
  stepHeroEntry,
  stepHeroExit,
} from "@/lib/heroExit";
import {
  DIVE_AT,
  UPRIGHT_FRACTION,
  beginFlyAnim,
  flyAnim,
  flyEase,
  planFlight,
  resetFlyAnim,
  stepFlyAnim,
} from "@/lib/flyTo";
import { earthMeshRef } from "@/lib/earthMeshRef";
import { useFlyToStore } from "@/hooks/useFlyToStore";
import { HERO_LOOK_TARGET } from "./CameraRig";
import {
  resetHeroScroll,
  stepHeroScroll,
  trackHeroScroll,
} from "@/lib/heroScroll";

/** Fallback look target if OrbitControls isn't wired yet — mirrors the value
 *  set in CameraRig, which frames the globe centred. */
const DEFAULT_LOOK = new THREE.Vector3(...HERO_LOOK_TARGET);

/* ── Shell framing ───────────────────────────────────────────────────────
   The shell is the outer group. It carries only where the planet SITS in
   frame; the inner group carries what the planet DOES (drag, hero travel,
   fly-to). Keeping them apart means the scroll framing composes with those
   animations instead of every one of them having to know about it.        */

/** Resting pose: dropped below the centre line and oversized, so what you
 *  see is the top of a very large planet cresting the bottom edge rather
 *  than a small whole globe floating in the middle. */
const REST_Y = -2.32;
const REST_SCALE = 1.92;

/** Fully-scrolled pose: clear of the top edge and smaller with it, so the
 *  planet reads as rising AND receding rather than sliding up a rail. The
 *  end state is fully out of frame — by the time the sections are being
 *  read, they have the screen to themselves. */
const RISEN_Y = 3.6;
const RISEN_SCALE = 0.9;

/** Ease for the rise. Slow at both ends, quickest through the middle —
 *  the planet leans into the move rather than starting at full speed. */
function riseEase(t: number) {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

/** How much of the shell framing is currently applied, 0–1. Eased to 0 when
 *  a flight or a departure takes the planet, since both plan their moves in
 *  world space and would be bent by a shifted, scaled parent. Module-level
 *  for the same reason the scroll value is: it changes every frame and
 *  React has no use for it. */
const shellRelease = { value: 1 };

/**
 * Everything that belongs to the planet — the globe, its orbit ring, the
 * satellite, the scan patch and the data trace — rides inside this group,
 * so a drag turns the whole system as one rigid body instead of spinning
 * the Earth out from under a stationary orbit.
 *
 * This is also where the "fly to a place" flight is applied: while a flight
 * is live the group's rotation, position and scale are driven from the
 * flight plan and the ordinary drag/idle transforms are held off.
 */
export default function GlobeSystem({ children }: { children: ReactNode }) {
  const groupRef = useRef<THREE.Group>(null);
  const shellRef = useRef<THREE.Group>(null);
  const camera = useThree((s) => s.camera);
  const controls = useThree((s) => s.controls) as
    | { target?: THREE.Vector3 }
    | null;

  useGlobeDragListeners();

  // A completed departure leaves progress at 1, so clear it — then fly the
  // globe back in. Also clear any stale flight so a return to the hero after
  // a fly-through starts from rest, not mid-dive.
  useEffect(() => {
    resetHeroExit();
    resetFlyAnim();
    if (useFlyToStore.getState().phase !== "idle") {
      useFlyToStore.getState().reset();
    }
    beginHeroEntry();
    shellRelease.value = 1;
    return resetHeroExit;
  }, []);

  // Page scroll drives the rise. Tracked here rather than in the overlay so
  // the listener's lifetime matches the scene that consumes it.
  useEffect(() => {
    const stop = trackHeroScroll();
    return () => {
      stop();
      resetHeroScroll();
    };
  }, []);

  useFrame((_, delta) => {
    stepGlobeDrag();
    stepHeroExit(delta);
    stepHeroEntry(delta);

    const g = groupRef.current;
    if (!g) return;

    const fly = useFlyToStore.getState();

    // ── Shell: where the planet sits in frame ─────────────────────────────
    // Scrolling lifts it out of the bottom edge. A flight or a departure
    // takes the framing back to identity first, so those animations run in
    // the world space they were planned in.
    const shell = shellRef.current;
    if (shell) {
      const owned = fly.phase !== "idle" || heroExit.active;
      shellRelease.value +=
        ((owned ? 0 : 1) - shellRelease.value) * Math.min(1, delta * 5.5);

      const rise = riseEase(stepHeroScroll(delta));
      const k = shellRelease.value;
      shell.position.y = (REST_Y + (RISEN_Y - REST_Y) * rise) * k;
      shell.scale.setScalar(
        1 + (REST_SCALE + (RISEN_SCALE - REST_SCALE) * rise - 1) * k,
      );
    }

    // ── Fly-to-place: owns the group transform while live ──────────────────
    if (fly.phase !== "idle") {
      if (!flyAnim.active) beginFlyAnim();

      // Plan the flight on its first frame, when the group and camera are
      // live and the Earth's idle spin can be frozen at a known angle.
      if (!flyAnim.plan && fly.target) {
        flyAnim.plan = planFlight({
          lat: fly.target.lat,
          lon: fly.target.lon,
          earthY: earthMeshRef.current?.rotation.y ?? 0,
          currentQuat: g.quaternion.clone(),
          currentPos: g.position.clone(),
          currentScale: g.scale.x,
          cameraPos: camera.position.clone(),
          lookTarget: controls?.target?.clone() ?? DEFAULT_LOOK.clone(),
        });
      }

      const t = stepFlyAnim(delta);
      const plan = flyAnim.plan;
      if (plan) {
        // Rotation in two beats so the planet is never seen tumbling at an
        // angle: first right it to upright, then turn it to the place.
        if (t < UPRIGHT_FRACTION) {
          const e = flyEase(t / UPRIGHT_FRACTION);
          g.quaternion.slerpQuaternions(plan.startQuat, plan.uprightQuat, e);
        } else {
          const e = flyEase((t - UPRIGHT_FRACTION) / (1 - UPRIGHT_FRACTION));
          g.quaternion.slerpQuaternions(plan.uprightQuat, plan.targetQuat, e);
        }
        // Position and scale ease across the whole flight.
        const ez = flyEase(t);
        g.position.lerpVectors(plan.startPos, plan.endPos, ez);
        g.scale.setScalar(
          plan.startScale + (plan.endScale - plan.startScale) * ez,
        );
      }

      // Raise the veil near the end, then hand off once fully arrived. Both
      // are no-ops after the first call (guarded in the store).
      if (t >= DIVE_AT) fly.dive();
      if (t >= 1) fly.arrive();
      return;
    }

    // ── Idle / drag / hero travel ──────────────────────────────────────────
    if (flyAnim.active) resetFlyAnim();

    g.rotation.y = globeDrag.spin;
    // Ease the tilt so a flick doesn't snap the axis over.
    g.rotation.x += (globeDrag.tilt - g.rotation.x) * Math.min(1, delta * 6);

    // Departure wins if both are somehow live — leaving is the newer intent.
    if (heroExit.active) {
      const p = heroExitEase();
      // Left and receding, not just left: pure sideways travel reads as a
      // slide across glass, while pulling away as it goes reads as distance
      // opening up behind you.
      const { x, z, scale } = globeTravelTransform(p);
      g.position.set(x, 0, z);
      g.scale.setScalar(scale);
      // Extra spin on the way out, so the planet carries its own momentum
      // instead of looking dragged off on a rail.
      g.rotation.y += p * delta * 1.6;
    } else if (heroEntry.active) {
      // Same path, run backwards: 1 → 0 brings it in from where the
      // departure left it, so the round trip retraces one route.
      const p = 1 - heroEntryEase();
      const { x, z, scale } = globeTravelTransform(p);
      g.position.set(x, 0, z);
      g.scale.setScalar(scale);
      g.rotation.y += p * delta * 1.2;
    } else {
      // Neither travel nor flight — make sure a prior move's offset/scale
      // doesn't linger.
      g.position.set(0, 0, 0);
      g.scale.setScalar(1);
    }
  });

  // Two nested groups, deliberately: the shell decides where the planet sits
  // in frame, the inner group decides what it is doing. Composing them keeps
  // the scroll framing out of the drag, travel and flight maths entirely.
  return (
    <group ref={shellRef}>
      <group ref={groupRef}>{children}</group>
    </group>
  );
}
