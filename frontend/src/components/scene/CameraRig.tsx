"use client";

import { useRef } from "react";
import { OrbitControls } from "@react-three/drei";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";

const BASE_DISTANCE = 5.45;
const BASE_HEIGHT = 0.45;

/** Where the camera looks. Shared with GlobeSystem, which needs the same
 *  point to plan a fly-to flight against. */
export const HERO_LOOK_TARGET: [number, number, number] = [0, 0.1, 0];

/**
 * The globe is user-controllable: drag to spin it on its own axis. The
 * wheel belongs to the page now, so the scene takes nothing from it.
 *
 * The target sits on the centre line: the planet is framed dead centre and
 * low, rising out of the bottom edge under the headline. How far below the
 * middle it sits is set by the shell transform in GlobeSystem, not here —
 * this only decides which way the camera faces.
 */
export default function CameraRig() {
  const controlsRef = useRef<OrbitControlsImpl | null>(null);

  return (
    // Camera rotation is off on purpose: dragging spins the planet on its
    // own axis (see useGlobeDrag in Earth.tsx) rather than swinging the
    // camera around it, so the globe stays parked in its corner of the
    // layout instead of sliding across the headline.
    //
    // Zoom is off as well now that the wheel belongs to the page: on a
    // scrolling landing page a wheel gesture has to move the document, and
    // OrbitControls would otherwise swallow it to dolly the camera.
    <OrbitControls
      ref={controlsRef}
      makeDefault
      target={HERO_LOOK_TARGET}
      enablePan={false}
      enableRotate={false}
      enableZoom={false}
      minDistance={3.4}
      maxDistance={8.5}
      zoomSpeed={0.7}
      enableDamping
      dampingFactor={0.08}
    />
  );
}

/** Initial camera pose, applied once via <Canvas camera={...}> in HeroScene. */
export const INITIAL_CAMERA_POSITION: [number, number, number] = [
  0,
  BASE_HEIGHT,
  BASE_DISTANCE,
];
