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

export const lowerThirdSchema = z.object({
  brand: z.enum(brandIds), // pick the brand live in Studio
  name: z.string(),
  role: z.string(),
});

export const lowerThirdDefaultProps: z.infer<typeof lowerThirdSchema> = {
  brand: 'default',
  name: 'Катерина',
  role: 'Гіпнологиня',
};

export const LowerThird: React.FC<z.infer<typeof lowerThirdSchema>> = ({brand, name, role}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const {colors, fonts} = getBrand(brand);

  // ENTER — slide the bar in from the left and fade it up.
  const enter = spring({frame, fps, config: {damping: 200, mass: 0.6}});
  const x = interpolate(enter, [0, 1], [-80, 0]);
  const barScale = spring({frame, fps, delay: 4, config: {damping: 200}});

  // EXIT — slide back out and fade over the final 18 frames.
  const exit = interpolate(frame, [durationInFrames - 18, durationInFrames], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.in(Easing.ease),
  });
  const exitX = interpolate(frame, [durationInFrames - 18, durationInFrames], [0, -60], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.in(Easing.ease),
  });

  return (
    <AbsoluteFill style={{backgroundColor: colors.bg}}>
      <div
        style={{
          position: 'absolute',
          left: 140,
          bottom: 160,
          display: 'flex',
          alignItems: 'center',
          gap: 28,
          opacity: enter * exit,
          transform: `translateX(${x + exitX}px)`,
        }}
      >
        <div
          style={{
            width: 8,
            height: 92,
            backgroundColor: colors.accent,
            borderRadius: 4,
            transform: `scaleY(${barScale})`,
            transformOrigin: 'top',
          }}
        />
        <div>
          <div style={{fontFamily: fonts.display, fontSize: 58, fontWeight: 700, color: colors.text, lineHeight: 1}}>
            {name}
          </div>
          <div style={{fontFamily: fonts.body, fontSize: 34, fontWeight: 400, color: colors.accent, marginTop: 14}}>
            {role}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
