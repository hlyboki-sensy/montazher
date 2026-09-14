import React from 'react';
import {AbsoluteFill, OffthreadVideo, staticFile, useVideoConfig} from 'remotion';
import {z} from 'zod';
import {brandIds} from '../brands';
import {ScriptCaption, scriptCaptionSchema} from './ScriptCaption';

// The full deliverable: a source video from public/ with the gold script + white
// grotesque subtitle burned on top. Reuses ScriptCaption in overlay mode, so the
// caption styling and safe-area logic stay in one place.
export const captionedReelSchema = z.object({
  brand: z.enum(brandIds),
  videoSrc: z.string(), // file in public/
  startInSeconds: z.number().min(0), // trim the source from here
  muted: z.boolean(),
  // Subtitle content + placement, borrowed from ScriptCaption's schema.
  lines: scriptCaptionSchema.shape.lines,
  verticalAnchor: scriptCaptionSchema.shape.verticalAnchor,
  showSafeGuides: scriptCaptionSchema.shape.showSafeGuides,
});

export const captionedReelDefaultProps: z.infer<typeof captionedReelSchema> = {
  brand: 'default',
  videoSrc: 'IMG_3382.MOV',
  startInSeconds: 0,
  muted: false,
  lines: [
    {words: [{text: 'Проста', style: 'script'}]},
    {
      words: [
        {text: 'формула', style: 'bold'},
        {text: 'ведення', style: 'bold'},
      ],
    },
    {words: [{text: 'сторіс', style: 'script'}]},
  ],
  verticalAnchor: 0.5,
  showSafeGuides: false,
};

export const CaptionedReel: React.FC<z.infer<typeof captionedReelSchema>> = ({
  brand,
  videoSrc,
  startInSeconds,
  muted,
  lines,
  verticalAnchor,
  showSafeGuides,
}) => {
  const {fps} = useVideoConfig();

  return (
    <AbsoluteFill style={{backgroundColor: '#000000'}}>
      <OffthreadVideo
        src={staticFile(videoSrc)}
        trimBefore={Math.round(startInSeconds * fps)}
        muted={muted}
        style={{width: '100%', height: '100%', objectFit: 'cover'}}
      />
      {/* Subtitle sits on top with a transparent background. */}
      <ScriptCaption
        brand={brand}
        lines={lines}
        verticalAnchor={verticalAnchor}
        showSafeGuides={showSafeGuides}
        overlay
      />
    </AbsoluteFill>
  );
};
