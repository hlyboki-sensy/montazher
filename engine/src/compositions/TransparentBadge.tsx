import React from 'react';
import {
  AbsoluteFill,
  Easing,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {z} from 'zod';
import {brandIds, getBrand} from '../brands';

// Renders on a TRANSPARENT background so it can be exported with a real alpha
// channel (see the ProRes 4444 command in the README) and dropped straight onto
// footage. Nothing here paints a full-frame background — that is what keeps the
// surrounding pixels transparent.
export const transparentBadgeSchema = z.object({
  brand: z.enum(brandIds),
  label: z.string(),
});

export const transparentBadgeDefaultProps: z.infer<typeof transparentBadgeSchema> = {
  brand: 'default',
  label: 'НАЖИВО',
};

export const TransparentBadge: React.FC<z.infer<typeof transparentBadgeSchema>> = ({brand, label}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const {colors, fonts} = getBrand(brand);

  // ENTER — pop the badge in with an overshooting spring.
  const enter = spring({frame, fps, config: {damping: 12, stiffness: 180, mass: 0.7}});

  // EXIT — scale down and fade out over the final 16 frames.
  const exitProgress = interpolate(frame, [durationInFrames - 16, durationInFrames], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.in(Easing.ease),
  });
  const exitScale = interpolate(exitProgress, [0, 1], [1, 0.6]);
  const opacity = interpolate(exitProgress, [0, 1], [1, 0]);

  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center'}}>
      <div
        style={{
          transform: `scale(${enter * exitScale})`,
          opacity,
          backgroundColor: colors.accent,
          color: colors.bg, // dark text on the bright accent
          fontFamily: fonts.body,
          fontSize: 64,
          fontWeight: 700,
          letterSpacing: '0.08em',
          padding: '28px 64px',
          borderRadius: 999,
          boxShadow: '0 20px 60px rgba(0,0,0,0.35)',
        }}
      >
        {label}
      </div>
    </AbsoluteFill>
  );
};
