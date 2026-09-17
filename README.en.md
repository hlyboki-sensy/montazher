# Montazher by Hlyboki Sensy

Shoot on your phone, get back a finished clip with captions that never land on
your face. Claude Code does the editing locally on your machine — nothing is
uploaded anywhere, no API keys, no subscriptions.

*[Українською](README.md)*

---

## What it does

**Captions that respect the frame.** The script finds the face in every cue and
lays the text out so it never covers it. It also avoids the platform's blind
spots — the icon column in Reels, the caption and music strip at the bottom,
the Stories timeline at the top.

**Six caption characters.** Same motion and timing, different typography:

| Look | Style | Use it for |
|---|---|---|
| `editorial` | brush script + heavy caps + coloured accent | the default choice |
| `podcast` | small white text, with a key phrase going large every few seconds | interviews, anything over a minute |
| `calligraphy` | the whole cue large: classic calligraphy + white caps | slow speech where text is part of the image |
| `classic` | Didone serif: italic on function words, caps on the rest | restrained and printed |
| `quiet` | one word on screen, white, lowercase | when attention must stay on the face |
| `bold` | all white caps, key word in colour | when it just has to be read fast |

**Colour that saves itself.** You pick one accent colour. The script measures
frame brightness exactly where the text will sit, then uses a lightened pair of
that colour on dark frames and the dark one on bright frames. No single colour
can stay readable on both snow and a night shot.

**Recording cleanup.** Trim head and tail, cut long pauses and filler words,
speed up without chipmunking the voice, normalise loudness, gentle colour
correction.

**A panel instead of commands.** A desktop icon opens a form: add the video,
pick a look, tick the boxes — then tell Claude the brief is ready.

## Requirements

- A Mac (face detection uses Vision, built into macOS)
- [Claude Code](https://claude.com/claude-code)
- Python 3.10+ and Node.js 18+ — the installer tells you where to get them

## Install

```bash
git clone https://github.com/hlyboki-sensy/montazher.git
cd montazher
./install.sh
```

The first run downloads the render engine and the speech model — a few minutes.
After that everything is instant and local.

## How to edit

1. Drop a video into `inbox/` — or hit "Add video" inside the panel.
2. Open **«Завдання до відео»** on your desktop, fill the form, save.
3. Open this folder in Claude Code and say the brief is ready.

Claude reads the brief, transcribes the speech, lays out the captions, cleans
the audio and drops the finished file into `out/`. A plain-text file with every
caption and its timecode lands next to it — transcription gets names wrong, and
reading the lines is the fastest way to proofread. Fix a word there, tell Claude,
and he rebuilds the clip. At the end he opens the folder for you.

Prefer no panel? The same thing in one command:

```bash
python3 engine/bin/captions-from-audio.py inbox/reel.mp4 \
  --mode reel --video-src reel.mp4 --look editorial --dest reels --accent-color '#660033'

cd engine && npx remotion render KineticReel ../out/reel.mp4 \
  --props=src/data/reel.captions.json --codec=h264 --crf=18
```

**Note on language:** the panel and the briefs are in Ukrainian, and speech
recognition defaults to Ukrainian. For another language pass `--language en`
(or any ISO code) — the layout, face avoidance and colour logic work the same.

## Make it yours

The package ships with a neutral brand: dark ground, light text, a plum accent
`#660033`. To build your own, copy `engine/src/brands/default.ts`, change the
colours and fonts, register it in `engine/src/brands/index.ts`. It shows up in
every composition's brand dropdown right away.

The caption colour is separate — `--accent-color`, or the swatch in the panel.
The light counterpart for dark frames is computed for you.

## What it can't do yet

Stated plainly so there are no surprises: stitching multiple clips with
transitions, cutting stumbles and restarted sentences, adding music, cover
frames, searching the web for B-roll. In the panel those are marked 🔧 — you can
tick them, but Claude will tell you they're still manual.

## Layout

```
montazher/
├── inbox/          your recordings + their briefs
│   └── assets/     one-off inserts for a specific clip
├── library/        permanent insert library + catalog.json
├── engine/
│   ├── bin/        transcription, layout, cuts, faces, brightness
│   ├── src/        Remotion compositions and brands
│   └── public/     the video the renderer sees
├── panel/          the "video brief" panel
└── out/            finished clips
```

## Built on

This package didn't rewrite what others already did well. Thanks to:

- [Remotion](https://www.remotion.dev) — video rendering from React code.
  **Note: Remotion has its own licence.** Free for individuals and small teams;
  companies past a certain size need a paid one —
  [terms here](https://www.remotion.dev/license).
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — local speech
  recognition with word-level timestamps (MIT).
- [OpenMontage](https://github.com/openmontage/openmontage) — the agentic video
  studio that started the idea (AGPL-3.0; none of its code ships here).
- [FFmpeg](https://ffmpeg.org) — everything to do with the video itself.
- [Google Fonts](https://fonts.google.com) under the Open Font License:
  Montserrat, Inter, Playfair Display, Great Vibes, Comforter Brush.

## Licence

[PolyForm Perimeter 1.0.1](LICENSE.md). In short: use it freely, including in
your own work and for clients. The one thing you can't do is sell it as a
competing product of your own.

---

Made by **Olena Dubytska** — a marketer who shoots a lot of video and got tired
of placing captions by hand.

[@hlyboki_sensy](https://www.instagram.com/hlyboki_sensy/) · [hlyboki-sensy.com](https://hlyboki-sensy.com)
