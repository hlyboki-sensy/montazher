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
import {loadFont as loadScript} from '@remotion/google-fonts/ComforterBrush';
import {loadFont as loadSans} from '@remotion/google-fonts/Montserrat';
import {brandIds, getBrand} from '../brands';

// Reference: nbystrovaa Reels — "mixed typography" subtitle where some words are
// an elegant gold calligraphy script and others are a heavy white grotesque.
// Script  = Comforter Brush (gold foil), Bold = Montserrat 800 (warm white),
// Accent  = one key word in warm yellow. Words appear one-by-one, bottom-up.

const {fontFamily: SCRIPT} = loadScript('normal', {
  weights: ['400'],
  subsets: ['cyrillic', 'latin'],
});
const {fontFamily: SANS} = loadSans('normal', {
  weights: ['800'],
  subsets: ['cyrillic', 'cyrillic-ext', 'latin'],
});

const wordSchema = z.object({
  text: z.string(),
  style: z.enum(['script', 'bold', 'accent']),
});

const lineSchema = z.object({
  words: z.array(wordSchema),
});

export const scriptCaptionSchema = z.object({
  brand: z.enum(brandIds),
  // Each line is one visual row; rows stack (and gently overlap) in the center.
  lines: z.array(lineSchema),
  // Vertical position of the caption block, 0 = top … 1 = bottom of the frame.
  // 0.6 = lower-center, above Instagram's right-side action buttons.
  verticalAnchor: z.number().min(0).max(1),
  // Draw the Instagram safe-area guides (3:4 profile crop + right UI column).
  showSafeGuides: z.boolean(),
  // When true the background is transparent, so the caption can sit over video
  // (used by CaptionedReel) or export as an alpha .mov overlay.
  overlay: z.boolean(),
});

export const scriptCaptionDefaultProps: z.infer<typeof scriptCaptionSchema> = {
  brand: 'default',
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
  overlay: false,
};

// Instagram Stories/Reels safe area, as fractions of the 9:16 frame.
// The 3:4 profile crop (1015×1350 on a 1080×1920 canvas) is what shows in the
// grid; the right column is where the like/comment/share icons sit.
const CROP_3_4 = {w: 1015 / 1080, h: 1350 / 1920}; // ≈ 0.94 × 0.70, centered
const RIGHT_UI_W = 180 / 1080; // ≈ 0.167 — the right edge holds the action buttons
const RIGHT_UI_TOP = 0.55; // icons live in the lower-right; keep text above this band
// Text stays a touch inside the 3:4 profile crop so nothing clips in the grid.
const SAFE_TEXT_WIDTH = `${Math.round(CROP_3_4.w * 100) - 6}%`;

// Warm-gold foil for script words. A vertical gradient reads as metallic.
// Той самий акцент, що і в решті пакета: сливовий у двох станах.
// Тут композиція живе поверх темного кадру, тож типово береться світла пара.
const ACCENT_GRADIENT = 'linear-gradient(178deg,#8C1B57 0%,#660033 45%,#4A0025 100%)';
const WHITE = '#FBF8F0';
const ACCENT_SOFT = '#E02985';

export const ScriptCaption: React.FC<z.infer<typeof scriptCaptionSchema>> = ({
  brand,
  lines,
  verticalAnchor,
  showSafeGuides,
  overlay,
}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const {colors} = getBrand(brand);

  // One shared fade-out for the whole caption over the final 18 frames.
  const exit = interpolate(frame, [durationInFrames - 18, durationInFrames], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.in(Easing.ease),
  });

  // Global word counter so words stagger across the whole caption, not per line.
  let wordIndex = -1;

  return (
    <AbsoluteFill style={{backgroundColor: overlay ? 'transparent' : colors.bg}}>
      {showSafeGuides && (
        <>
          {/* 3:4 profile crop — content inside this box shows in the grid. */}
          <div
            style={{
              position: 'absolute',
              left: `${((1 - CROP_3_4.w) / 2) * 100}%`,
              top: `${((1 - CROP_3_4.h) / 2) * 100}%`,
              width: `${CROP_3_4.w * 100}%`,
              height: `${CROP_3_4.h * 100}%`,
              border: '3px dashed rgba(255,255,255,0.55)',
            }}
          />
          {/* Right-side UI column (like / comment / share). Keep text out of it. */}
          <div
            style={{
              position: 'absolute',
              right: 0,
              top: `${RIGHT_UI_TOP * 100}%`,
              bottom: 0,
              width: `${RIGHT_UI_W * 100}%`,
              backgroundColor: 'rgba(255,60,60,0.14)',
            }}
          />
        </>
      )}

      {/* Caption block, anchored vertically and kept inside the safe text width. */}
      <div
        style={{
          position: 'absolute',
          top: `${verticalAnchor * 100}%`,
          left: 0,
          right: 0,
          transform: 'translateY(-50%)',
          display: 'flex',
          justifyContent: 'center',
        }}
      >
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            maxWidth: SAFE_TEXT_WIDTH,
            opacity: exit,
          }}
        >
          {lines.map((line, li) => (
          // eslint-disable-next-line react/no-array-index-key
          <div
            key={li}
            style={{
              display: 'flex',
              justifyContent: 'center',
              alignItems: 'baseline',
              gap: '0 28px',
              // Rows lean into each other slightly, like the reference layout.
              marginTop: li === 0 ? 0 : -18,
            }}
          >
            {line.words.map((word, wi) => {
              wordIndex += 1;
              const enter = spring({frame, fps, delay: wordIndex * 5, config: {damping: 200}});
              const y = interpolate(enter, [0, 1], [50, 0]);

              const isScript = word.style === 'script';
              const isAccent = word.style === 'accent';

              // Accent word gets a tiny pulse right as it lands.
              const pulse = isAccent
                ? interpolate(enter, [0.5, 0.8, 1], [1, 1.06, 1], {extrapolateLeft: 'clamp'})
                : 1;

              const base: React.CSSProperties = {
                display: 'inline-block',
                opacity: enter,
                transform: `translateY(${y}px) scale(${pulse})`,
                fontFamily: isScript ? SCRIPT : SANS,
                fontWeight: isScript ? 400 : 800,
                fontSize: isScript ? 132 : 78,
                lineHeight: 1,
                textTransform: isScript ? 'none' : 'uppercase',
                letterSpacing: isScript ? 'normal' : '0.01em',
                // Two shadows: a tight dark halo so gold reads on light areas,
                // plus a soft drop for depth on darker ones.
                filter:
                  'drop-shadow(0 0 4px rgba(0,0,0,0.75)) drop-shadow(0 4px 12px rgba(0,0,0,0.5))',
                paddingBottom: isScript ? '0.12em' : 0, // room for script descenders
              };

              if (isScript) {
                return (
                  <span
                    // eslint-disable-next-line react/no-array-index-key
                    key={wi}
                    style={{
                      ...base,
                      backgroundImage: ACCENT_GRADIENT,
                      WebkitBackgroundClip: 'text',
                      backgroundClip: 'text',
                      color: 'transparent',
                    }}
                  >
                    {word.text}
                  </span>
                );
              }

              return (
                <span
                  // eslint-disable-next-line react/no-array-index-key
                  key={wi}
                  style={{...base, color: isAccent ? ACCENT_SOFT : WHITE}}
                >
                  {word.text}
                </span>
              );
            })}
            </div>
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};
