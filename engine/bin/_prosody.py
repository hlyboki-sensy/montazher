"""Акустика запису: гучність, острівці мовлення, висота голосу, гармонійність.

Потрібна рівно для одного: відрізнити обрив («людина збилася») від нормального
завершення слова. Усе міряється на numpy — жодної нової залежності, бо numpy
вже приїжджає разом із розпізнавачем мови.

Чому не parselmouth. Він точніший і швидший, але тягне за собою 8,6 МБ і ще
один крок в інсталяторі — а вирішальна ознака (провал енергії в точці обриву)
рахується тривіально й без нього. Висоту голосу беремо автокореляцією, а
гармонійність (HNR) — із того самого піка автокореляції за формулою Бурсми:
HNR = 10·log10(r / (1 − r)). Це те саме, що рахує Praat.

Дорогі ознаки (висота, HNR) рахуються ЛИШЕ навколо кандидатів, а не на весь
файл: на шестихвилинному записі це різниця між пів секунди і пів хвилини.
"""

from __future__ import annotations

import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

HOP = 0.010          # крок сітки, 10 мс
RMS_WIN = 0.025      # вікно гучності
PITCH_WIN = 0.048    # вікно висоти: два періоди навіть на 70 Гц це 28 мс, беремо із запасом
F0_MIN, F0_MAX = 70.0, 400.0
VOICED_R = 0.35      # нижче цього піка автокореляції кадр вважаємо неозвученим

SPEECH_DB = -34.0    # тихіше за це від піку файлу — тиша
MIN_ISLAND = 0.10    # острівець коротший за 100 мс — це поштовх, а не мовлення
MIN_GAP = 0.12       # тиша коротша за 120 мс — це змикання в слові, не пауза


def extract_wav(source: Path, dest: Path) -> Path:
    """16 кГц моно — рівно те, на чому працює і розпізнавач, і ця арифметика."""
    if dest.exists() and dest.stat().st_mtime >= source.stat().st_mtime:
        return dest
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(source),
           "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dest)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"Не вдалося витягти звук:\n{res.stderr[-1500:]}")
    return dest


class Voice:
    """Один запис і все, що про нього можна спитати."""

    def __init__(self, wav: Path):
        with wave.open(str(wav), "rb") as f:
            rate, width, channels = f.getframerate(), f.getsampwidth(), f.getnchannels()
            raw = f.readframes(f.getnframes())
        dtype = {1: np.int8, 2: np.int16, 4: np.int32}[width]
        x = np.frombuffer(raw, dtype=dtype).astype(np.float32)
        if channels > 1:
            x = x.reshape(-1, channels).mean(axis=1)
        peak = float(np.abs(x).max()) or 1.0
        self.x = x / peak
        self.rate = rate
        self.dur = len(self.x) / rate

        hop = max(1, int(rate * HOP))
        win = max(hop, int(rate * RMS_WIN))
        n = max(1, (len(self.x) - win) // hop + 1)
        idx = np.arange(n) * hop
        frames = np.lib.stride_tricks.sliding_window_view(self.x, win)[idx]
        rms = np.sqrt((frames ** 2).mean(axis=1)) + 1e-9
        self.hop_sec = hop / rate
        self.db = 20.0 * np.log10(rms / rms.max())

    # ── гучність ────────────────────────────────────────────────────────────
    def _frames(self, a: float, b: float) -> slice:
        i = int(max(a, 0.0) / self.hop_sec)
        j = int(max(b, 0.0) / self.hop_sec) + 1
        return slice(min(i, len(self.db)), min(max(j, i), len(self.db)))

    def slice_db(self, a: float, b: float) -> np.ndarray:
        return self.db[self._frames(a, b)]

    def islands(self, a: float, b: float) -> list[tuple[float, float]]:
        """Острівці мовлення в проміжку — у секундах від початку файлу.

        Це відповідь на питання «що сховане всередині розпухлого токена»:
        один острівець означає слово, а далі звичайна пауза (норма), два і
        більше — людина замовкла й заговорила знову.
        """
        seg = self.slice_db(a, b)
        if seg.size == 0:
            return []
        loud = seg > SPEECH_DB
        runs: list[list[int]] = []
        start = None
        for k, on in enumerate(loud):
            if on and start is None:
                start = k
            elif not on and start is not None:
                runs.append([start, k])
                start = None
        if start is not None:
            runs.append([start, len(loud)])

        merged: list[list[int]] = []
        for s, e in runs:
            if merged and (s - merged[-1][1]) * self.hop_sec < MIN_GAP:
                merged[-1][1] = e
            else:
                merged.append([s, e])
        base = self._frames(a, b).start * self.hop_sec
        return [(base + s * self.hop_sec, base + e * self.hop_sec)
                for s, e in merged if (e - s) * self.hop_sec >= MIN_ISLAND]

    def longest_silence(self, a: float, b: float) -> float:
        isl = self.islands(a, b)
        if len(isl) < 2:
            return 0.0
        return max(nxt[0] - cur[1] for cur, nxt in zip(isl, isl[1:]))

    def drop_at_end(self, a: float, b: float, tail: float = 0.06) -> float:
        """Перепад між тілом ділянки та її останніми 60 мс, у децибелах.

        Нормальне завершення слова — 3-5 дБ, обрив — близько 13. Коридор між
        ними порожній, тому це найнадійніша ознака з усіх.
        """
        edge = max(b - tail, a + self.hop_sec)
        body, end = self.slice_db(a, edge), self.slice_db(max(b - tail, a), b)
        if body.size == 0 or end.size == 0:
            return 0.0
        return float(np.percentile(body, 90) - np.percentile(end, 90))

    def loudness(self, a: float, b: float) -> float:
        seg = self.slice_db(a, b)
        return float(np.percentile(seg, 90)) if seg.size else -120.0

    # ── висота й гармонійність ──────────────────────────────────────────────
    def pitch(self, a: float, b: float) -> tuple[np.ndarray, np.ndarray]:
        """(f0, hnr) по сітці 10 мс. Неозвучені кадри — nan в обох масивах."""
        win = int(self.rate * PITCH_WIN)
        hop = int(self.rate * HOP)
        i0 = max(0, int(a * self.rate))
        i1 = min(len(self.x), int(b * self.rate) + win)
        seg = self.x[i0:i1]
        if len(seg) < win + hop:
            return np.array([]), np.array([])

        n = (len(seg) - win) // hop + 1
        frames = np.lib.stride_tricks.sliding_window_view(seg, win)[np.arange(n) * hop]
        frames = frames - frames.mean(axis=1, keepdims=True)
        frames = frames * np.hanning(win)

        size = 1 << int(np.ceil(np.log2(2 * win)))
        spec = np.fft.rfft(frames, n=size, axis=1)
        corr = np.fft.irfft(spec * np.conj(spec), n=size, axis=1)[:, :win]
        zero = corr[:, :1].copy()
        zero[zero <= 0] = 1e-12
        corr = corr / zero
        # Нормування на автокореляцію самого вікна — без цього Hann сам по собі
        # тягне пік донизу зі зростанням лагу, і HNR виходить заниженим на
        # кілька децибел. Praat робить рівно це (Boersma 1993).
        corr = corr / np.maximum(self._win_corr(win, size), 1e-6)

        lo, hi = int(self.rate / F0_MAX), min(win - 1, int(self.rate / F0_MIN))
        if hi <= lo:
            return np.array([]), np.array([])
        band = corr[:, lo:hi + 1]
        lag = band.argmax(axis=1) + lo
        r = band.max(axis=1)

        f0 = self.rate / lag.astype(np.float64)
        r = np.clip(r, 0.0, 0.999)
        hnr = 10.0 * np.log10(np.maximum(r, 1e-6) / np.maximum(1.0 - r, 1e-6))
        unvoiced = r < VOICED_R
        f0[unvoiced] = np.nan
        hnr[unvoiced] = np.nan
        return f0, hnr

    @staticmethod
    def _win_corr(win: int, size: int) -> np.ndarray:
        """Автокореляція вікна Ганна, нормована на нуль."""
        w = np.hanning(win)
        sp = np.fft.rfft(w, n=size)
        c = np.fft.irfft(sp * np.conj(sp), n=size)[:win]
        return c / (c[0] or 1e-12)

    def voiced_fraction(self, a: float, b: float) -> float:
        f0, _ = self.pitch(a, b)
        return float(np.mean(~np.isnan(f0))) if f0.size else 0.0

    def tail_hnr(self, a: float, b: float) -> float:
        """Медіанний HNR озвучених кадрів. nan, якщо озвучених немає взагалі."""
        _, hnr = self.pitch(a, b)
        good = hnr[~np.isnan(hnr)] if hnr.size else np.array([])
        return float(np.median(good)) if good.size else float("nan")

    def contour(self, a: float, b: float) -> np.ndarray:
        """Контур висоти в напівтонах від 100 Гц, із заповненими пропусками."""
        f0, _ = self.pitch(a, b)
        if f0.size == 0 or np.all(np.isnan(f0)):
            return np.array([])
        st = 12.0 * np.log2(f0 / 100.0)
        idx = np.arange(len(st))
        good = ~np.isnan(st)
        if good.sum() < 2:
            return np.array([])
        return np.interp(idx, idx[good], st[good])

    def median_f0(self, a: float, b: float) -> float:
        f0, _ = self.pitch(a, b)
        good = f0[~np.isnan(f0)] if f0.size else np.array([])
        return float(np.median(good)) if good.size else float("nan")


def corr_contours(one: np.ndarray, two: np.ndarray) -> float:
    """Кореляція двох контурів після приведення до спільної довжини.

    Негативна кореляція — підпис НАВМИСНОГО повтору: кожен елемент списку несе
    свою тональну роль. При простій хезитації контур, навпаки, зберігається.
    """
    if one.size < 3 or two.size < 3:
        return float("nan")
    m = min(len(one), len(two))
    grid = np.linspace(0, 1, m)
    a = np.interp(grid, np.linspace(0, 1, len(one)), one)
    b = np.interp(grid, np.linspace(0, 1, len(two)), two)
    if a.std() < 1e-6 or b.std() < 1e-6:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])
