"""Пошук обличчя в кадрі — щоб субтитри не сідали людині на лице.

Використовує Vision, вбудований у macOS: працює локально, нічого не качає,
нічого не коштує. Кадри витягує ffmpeg.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Vision живе в pyobjc, а pyobjc — в оточенні пакета (його ставить install.sh).
# Тому кадри розбирає окремий процес саме з тим інтерпретатором.
import _paths  # noqa: E402

# Vision знаходить саме лице — без волосся, підборіддя й шиї. Розширюємо рамку,
# щоб текст не чіплявся за край зачіски чи за підборіддя.
PAD_SIDES = 0.085
PAD_TOP = 0.075
PAD_BOTTOM = 0.055

_DETECT_SNIPPET = r'''
import sys, json
import Quartz, Vision
from Foundation import NSURL

out = []
for path in sys.argv[1:]:
    url = NSURL.fileURLWithPath_(path)
    src = Quartz.CGImageSourceCreateWithURL(url, None)
    if src is None:
        out.append(None); continue
    img = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    if img is None:
        out.append(None); continue
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(img, None)
    req = Vision.VNDetectFaceRectanglesRequest.alloc().init()
    handler.performRequests_error_([req], None)
    res = req.results() or []
    if not res:
        out.append(None); continue
    # Найбільше обличчя в кадрі — це той, хто говорить.
    best = max(res, key=lambda o: o.boundingBox().size.width * o.boundingBox().size.height)
    b = best.boundingBox()
    # Vision рахує від нижнього лівого кута — перевертаємо у звичні координати.
    out.append({"x": b.origin.x, "y": 1.0 - b.origin.y - b.size.height,
                "w": b.size.width, "h": b.size.height,
                "confidence": float(best.confidence())})
sys.stdout.write("@@JSON@@" + json.dumps(out))
'''


def _grab_frames(video: Path, times: list[float], workdir: Path) -> list[Path]:
    paths = []
    for i, t in enumerate(times):
        out = workdir / f"f{i:04d}.jpg"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{max(t, 0):.2f}",
             "-i", str(video), "-frames:v", "1", "-vf", "scale=480:-1", str(out)],
            capture_output=True,
        )
        paths.append(out)
    return paths


def detect(video: Path, times: list[float]) -> list[dict | None]:
    """Для кожного моменту часу повертає рамку обличчя в частках кадру або None."""
    if not times:
        return []
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        frames = _grab_frames(video, times, workdir)
        existing = [p for p in frames if p.exists()]
        if not existing:
            return [None] * len(times)
        proc = subprocess.run(
            [_paths.python_with("Vision"), "-c", _DETECT_SNIPPET, *[str(p) for p in existing]],
            capture_output=True, text=True,
        )
        if "@@JSON@@" not in proc.stdout:
            return [None] * len(times)
        import json
        found = json.loads(proc.stdout.split("@@JSON@@", 1)[1])

    by_path = dict(zip(existing, found))
    return [by_path.get(p) for p in frames]


def padded(face: dict) -> dict:
    """Рамка обличчя з запасом на волосся, підборіддя й шию."""
    x = face["x"] - PAD_SIDES
    y = face["y"] - PAD_TOP
    w = face["w"] + 2 * PAD_SIDES
    h = face["h"] + PAD_TOP + PAD_BOTTOM
    return {"x": max(x, 0.0), "y": max(y, 0.0),
            "w": min(w, 1.0), "h": min(h, 1.0)}


def fill_gaps(faces: list[dict | None]) -> list[dict | None]:
    """Там, де обличчя не знайшлося, підставляє сусіднє — краще, ніж нічого."""
    known = [f for f in faces if f]
    if not known:
        return faces
    median = {
        k: sorted(f[k] for f in known)[len(known) // 2]
        for k in ("x", "y", "w", "h")
    }
    out, last = [], None
    for f in faces:
        if f:
            last = f
            out.append(f)
        else:
            out.append(last or median)
    return out


def union(boxes: list[dict]) -> dict | None:
    """Обʼєднана рамка — щоб врахувати рух людини за весь час показу репліки."""
    real = [b for b in boxes if b]
    if not real:
        return None
    x = min(b["x"] for b in real)
    y = min(b["y"] for b in real)
    x2 = max(b["x"] + b["w"] for b in real)
    y2 = max(b["y"] + b["h"] for b in real)
    return {"x": x, "y": y, "w": x2 - x, "h": y2 - y}
