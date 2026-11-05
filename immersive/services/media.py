"""Scene pictures (Pillow) and lesson videos (Pillow frames + TTS + ffmpeg)."""
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf", "DejaVuSans.ttf",
]
BOLD_PATHS = [p.replace("DejaVuSans.ttf", "DejaVuSans-Bold.ttf").replace("segoeui.ttf", "segoeuib.ttf")
              .replace("arial.ttf", "arialbd.ttf") for p in FONT_PATHS]


def _font(size, bold=False):
    for p in (BOLD_PATHS if bold else FONT_PATHS):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def rtl(text, language):
    """Shape Urdu/Arabic text for Pillow (needs arabic-reshaper + python-bidi; optional)."""
    if language not in ("ur", "ar"):
        return text
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text


def _rgb(hexcolor):
    h = hexcolor.lstrip("#")
    if len(h) != 6:
        h = "5579ff"
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _background():
    top, bot = np.array([16, 29, 54]), np.array([49, 91, 222])
    t = np.linspace(0, 1, H)[:, None, None]
    arr = (top * (1 - t) + bot * t).repeat(W, axis=1).astype("uint8")
    return Image.fromarray(arr, "RGB")


# ---- little 3D-looking primitives ------------------------------------------------------------
def sphere(d, cx, cy, r, color, glow=False):
    base = _rgb(color) if isinstance(color, str) else color
    dark, light = _mix(base, (0, 0, 0), 0.4), _mix(base, (255, 255, 255), 0.6)
    if glow:
        for k in range(6, 0, -1):
            d.ellipse([cx - r - k * 8, cy - r - k * 8, cx + r + k * 8, cy + r + k * 8], fill=base + (16,))
    steps = 24
    for i in range(steps):
        t = i / (steps - 1)
        rr = r * (1 - 0.82 * t)
        ox, oy = -r * 0.3 * t, -r * 0.3 * t
        col = _mix(dark, base, t / 0.45) if t < 0.45 else _mix(base, light, (t - 0.45) / 0.55)
        d.ellipse([cx + ox - rr, cy + oy - rr, cx + ox + rr, cy + oy + rr], fill=col + (255,))


def ring(d, cx, cy, a, b, angle=0.0, color=(255, 255, 255, 90), width=2):
    pts = []
    for i in range(121):
        t = 2 * math.pi * i / 120
        x, y = a * math.cos(t), b * math.sin(t)
        pts.append((cx + x * math.cos(angle) - y * math.sin(angle), cy + x * math.sin(angle) + y * math.cos(angle)))
    d.line(pts, fill=color, width=width)


def label(d, x, y, text, size=18, anchor="mm", fill=(255, 255, 255, 235), language="en"):
    d.text((x, y), rtl(text, language), font=_font(size, True), fill=fill, anchor=anchor)


def draw_visual(img, vtype, color, labels, cx=940, cy=370, size=240, language="en"):
    d = ImageDraw.Draw(img, "RGBA")
    labels = labels or []
    if vtype == "solar":
        sphere(d, cx - 90, cy, 56, "#ffcc33", glow=True)
        for i, (rad, col, nm) in enumerate([(105, "#b5a79a", "Mercury"), (150, "#e6b86a", "Venus"), (200, "#3b82f6", "Earth"), (250, "#d1603d", "Mars")]):
            ring(d, cx - 90, cy, rad, rad * 0.42, 0)
            ang = 0.9 + i * 1.35
            px, py = cx - 90 + rad * math.cos(ang), cy + rad * 0.42 * math.sin(ang)
            sphere(d, px, py, 12 + i * 2, col)
            label(d, px, py + 28, nm, 14, language=language)
    elif vtype == "cell":
        d.ellipse([cx - 280, cy - 210, cx + 280, cy + 210], fill=(17, 168, 139, 70), outline=(180, 255, 235, 200), width=5)
        sphere(d, cx - 40, cy - 10, 70, "#7a5bf1")
        label(d, cx - 40, cy - 10, "Nucleus", 18, language=language)
        for (ox, oy, nm) in [(150, -90, "Mitochondria"), (-170, 80, "Ribosomes"), (120, 110, "Vacuole")]:
            sphere(d, cx + ox, cy + oy, 34, "#f0aa49")
            label(d, cx + ox, cy + oy + 52, nm, 15, language=language)
    elif vtype == "atom":
        for a in (0, math.pi / 3, 2 * math.pi / 3):
            ring(d, cx, cy, 230, 80, a, width=3)
        for k in range(5):
            sphere(d, cx + (k % 2 - .5) * 30, cy + (k // 2 - 1) * 26, 24, "#e5484d" if k % 2 else "#7a8bff")
        for a, t in [(0, 0.6), (math.pi / 3, 2.4), (2 * math.pi / 3, 4.2)]:
            x, y = 230 * math.cos(t), 80 * math.sin(t)
            sphere(d, cx + x * math.cos(a) - y * math.sin(a), cy + x * math.sin(a) + y * math.cos(a), 12, "#7fe3ff")
        label(d, cx, cy + 190, "Nucleus + electrons", 17, language=language)
    elif vtype == "circuit":
        x0, y0, x1, y1 = cx - 230, cy - 130, cx + 230, cy + 130
        d.rectangle([x0, y0, x1, y1], outline=(255, 255, 255, 230), width=7)
        d.rectangle([x0 - 22, cy - 55, x0 + 22, cy + 55], fill=(20, 30, 60, 255), outline=(255, 255, 255, 255), width=3)
        label(d, x0, cy, "+ –", 22, language=language)
        sphere(d, cx, y0, 36, "#ffe066", glow=True)
        label(d, cx, y0 - 62, "Bulb", 17, language=language)
        d.rectangle([cx - 40, y1 - 14, cx + 40, y1 + 14], fill=(240, 170, 73, 255))
        label(d, cx, y1 + 38, "Resistor", 17, language=language)
        label(d, x0, cy + 85, "Battery", 17, language=language)
    elif vtype == "dna":
        pts_a, pts_b = [], []
        for i in range(60):
            t = i / 59
            y = cy - 250 + 500 * t
            x = 95 * math.sin(t * 6 * math.pi)
            pts_a.append((cx + x, y)); pts_b.append((cx - x, y))
            if i % 3 == 0:
                d.line([(cx + x, y), (cx - x, y)], fill=(255, 255, 255, 130), width=3)
        d.line(pts_a, fill=(255, 120, 160, 255), width=6)
        d.line(pts_b, fill=(120, 200, 255, 255), width=6)
        for i in range(0, 60, 3):
            sphere(d, *pts_a[i], 9, "#ff7aa8"); sphere(d, *pts_b[i], 9, "#7ac8ff")
    elif vtype == "geometry":
        # isometric cube
        s = 110
        top = [(cx - 190, cy - 20), (cx - 190 + s, cy - 20 - s * .55), (cx - 190 + 2 * s, cy - 20), (cx - 190 + s, cy - 20 + s * .55)]
        d.polygon(top, fill=(140, 220, 255, 255))
        d.polygon([top[3], top[2], (top[2][0], top[2][1] + s), (top[3][0], top[3][1] + s)], fill=(60, 140, 230, 255))
        d.polygon([top[0], top[3], (top[3][0], top[3][1] + s), (top[0][0], top[0][1] + s)], fill=(40, 100, 200, 255))
        label(d, cx - 190 + s, cy + 150, "Cube", 18, language=language)
        # pyramid
        bx, by = cx + 150, cy + 80
        d.polygon([(bx, by - 190), (bx - 110, by), (bx + 20, by + 50)], fill=(255, 190, 90, 255))
        d.polygon([(bx, by - 190), (bx + 20, by + 50), (bx + 130, by - 10)], fill=(220, 130, 40, 255))
        label(d, bx, by + 85, "Pyramid", 18, language=language)
    else:  # concept cluster
        sphere(d, cx, cy, 78, color, glow=True)
        label(d, cx, cy, (labels[0] if labels else "Concept")[:14], 19, language=language)
        others = labels[1:6] or ["Idea", "Example", "Use"]
        for i, nm in enumerate(others):
            ang = -math.pi / 2 + i * 2 * math.pi / len(others)
            ring(d, cx, cy, 205, 205, 0, width=1)
            px, py = cx + 205 * math.cos(ang), cy + 205 * math.sin(ang)
            d.line([(cx, cy), (px, py)], fill=(255, 255, 255, 70), width=2)
            sphere(d, px, py, 34, _mix(_rgb(color), (255, 255, 255), 0.25))
            label(d, px, py + 54, nm[:16], 16, language=language)


def _wrap(text, font, max_w, draw):
    lines, cur = [], ""
    for word in text.split():
        t = (cur + " " + word).strip()
        if draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def render_slide(scene, out_path, index=1, total=1, lesson_title="", language="en"):
    """Render one 1280x720 slide picture for a scene."""
    img = _background()
    d = ImageDraw.Draw(img, "RGBA")
    d.ellipse([-200, H - 120, W + 200, H + 380], fill=(208, 237, 255, 30))
    v = scene.visual or {}
    draw_visual(img, v.get("type", "cluster"), v.get("color", "#5579ff"), v.get("labels", []), language=language)
    d = ImageDraw.Draw(img, "RGBA")
    rtl_mode = language in ("ur", "ar")
    d.text((60, 44), f"EDUPILOT IMMERSIVE  ·  {rtl(lesson_title, language)[:60]}", font=_font(16, True), fill=(200, 215, 255, 255))
    tf = _font(44, True)
    y = 100
    for line in _wrap(rtl(scene.title, language), tf, 540, d)[:3]:
        d.text((60, y), line, font=tf, fill=(255, 255, 255, 255))
        y += 56
    y += 14
    bf = _font(25)
    for p in (scene.key_points or [])[:3]:
        lines = _wrap(rtl(p, language), bf, 500, d)[:3]
        d.ellipse([60, y + 10, 72, y + 22], fill=(120, 220, 255, 255))
        for ln in lines:
            d.text((90, y), ln, font=bf, fill=(235, 242, 255, 255))
            y += 34
        y += 14
        if y > H - 90:
            break
    d.rounded_rectangle([60, H - 62, 60 + 240, H - 30], radius=16, fill=(255, 255, 255, 30))
    d.text((80, H - 57), f"Scene {index} / {total}", font=_font(18, True), fill=(255, 255, 255, 255))
    img.save(out_path, "PNG", optimize=True)
    return out_path


# ---- narration -------------------------------------------------------------------------------
def ffprobe_duration(path):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                              "default=nk=1:nw=1", str(path)], capture_output=True, text=True, timeout=30)
        return float(out.stdout.strip())
    except Exception:
        return None


def synth(text, language, out_base):
    """Try gTTS (online) then espeak-ng (offline). Returns (path, engine) or (None, 'silent')."""
    text = " ".join(text.split())[:1500]
    try:
        from gtts import gTTS
        p = f"{out_base}.mp3"
        gTTS(text=text, lang={"ur": "ur", "hi": "hi"}.get(language, "en")).save(p)
        if os.path.getsize(p) > 1000:
            return p, "gtts"
    except Exception:
        pass
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    if exe:
        try:
            p = f"{out_base}.wav"
            subprocess.run([exe, "-v", {"ur": "ur", "hi": "hi"}.get(language, "en"), "-w", p, text],
                           check=True, capture_output=True, timeout=60)
            return p, "espeak"
        except Exception:
            pass
    return None, "silent"


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-800:])


def render_video(lesson, out_path, language="en", use_tts=True):
    """Build an MP4: one slide per scene with slow zoom + narration. Returns voice engine used."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed (install it and add to PATH).")
    scenes = list(lesson.scenes.all())
    if not scenes:
        raise RuntimeError("Lesson has no scenes.")
    engines = set()
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        clips = []
        for i, sc in enumerate(scenes, 1):
            png = os.path.join(tmp, f"s{i}.png")
            render_slide(sc, png, i, len(scenes), lesson.title, language)
            audio, eng = (synth(sc.narration, language, os.path.join(tmp, f"a{i}")) if use_tts else (None, "silent"))
            engines.add(eng)
            adur = ffprobe_duration(audio) if audio else None
            dur = (adur or max(6.0, len(sc.narration.split()) / 2.4)) + 0.8
            frames = int(dur * 25)
            clip = os.path.join(tmp, f"c{i}.mp4")
            cmd = ["ffmpeg", "-y", "-i", png]
            cmd += ["-i", audio] if audio else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
            cmd += ["-vf", f"zoompan=z='min(zoom+0.0007,1.09)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps=25,format=yuv420p",
                    "-af", "apad,aresample=44100", "-ac", "2", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
                    "-t", f"{dur:.2f}", "-r", "25", clip]
            _run(cmd)
            clips.append(clip)
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w") as f:
            f.writelines(f"file '{c}'\n" for c in clips)
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", str(out_path)])
    return "gtts" if "gtts" in engines else "espeak" if "espeak" in engines else "silent"
