import React from 'react';
import {
  AbsoluteFill,
  Easing,
  Img,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {z} from 'zod';
import {loadFont as loadSans} from '@remotion/google-fonts/Montserrat';
import {getBrand} from '../brands';
import type {BrandId} from '../brands';
import type {Brand} from '../brands/types';

// Вставки — те, що зʼявляється поверх кадру: велика цифра, короткий підпис або
// картинка. Кожна вставка знає свій прямокутник (частки кадру), тож не сідає на
// обличчя і не вилазить за поле — так само, як репліки субтитрів.

const {fontFamily: SANS} = loadSans('normal', {
  weights: ['600', '800'],
  subsets: ['latin', 'cyrillic', 'cyrillic-ext'],
});

export const insertSchema = z.object({
  fromSec: z.number().min(0),
  durSec: z.number().min(0.3),
  kind: z.enum(['number', 'label', 'image']),
  text: z.string().optional(),
  caption: z.string().optional(),
  src: z.string().optional(),
  credit: z.string().optional(),
  box: z.object({
    x: z.number().min(0).max(1),
    y: z.number().min(0).max(1),
    w: z.number().min(0.03).max(1),
    h: z.number().min(0.02).max(1),
  }),
});

export type InsertProps = z.infer<typeof insertSchema>;

const SHADOW = 'drop-shadow(0 0 6px rgba(0,0,0,.7)) drop-shadow(0 6px 18px rgba(0,0,0,.45))';

const One: React.FC<{ins: InsertProps; brand: Brand}> = ({ins, brand}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const durFrames = Math.round(ins.durSec * fps);

  const enter = spring({frame, fps, config: {damping: 200}});
  const fadeOut = interpolate(frame, [durFrames - 10, durFrames], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.in(Easing.ease),
  });
  const scale = interpolate(enter, [0, 1], [0.88, 1]);
  const lift = interpolate(enter, [0, 1], [26, 0]);

  const frameStyle: React.CSSProperties = {
    position: 'absolute',
    left: `${ins.box.x * 100}%`,
    top: `${ins.box.y * 100}%`,
    width: `${ins.box.w * 100}%`,
    height: `${ins.box.h * 100}%`,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    opacity: Math.min(enter, fadeOut),
    transform: `translateY(${lift}px) scale(${scale})`,
  };

  if (ins.kind === 'image') {
    return (
      <div style={frameStyle}>
        <Img
          src={staticFile(ins.src as string)}
          style={{maxWidth: '100%', maxHeight: '100%', objectFit: 'contain', filter: SHADOW}}
        />
        {ins.credit ? (
          <span
            style={{
              fontFamily: SANS,
              fontWeight: 600,
              fontSize: 17,
              letterSpacing: '.06em',
              color: 'rgba(245,245,245,.62)',
              marginTop: 12,
              textShadow: '0 2px 8px rgba(0,0,0,.8)',
            }}
          >
            {ins.credit}
          </span>
        ) : null}
      </div>
    );
  }

  if (ins.kind === 'label') {
    return (
      <div style={frameStyle}>
        <span
          style={{
            fontFamily: SANS,
            fontWeight: 800,
            fontSize: 46,
            letterSpacing: '.14em',
            textTransform: 'uppercase',
            color: brand.colors.accent,
            filter: SHADOW,
            textAlign: 'center',
          }}
        >
          {ins.text}
        </span>
        <span
          style={{
            width: interpolate(enter, [0, 1], [0, 150]),
            height: 3,
            background: brand.colors.accent,
            marginTop: 16,
            filter: SHADOW,
          }}
        />
      </div>
    );
  }

  // number — велика цифра дисплейним шрифтом бренду
  return (
    <div style={frameStyle}>
      <span
        style={{
          fontFamily: brand.fonts.display,
          fontWeight: 700,
          fontSize: 210,
          lineHeight: 0.9,
          color: brand.colors.accent,
          filter: SHADOW,
        }}
      >
        {ins.text}
      </span>
      {ins.caption ? (
        <span
          style={{
            fontFamily: SANS,
            fontWeight: 800,
            fontSize: 40,
            letterSpacing: '.16em',
            textTransform: 'uppercase',
            color: brand.colors.text,
            marginTop: 14,
            filter: SHADOW,
          }}
        >
          {ins.caption}
        </span>
      ) : null}
    </div>
  );
};

export const InsertLayer: React.FC<{inserts: InsertProps[]; brand: BrandId}> = ({
  inserts,
  brand,
}) => {
  const {fps} = useVideoConfig();
  const b = getBrand(brand);
  return (
    <AbsoluteFill>
      {inserts.map((ins, i) => (
        <Sequence
          // eslint-disable-next-line react/no-array-index-key
          key={i}
          from={Math.round(ins.fromSec * fps)}
          durationInFrames={Math.round(ins.durSec * fps)}
          layout="none"
        >
          <One ins={ins} brand={b} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
