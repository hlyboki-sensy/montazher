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

export const kineticTextSchema = z.object({
  brand: z.enum(brandIds),
  text: z.string(),
});

export const kineticTextDefaultProps: z.infer<typeof kineticTextSchema> = {
  brand: 'default',
  text: 'Один акцент на кадр',
};

export const KineticText: React.FC<z.infer<typeof kineticTextSchema>> = ({brand, text}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const {colors, fonts} = getBrand(brand);

  const words = text.split(' ');

  // EXIT — one shared fade for the whole line over the final 18 frames.
  const exit = interpolate(frame, [durationInFrames - 18, durationInFrames], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.in(Easing.ease),
  });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: colors.bg,
        justifyContent: 'center',
        alignItems: 'center',
        fontFamily: fonts.display,
      }}
    >
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          justifyContent: 'center',
          gap: '0 24px',
          maxWidth: '80%',
          opacity: exit,
        }}
      >
        {words.map((word, i) => {
          // ENTER — each word springs up in sequence, staggered by 4 frames.
          const wordEnter = spring({frame, fps, delay: i * 4, config: {damping: 200}});
          const y = interpolate(wordEnter, [0, 1], [60, 0]);
          // Emphasise the last word in the brand accent colour.
          const isLast = i === words.length - 1;

          return (
            <span
              // eslint-disable-next-line react/no-array-index-key
              key={i}
              style={{
                fontSize: 96,
                fontWeight: 700,
                color: isLast ? colors.accent : colors.text,
                opacity: wordEnter,
                transform: `translateY(${y}px)`,
                display: 'inline-block',
                letterSpacing: '-0.01em',
              }}
            >
              {word}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
