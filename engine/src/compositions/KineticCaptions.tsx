import React from 'react';
import {
  AbsoluteFill,
  Easing,
  interpolate,
  OffthreadVideo,
  Sequence,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {z} from 'zod';
import {loadFont as loadScript} from '@remotion/google-fonts/ComforterBrush';
import {loadFont as loadSans} from '@remotion/google-fonts/Montserrat';
import {loadFont as loadPlain} from '@remotion/google-fonts/Inter';
import {loadFont as loadCalli} from '@remotion/google-fonts/GreatVibes';
import {loadFont as loadSerif} from '@remotion/google-fonts/PlayfairDisplay';
import {brandIds, getBrand} from '../brands';
import {InsertLayer, insertSchema} from './Inserts';

// Kinetic captions: a timeline of short "cues" that pop in different parts of the
// frame, word-by-word, then fade — like the nbystrovaa reference. Each cue owns
// its time, position (x/y) and alignment; positions are authored inside the
// Instagram safe area (3:4 profile crop, clear of the right icon column).

const {fontFamily: SCRIPT} = loadScript('normal', {weights: ['400'], subsets: ['cyrillic', 'latin']});
const {fontFamily: SANS} = loadSans('normal', {
  weights: ['800'],
  subsets: ['cyrillic', 'cyrillic-ext', 'latin'],
});
const {fontFamily: PLAIN} = loadPlain('normal', {
  weights: ['700'],
  subsets: ['cyrillic', 'cyrillic-ext', 'latin'],
});
// Класична каліграфія з високим контрастом - тонкі волосяні зʼєднання й петлі.
// Інший характер, ніж щіточний Comforter Brush.
const {fontFamily: CALLI} = loadCalli('normal', {weights: ['400'], subsets: ['cyrillic', 'latin']});
// Дідонівський серіф — той самий клас, що й Didot у заголовках панелі:
// високий контраст, тонкі засічки. Курсив і капс беремо з однієї родини.
const {fontFamily: SERIF_IT} = loadSerif('italic', {weights: ['500'], subsets: ['cyrillic', 'latin']});
const {fontFamily: SERIF} = loadSerif('normal', {weights: ['800'], subsets: ['cyrillic', 'latin']});

// Базовий акцент пакета — глибокий сливовий. Він живе у двох станах:
// темний (ACCENT) для світлих кадрів і освітлений (ACCENT_SOFT) для темних,
// бо той самий колір не може читатися і на снігу, і на нічному кадрі.
// Свій колір задається одним ключем --accent-color: світлу пару до нього
// система порахує сама (див. lightenForDark нижче).
const ACCENT = '#660033';
const ACCENT_SOFT = '#E02985';
const ACCENT_GRADIENT = 'linear-gradient(178deg,#8C1B57 0%,#660033 45%,#4A0025 100%)';
const WHITE = '#FBF8F0';
// Колір тексту на світлому кадрі: майже чорний із теплим відтінком,
// щоб білий капс не розчинявся в небі чи білій стіні.
const INK = '#16121A';

/** #RRGGBB → [h, s, l] у частках. */
const hexToHsl = (hex: string): [number, number, number] | null => {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  const r = ((n >> 16) & 255) / 255;
  const g = ((n >> 8) & 255) / 255;
  const b = (n & 255) / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  if (max === min) return [0, 0, l];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  const h =
    max === r ? ((g - b) / d + (g < b ? 6 : 0)) / 6 : max === g ? ((b - r) / d + 2) / 6 : ((r - g) / d + 4) / 6;
  return [h, s, l];
};

const hslToHex = (h: number, s: number, l: number): string => {
  const f = (n: number) => {
    const k = (n + h * 12) % 12;
    const a = s * Math.min(l, 1 - l);
    const v = l - a * Math.max(-1, Math.min(k - 3, Math.min(9 - k, 1)));
    return Math.round(v * 255)
      .toString(16)
      .padStart(2, '0');
  };
  return `#${f(0)}${f(8)}${f(4)}`;
};

/**
 * Освітлена пара до акцентного кольору — для темних кадрів.
 * Тон лишається той самий, піднімаються світлість і трохи гаситься
 * насиченість: так колір читається на темному, але впізнається як той самий.
 * Світлий колір (як жовтий) не чіпаємо — він і так видно.
 */
const lightenForDark = (hex: string): string => {
  const hsl = hexToHsl(hex);
  if (!hsl) return hex;
  const [h, s, l] = hsl;
  if (l >= 0.5) return hex;
  return hslToHex(h, Math.min(s, 0.78), 0.52);
};

/** Чи цей колір світлий — щоб зрозуміти, чи треба його темнити на світлому кадрі. */
const isLight = (hex: string): boolean => {
  const hsl = hexToHsl(hex);
  return hsl ? hsl[2] > 0.6 : false;
};

// Три «характери» субтитрів. Форма й таймінги спільні — різниться лише
// типографіка: чим кожна роль слова (script / bold / accent) себе показує.
// Чим відділяти літери від кадру. halo — щільний темний ореол плюс тінь (те, що
// рятує білий текст на світлому кадрі); shadow — сама лише мʼяка тінь; none —
// нічого, чистий текст. Останнє чесно працює тільки на спокійному темному тлі.
export const EDGES = ['halo', 'shadow', 'none'] as const;
export type Edge = (typeof EDGES)[number];

const EDGE_FILTER: Record<Edge, string | undefined> = {
  halo:
    'drop-shadow(0 0 1px rgba(0,0,0,0.95)) drop-shadow(0 0 2px rgba(0,0,0,0.95)) ' +
    'drop-shadow(0 0 4px rgba(0,0,0,0.9)) drop-shadow(0 0 14px rgba(0,0,0,0.7)) ' +
    'drop-shadow(0 8px 22px rgba(0,0,0,0.5))',
  shadow: 'drop-shadow(0 6px 18px rgba(0,0,0,0.55))',
  none: undefined,
};

export const LOOKS = ['editorial', 'quiet', 'bold', 'calligraphy', 'podcast', 'classic'] as const;
export type Look = (typeof LOOKS)[number];

type Face = {
  font: string;
  weight: number;
  size: number;
  upper: boolean;
  tracking: string;
  color: string;
  gradient?: string;
  // tinted — роль, яка в стилі має колір, а не білий. Саме такі ролі
  // перефарбовує обраний колір, щоб у кадрі не жили два різні жовті.
  tinted?: boolean;
  // italic — для родин, де курсив це окреме накреслення, а не сам шрифт
  // (Playfair). У Comforter чи Great Vibes нахил уже вбудований.
  italic?: boolean;
};

// enterDelay - на скільки кадрів кожне наступне слово відстає від попереднього;
// enterShift - з якої висоти воно приїжджає; enterDamping - мʼякість пружини.
type LookPreset = {
  script: Face;
  bold: Face;
  accent: Face;
  gap: string;
  rowShift: number;
  enterDelay: number;
  enterShift: number;
  enterDamping: number;
  hardCut: boolean;
  hero?: Omit<LookPreset, 'hero'>;
};

const LOOK_PRESETS: Record<
  Look,
  {
    script: Face;
    bold: Face;
    accent: Face;
    gap: string;
    rowShift: number;
    enterDelay: number;
    enterShift: number;
    enterDamping: number;
    // hardCut - слово зʼявляється й зникає майже вмить, без мʼякої пружини.
    // Це єдиний спосіб лишити його читабельним, коли воно живе чверть секунди.
    hardCut: boolean;
    // Другий поверх: як виглядає репліка, позначена ключовою (cue.hero).
    hero?: Omit<LookPreset, 'hero'>;
  }
> = {
  // Наш редакторський: золотий рукопис + важкий капс + жовтий акцент.
  editorial: {
    script: {font: SCRIPT, weight: 400, size: 104, upper: false, tracking: 'normal', color: 'transparent', gradient: ACCENT_GRADIENT, tinted: true},
    bold: {font: SANS, weight: 800, size: 62, upper: true, tracking: '0.01em', color: WHITE},
    accent: {font: SANS, weight: 800, size: 62, upper: true, tracking: '0.01em', color: ACCENT_SOFT, tinted: true},
    gap: '0 22px',
    rowShift: -14,
    enterDelay: 4,
    enterShift: 40,
    enterDamping: 200,
    hardCut: false,
  },
  // Тихий: усе біле, малими літерами, нічого не кричить. Одне слово в кадрі.
  quiet: {
    script: {font: PLAIN, weight: 700, size: 56, upper: false, tracking: '-0.01em', color: '#FFFFFF'},
    bold: {font: PLAIN, weight: 700, size: 56, upper: false, tracking: '-0.01em', color: '#FFFFFF'},
    accent: {font: PLAIN, weight: 700, size: 56, upper: false, tracking: '-0.01em', color: '#FFFFFF'},
    gap: '0 14px',
    rowShift: 4,
    // Слово в цьому стилі живе недовго, тож зʼявляється майже миттєво й майже
    // без руху — інакше воно гасне, так і не проявившись до кінця.
    enterDelay: 0,
    enterShift: 0,
    enterDamping: 30,
    hardCut: true,
  },
  // Класичний: дідонівський серіф — курсив на службових словах, капс на решті.
  // Той самий характер, що й у заголовках панелі, тільки в кадрі.
  classic: {
    script: {font: SERIF_IT, weight: 500, size: 104, upper: false, tracking: '0.01em', color: ACCENT_SOFT, tinted: true, italic: true},
    bold: {font: SERIF, weight: 800, size: 68, upper: true, tracking: '0.04em', color: '#FFFFFF'},
    accent: {font: SERIF, weight: 800, size: 68, upper: true, tracking: '0.04em', color: ACCENT_SOFT, tinted: true},
    gap: '0 20px',
    rowShift: 2,
    enterDelay: 4,
    enterShift: 34,
    enterDamping: 200,
    hardCut: false,
  },
  // Каліграфія: великий масляно-жовтий рукопис Great Vibes на службових словах,
  // важкий білий капс на решті. Найбільш «журнальний» із усіх.
  calligraphy: {
    script: {font: CALLI, weight: 400, size: 132, upper: false, tracking: '0.01em', color: ACCENT_SOFT, tinted: true},
    bold: {font: SANS, weight: 800, size: 72, upper: true, tracking: '0.01em', color: '#FFFFFF'},
    accent: {font: CALLI, weight: 400, size: 132, upper: false, tracking: '0.01em', color: ACCENT_SOFT, tinted: true},
    gap: '0 24px',
    rowShift: -18,
    enterDelay: 4,
    enterShift: 40,
    enterDamping: 200,
    hardCut: false,
  },
  // Подкастовий: дрібне біле малими для потоку мови, а ключові фрази - великі,
  // капсом і каліграфією. Саме так зроблений референс.
  podcast: {
    script: {font: PLAIN, weight: 700, size: 56, upper: false, tracking: '-0.01em', color: '#FFFFFF'},
    bold: {font: PLAIN, weight: 700, size: 56, upper: false, tracking: '-0.01em', color: '#FFFFFF'},
    accent: {font: PLAIN, weight: 700, size: 56, upper: false, tracking: '-0.01em', color: '#FFFFFF'},
    gap: '0 14px',
    rowShift: 4,
    enterDelay: 0,
    enterShift: 0,
    enterDamping: 30,
    hardCut: true,
    // Те саме, але для реплік, позначених як ключові (cue.hero).
    hero: {
      script: {font: CALLI, weight: 400, size: 176, upper: false, tracking: '0.01em', color: ACCENT_SOFT, tinted: true},
      bold: {font: SANS, weight: 800, size: 128, upper: true, tracking: '0.01em', color: '#FFFFFF'},
      accent: {font: CALLI, weight: 400, size: 176, upper: false, tracking: '0.01em', color: ACCENT_SOFT, tinted: true},
      gap: '0 26px',
      rowShift: -26,
      enterDelay: 3,
      enterShift: 34,
      enterDamping: 200,
      hardCut: false,
    },
  },
  // Капс-блок: усе білим капсом, ключове слово - брендовим жовтим.
  bold: {
    script: {font: SANS, weight: 800, size: 64, upper: true, tracking: '0.01em', color: WHITE},
    bold: {font: SANS, weight: 800, size: 64, upper: true, tracking: '0.01em', color: WHITE},
    accent: {font: SANS, weight: 800, size: 64, upper: true, tracking: '0.01em', color: ACCENT_SOFT, tinted: true},
    gap: '0 18px',
    rowShift: -6,
    enterDelay: 3,
    enterShift: 30,
    enterDamping: 200,
    hardCut: false,
  },
};

// Safe area as fractions of the 9:16 frame (same basis as ScriptCaption).
const CROP_3_4 = {w: 1015 / 1080, h: 1350 / 1920};
const RIGHT_UI_W = 180 / 1080;
const RIGHT_UI_TOP = 0.55;

const wordSchema = z.object({text: z.string(), style: z.enum(['script', 'bold', 'accent'])});
const lineSchema = z.object({words: z.array(wordSchema)});

const cueSchema = z.object({
  lines: z.array(lineSchema), // one or two rows per cue
  fromSec: z.number().min(0), // when the cue appears
  durSec: z.number().min(0.3), // how long it stays
  x: z.number().min(0).max(1), // anchor point, fraction of width
  y: z.number().min(0).max(1), // anchor point, fraction of height
  align: z.enum(['left', 'center', 'right']),
  // Ключова репліка: у стилях із двома поверхами вона виходить великою.
  hero: z.boolean().optional(),
  // Чи темний кадр під цією реплікою. Рахується під час розкладки: скрипт
  // вимірює яскравість саме тієї смуги, де стоятиме текст. Від цього залежить,
  // якою парою кольорів писати — світлою по темному чи темною по світлому.
  // Немає значення — вважаємо кадр темним (найчастіший випадок у відео).
  dark: z.boolean().optional(),
  // Наскільки стиснути текст, щоб він вліз у відведену зону і не наліз на
  // обличчя. Рахується під час розкладки; 1 — повний розмір.
  scale: z.number().min(0.3).max(1).optional(),
  // Прямокутник, у якому репліці дозволено жити (частки кадру). Коли він є,
  // текст верстається всередині нього й переносить рядки, тож не вилазить за
  // поле і не сідає на обличчя. Коли його немає — працює старий якір x/y.
  box: z
    .object({
      x: z.number().min(0).max(1),
      y: z.number().min(0).max(1),
      w: z.number().min(0.05).max(1),
      h: z.number().min(0.03).max(1),
    })
    .optional(),
});

export const kineticCaptionsSchema = z.object({
  brand: z.enum(brandIds),
  cues: z.array(cueSchema),
  // Характер субтитрів: editorial - золото+капс, quiet - тихе біле малими,
  // bold - білий капс із жовтим ключовим словом.
  look: z.enum(LOOKS).default('editorial'),
  // Чим підсвічувати ключове слово. Порожньо - як задано в стилі.
  accentColor: z.string().optional(),
  // Обводка й тінь під літерами.
  edge: z.enum(EDGES).default('halo'),
  overlay: z.boolean(), // transparent bg to sit over video
  showSafeGuides: z.boolean(),
});

// A demo timeline that reproduces the reference's roving captions.
const DEMO_CUES: z.infer<typeof cueSchema>[] = [
  {
    lines: [{words: [{text: 'сьогодні', style: 'accent'}]}, {words: [{text: 'розповісти', style: 'bold'}]}],
    fromSec: 0.0,
    durSec: 2.2,
    x: 0.07,
    y: 0.27,
    align: 'left',
  },
  {
    lines: [{words: [{text: 'за 1 хвилину', style: 'script'}]}],
    fromSec: 1.6,
    durSec: 2.0,
    x: 0.93,
    y: 0.33,
    align: 'right',
  },
  {
    lines: [{words: [{text: 'МАКСИМАЛЬНО', style: 'bold'}]}, {words: [{text: 'тригерна', style: 'accent'}]}],
    fromSec: 3.3,
    durSec: 2.0,
    x: 0.5,
    y: 0.42,
    align: 'center',
  },
  // Wide bold phrase → kept centered and above the icon column (never lower-right).
  {
    lines: [
      {words: [{text: 'Проста', style: 'script'}]},
      {words: [{text: 'формула', style: 'bold'}, {text: 'ведення', style: 'bold'}]},
      {words: [{text: 'сторіс', style: 'script'}]},
    ],
    fromSec: 5.5,
    durSec: 2.3,
    x: 0.5,
    y: 0.5,
    align: 'center',
  },
];

export const kineticCaptionsDefaultProps: z.infer<typeof kineticCaptionsSchema> = {
  brand: 'default',
  cues: DEMO_CUES,
  look: 'editorial',
  edge: 'halo',
  overlay: false,
  showSafeGuides: false,
};

// One cue: positioned block whose words spring in (staggered) and fade out
// together over the cue's final frames. useCurrentFrame is local to the Sequence.
const Cue: React.FC<{cue: z.infer<typeof cueSchema>; look: Look; accentColor?: string; edge: Edge}> = ({cue, look, accentColor, edge}) => {
  const base = LOOK_PRESETS[look] ?? LOOK_PRESETS.editorial;
  const preset = cue.hero && base.hero ? base.hero : base;
  // Немає заміру — вважаємо кадр темним: так поводиться більшість відео,
  // і світлий текст на темному — безпечніший дефолт, ніж навпаки.
  const darkFrame = cue.dark !== false;
  const k = cue.scale ?? 1;
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const durFrames = Math.round(cue.durSec * fps);

  const fade = preset.hardCut ? 1 : Math.max(4, Math.min(12, Math.round(durFrames * 0.3)));
  const exit = interpolate(frame, [durFrames - fade, durFrames], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: preset.hardCut ? Easing.linear : Easing.in(Easing.ease),
  });

  const translate =
    cue.align === 'center'
      ? 'translate(-50%, -50%)'
      : cue.align === 'right'
        ? 'translate(-100%, -50%)'
        : 'translate(0, -50%)';

  let wordIndex = -1;

  const items =
    cue.align === 'left' ? 'flex-start' : cue.align === 'right' ? 'flex-end' : 'center';

  // Коли задано box — репліка живе всередині прямокутника й переносить рядки.
  // Інакше лишається старий якір: точка x/y плюс зсув через transform.
  const frameStyle: React.CSSProperties = cue.box
    ? {
        position: 'absolute',
        left: `${cue.box.x * 100}%`,
        top: `${cue.box.y * 100}%`,
        width: `${cue.box.w * 100}%`,
        height: `${cue.box.h * 100}%`,
        justifyContent: 'center',
      }
    : {
        position: 'absolute',
        left: `${cue.x * 100}%`,
        top: `${cue.y * 100}%`,
        transform: translate,
        maxWidth: `${Math.round(CROP_3_4.w * 100) - 8}%`,
      };

  return (
    <div
      style={{
        ...frameStyle,
        display: 'flex',
        flexDirection: 'column',
        alignItems: items,
        opacity: exit,
      }}
    >
      {cue.lines.map((line, li) => (
        // eslint-disable-next-line react/no-array-index-key
        <div
          key={li}
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            justifyContent: items,
            alignItems: 'baseline',
            gap: preset.gap.replace(/(\d+)px/, (_, n) => `${Math.round(Number(n) * k)}px`),
            marginTop: li === 0 ? 0 : Math.round(preset.rowShift * k),
            maxWidth: '100%',
          }}
        >
          {line.words.map((word, wi) => {
            wordIndex += 1;
            const enter = preset.hardCut
              ? interpolate(frame, [0, 2], [0, 1], {
                  extrapolateLeft: 'clamp',
                  extrapolateRight: 'clamp',
                })
              : spring({
                  frame,
                  fps,
                  delay: wordIndex * preset.enterDelay,
                  config: {damping: preset.enterDamping},
                });
            const y = interpolate(enter, [0, 1], [preset.enterShift * k, 0]);
            const isScript = word.style === 'script';
            const isAccent = word.style === 'accent';
            const preseted = preset[word.style] ?? preset.bold;
            // Обраний колір лягає на ВСІ кольорові ролі стилю - і на акцент, і
            // на рукопис. Інакше в кадрі співіснували б два різні відтінки: один
            // із градієнта, другий із акценту.
            //
            // Далі — головне правило читабельності: той самий колір не може
            // працювати і на світлому кадрі, і на темному. Тому на темному
            // акцент світлішає, а на світлому — білий текст темніє.
            const tint = accentColor
              ? darkFrame
                ? lightenForDark(accentColor)
                : accentColor
              : undefined;
            let face: Face =
              preseted.tinted && tint ? {...preseted, color: tint, gradient: undefined} : preseted;
            if (!darkFrame) {
              if (face.gradient) {
                // Градієнт розрахований на темне тло — на світлому беремо
                // суцільний темний акцент.
                face = {...face, gradient: undefined, color: accentColor ?? ACCENT};
              } else if (face.tinted && !accentColor) {
                face = {...face, color: ACCENT};
              } else if (!face.tinted && isLight(face.color)) {
                face = {...face, color: INK};
              }
            }
            // Пульс лише там, де акцент справді виділяється кольором.
            const pulse =
              isAccent && face.color !== preset.bold.color
                ? interpolate(enter, [0.5, 0.8, 1], [1, 1.06, 1], {extrapolateLeft: 'clamp'})
                : 1;

            const base: React.CSSProperties = {
              display: 'inline-block',
              opacity: enter,
              transform: `translateY(${y}px) scale(${pulse})`,
              fontFamily: face.font,
              fontStyle: face.italic ? 'italic' : 'normal',
              fontWeight: face.weight,
              fontSize: Math.round(face.size * k),
              lineHeight: 1,
              textTransform: face.upper ? 'uppercase' : 'none',
              letterSpacing: face.tracking,
              filter: EDGE_FILTER[edge],
              paddingBottom: isScript && face.gradient ? '0.12em' : 0,
            };

            if (face.gradient) {
              return (
                <span
                  // eslint-disable-next-line react/no-array-index-key
                  key={wi}
                  style={{...base, backgroundImage: face.gradient, WebkitBackgroundClip: 'text', backgroundClip: 'text', color: 'transparent'}}
                >
                  {word.text}
                </span>
              );
            }
            return (
              <span
                // eslint-disable-next-line react/no-array-index-key
                key={wi}
                style={{...base, color: face.color}}
              >
                {word.text}
              </span>
            );
          })}
        </div>
      ))}
    </div>
  );
};

const SafeGuides: React.FC = () => (
  <>
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
);

export const KineticCaptions: React.FC<z.infer<typeof kineticCaptionsSchema>> = ({
  brand,
  cues,
  look,
  accentColor,
  edge,
  overlay,
  showSafeGuides,
}) => {
  const {fps} = useVideoConfig();
  const {colors} = getBrand(brand);

  return (
    <AbsoluteFill style={{backgroundColor: overlay ? 'transparent' : colors.bg}}>
      {showSafeGuides && <SafeGuides />}
      {cues.map((cue, i) => (
        <Sequence
          // eslint-disable-next-line react/no-array-index-key
          key={i}
          from={Math.round(cue.fromSec * fps)}
          durationInFrames={Math.round(cue.durSec * fps)}
          layout="none"
        >
          <Cue cue={cue} look={look ?? 'editorial'} accentColor={accentColor} edge={edge ?? 'halo'} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};

// Full deliverable: source video + kinetic captions on top.
export const kineticReelSchema = z.object({
  brand: z.enum(brandIds),
  videoSrc: z.string(),
  startInSeconds: z.number().min(0),
  muted: z.boolean(),
  cues: z.array(cueSchema),
  look: z.enum(LOOKS).default('editorial'),
  accentColor: z.string().optional(),
  edge: z.enum(EDGES).default('halo'),
  // Вставки поверх кадру: цифри, підписи, картинки. Порожній масив — їх немає.
  inserts: z.array(insertSchema).default([]),
  showSafeGuides: z.boolean(),
});

export const kineticReelDefaultProps: z.infer<typeof kineticReelSchema> = {
  brand: 'default',
  videoSrc: 'IMG_3382.MOV',
  startInSeconds: 0,
  muted: false,
  cues: DEMO_CUES,
  look: 'editorial',
  edge: 'halo',
  inserts: [],
  showSafeGuides: false,
};

export const KineticReel: React.FC<z.infer<typeof kineticReelSchema>> = ({
  brand,
  videoSrc,
  startInSeconds,
  muted,
  cues,
  look,
  accentColor,
  edge,
  inserts,
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
      <InsertLayer inserts={inserts ?? []} brand={brand} />
      <KineticCaptions
        brand={brand}
        cues={cues}
        look={look}
        accentColor={accentColor}
        edge={edge}
        overlay
        showSafeGuides={showSafeGuides}
      />
    </AbsoluteFill>
  );
};
