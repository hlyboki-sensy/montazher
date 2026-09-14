import React from 'react';
import {
  AbsoluteFill,
  Easing,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
  staticFile,
} from 'remotion';
import {loadFont} from '@remotion/google-fonts/Inter';
import {z} from 'zod';
import { Video } from "@remotion/media";

// NICE-TO-HAVE: a Google font loaded at build time via @remotion/google-fonts.
// Loading only the weights/subset you use keeps the render fast.
// `fontFamily` is ready to drop into any style object below.
const {fontFamily} = loadFont('normal', {weights: ['400', '700'], subsets: ['latin']});

export const titleCardSchema = z.object({
  title: z.string(),
  subtitle: z.string(),
  backgroundColor: z.string(),
  textColor: z.string(),
});

export const titleCardDefaultProps: z.infer<typeof titleCardSchema> = {
  title: 'Your Title Here',
  subtitle: 'A neutral starting point',
  backgroundColor: '#0f0f12',
  textColor: '#ffffff',
};

export const TitleCard: React.FC<z.infer<typeof titleCardSchema>> = ({
  title,
  subtitle,
  backgroundColor,
  textColor,
}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();

  // ENTER — spring the title up and fade it in.
  const enter = spring({frame, fps, config: {damping: 200}});
  const titleY = interpolate(enter, [0, 1], [40, 0]);

  // Subtitle follows the title, delayed by a few frames.
  const subEnter = spring({frame, fps, delay: 8, config: {damping: 200}});
  const subY = interpolate(subEnter, [0, 1], [24, 0]);

  // EXIT — fade the whole card out over the final 18 frames so nothing cuts hard.
  const exit = interpolate(
    frame,
    [durationInFrames - 18, durationInFrames],
    [1, 0],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.in(Easing.ease)},
  );

  return (
    <AbsoluteFill style={{backgroundColor, fontFamily, justifyContent: 'center', alignItems: 'center'}}>
      <div style={{textAlign: 'center', opacity: exit}}>
        <h1
          style={{
            margin: 0,
            fontSize: 120,
            fontWeight: 700,
            color: textColor,
            opacity: enter,
            transform: `translateY(${titleY}px)`,
            letterSpacing: '-0.02em',
          }}
        >
          {title}
        </h1>
        <p
          style={{
            margin: '24px 0 0',
            fontSize: 44,
            fontWeight: 400,
            color: textColor,
            opacity: subEnter * 0.7,
            transform: `translateY(${subY}px)`,
          }}
        >
          {subtitle}
        </p>
      </div>
      <Video
        src={staticFile("IMG_3382.MOV")}
        style={{
          position: "absolute",
          translate: "-64px -19.7px",
          width: 2160,
          height: 3840,
          scale: 0.29
        }} /></AbsoluteFill>
  );
};
