/**
 * Shared video settings — the single place to change canvas defaults.
 *
 * Want 4K? Set WIDTH = 3840, HEIGHT = 2160.
 * Want 60fps? Set FPS = 60.
 * Every composition and every duration below is derived from these three values,
 * so changing them here updates the whole project consistently.
 */
export const WIDTH = 1920;
export const HEIGHT = 1080;
export const FPS = 30;

/** Vertical 9:16 canvas for Reels / TikTok / Shorts. */
export const VERTICAL = {width: 1080, height: 1920};

/** Convert seconds to a whole number of frames at the current FPS. */
export const seconds = (s: number): number => Math.round(s * FPS);

/** Default clip lengths, expressed in seconds so they stay correct at any FPS. */
export const DURATIONS = {
  titleCard: seconds(5),
  lowerThird: seconds(6),
  kineticText: seconds(5),
  transparentBadge: seconds(4),
  scriptCaption: seconds(4.5),
  kineticCaptions: seconds(8),
};
