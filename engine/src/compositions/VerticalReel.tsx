import React from 'react';
import {AbsoluteFill, OffthreadVideo, staticFile, useVideoConfig} from 'remotion';
import {z} from 'zod';

// A vertical 9:16 clip built from a source video in public/.
// Set start/end (in seconds) to trim — the timeline length follows automatically
// (see calculateMetadata in Root.tsx). The source IMG_3382.MOV is already 9:16
// (2160x3840), so it fills the frame with no cropping.
export const verticalReelSchema = z.object({
  videoSrc: z.string(), // file in public/
  startInSeconds: z.number().min(0),
  endInSeconds: z.number().min(0),
  muted: z.boolean(),
});

export const verticalReelDefaultProps: z.infer<typeof verticalReelSchema> = {
  videoSrc: 'IMG_3382.MOV',
  startInSeconds: 0,
  endInSeconds: 15,
  muted: false,
};

export const VerticalReel: React.FC<z.infer<typeof verticalReelSchema>> = ({
  videoSrc,
  startInSeconds,
  muted,
}) => {
  const {fps} = useVideoConfig();
  return (
    <AbsoluteFill style={{backgroundColor: '#000000'}}>
      <OffthreadVideo
        src={staticFile(videoSrc)}
        // Trim from this point in the source (in seconds).
        trimBefore={Math.round(startInSeconds * fps)}
        muted={muted}
        style={{
          width: '100%',
          height: '100%',
          objectFit: 'cover', // fill 9:16; source is already 9:16 so nothing is lost
        }}
      />
    </AbsoluteFill>
  );
};
