import { Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';

export const FPS = 60;
export const sec = (s: number): number => Math.round(s * FPS);
export const EXPO = Easing.bezier(0.16, 1, 0.3, 1);

/** 0 to 1 over [start, start+dur] seconds of the local sequence, expo-out. */
export function useIn(startSec = 0, durSec = 0.6): number {
  const f = useCurrentFrame();
  return interpolate(f, [sec(startSec), sec(startSec + durSec)], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: EXPO,
  });
}

export function useSpring(startSec = 0, damping = 18): number {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame: f - sec(startSec), fps, config: { damping, mass: 0.7 } });
}
