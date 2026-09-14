import React from 'react';
import {Composition} from 'remotion';

import {WIDTH, HEIGHT, FPS, VERTICAL, DURATIONS, seconds} from './video-config';

import {TitleCard, titleCardSchema, titleCardDefaultProps} from './compositions/TitleCard';
import {
  VerticalReel,
  verticalReelSchema,
  verticalReelDefaultProps,
} from './compositions/VerticalReel';
import {LowerThird, lowerThirdSchema, lowerThirdDefaultProps} from './compositions/LowerThird';
import {KineticText, kineticTextSchema, kineticTextDefaultProps} from './compositions/KineticText';
import {
  ScriptCaption,
  scriptCaptionSchema,
  scriptCaptionDefaultProps,
} from './compositions/ScriptCaption';
import {
  CaptionedReel,
  captionedReelSchema,
  captionedReelDefaultProps,
} from './compositions/CaptionedReel';
import {
  KineticCaptions,
  kineticCaptionsSchema,
  kineticCaptionsDefaultProps,
  KineticReel,
  kineticReelSchema,
  kineticReelDefaultProps,
} from './compositions/KineticCaptions';
import {
  TransparentBadge,
  transparentBadgeSchema,
  transparentBadgeDefaultProps,
} from './compositions/TransparentBadge';

// Every graphic is registered here as a <Composition>. Each one shares the
// canvas size and fps from video-config.ts, so switching to 4K/60fps is a
// one-line change there — no need to touch this file.
// Тривалість реплік визначає довжину ролика: коли props приходять із
// bin/captions-from-audio.py, кліп сам розтягується під транскрипцію,
// а не обрізається на восьмій секунді.
const durationFromCues = (cues: {fromSec: number; durSec: number}[]): number => {
  if (!cues || cues.length === 0) return DURATIONS.kineticCaptions;
  const endSec = Math.max(...cues.map((c) => c.fromSec + c.durSec));
  return Math.max(seconds(endSec + 0.4), DURATIONS.kineticCaptions);
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="TitleCard"
        component={TitleCard}
        durationInFrames={DURATIONS.titleCard}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        schema={titleCardSchema}
        defaultProps={titleCardDefaultProps}
      />

      <Composition
        id="LowerThird"
        component={LowerThird}
        durationInFrames={DURATIONS.lowerThird}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        schema={lowerThirdSchema}
        defaultProps={lowerThirdDefaultProps}
      />

      <Composition
        id="KineticText"
        component={KineticText}
        durationInFrames={DURATIONS.kineticText}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        schema={kineticTextSchema}
        defaultProps={kineticTextDefaultProps}
      />

      <Composition
        id="TransparentBadge"
        component={TransparentBadge}
        durationInFrames={DURATIONS.transparentBadge}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        schema={transparentBadgeSchema}
        defaultProps={transparentBadgeDefaultProps}
      />

      {/* Mixed-typography subtitle (gold script + white grotesque), 9:16 for Reels. */}
      <Composition
        id="ScriptCaption"
        component={ScriptCaption}
        durationInFrames={DURATIONS.scriptCaption}
        fps={FPS}
        width={VERTICAL.width}
        height={VERTICAL.height}
        schema={scriptCaptionSchema}
        defaultProps={scriptCaptionDefaultProps}
      />

      {/* Full deliverable: source video + gold/white subtitle burned on top. */}
      <Composition
        id="CaptionedReel"
        component={CaptionedReel}
        durationInFrames={DURATIONS.scriptCaption}
        fps={FPS}
        width={VERTICAL.width}
        height={VERTICAL.height}
        schema={captionedReelSchema}
        defaultProps={captionedReelDefaultProps}
      />

      {/* Roving captions that pop around the frame, word-by-word (no video). */}
      <Composition
        id="KineticCaptions"
        component={KineticCaptions}
        durationInFrames={DURATIONS.kineticCaptions}
        calculateMetadata={({props}) => ({durationInFrames: durationFromCues(props.cues)})}
        fps={FPS}
        width={VERTICAL.width}
        height={VERTICAL.height}
        schema={kineticCaptionsSchema}
        defaultProps={kineticCaptionsDefaultProps}
      />

      {/* Same roving captions, burned over the source video. */}
      <Composition
        id="KineticReel"
        component={KineticReel}
        durationInFrames={DURATIONS.kineticCaptions}
        calculateMetadata={({props}) => ({durationInFrames: durationFromCues(props.cues)})}
        fps={FPS}
        width={VERTICAL.width}
        height={VERTICAL.height}
        schema={kineticReelSchema}
        defaultProps={kineticReelDefaultProps}
      />

      {/* Vertical 9:16 clip from a source video. The timeline length follows the
          start/end props, so trimming in Studio updates the duration live. */}
      <Composition
        id="VerticalReel"
        component={VerticalReel}
        fps={FPS}
        width={VERTICAL.width}
        height={VERTICAL.height}
        schema={verticalReelSchema}
        defaultProps={verticalReelDefaultProps}
        calculateMetadata={({props}) => ({
          durationInFrames: Math.max(
            1,
            Math.round((props.endInSeconds - props.startInSeconds) * FPS),
          ),
        })}
      />

    </>
  );
};
