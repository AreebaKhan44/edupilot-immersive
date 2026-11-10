"""Pictures the system draws itself when the book has no picture for a scene.

A scene's text is turned into a small *diagram spec*  {"kind": "flow"|"cycle"|"map", "nodes": [{"label","detail"}]}:
  flow  - steps that happen one after another   (first / then / next / finally ...)
  cycle - a process that repeats                 (the text talks about a cycle)
  map   - one central idea with its parts        (default)
The same spec is used twice: Pillow draws it as a clear 1280x720 picture (lesson page, video, 3D picture board) and
the 3D viewer builds a 3D version of it (viewer.js). Built-in 3D subjects (solar system, cell, atom, circuit, DNA,
geometry) get their own illustration instead. Nothing here needs an internet connection or an API key.
"""
import math
import re
from pathlib import Path

from PIL import Image, ImageDraw

from . import media
from .textproc import keywords, split_sentences, trim, WORD_RE

KINDS = ("flow", "cycle", "map")
BUILTIN_VISUALS = ("solar", "cell", "atom", "circuit", "dna", "geometry", "bits")
SEQ_RE = re.compile(r"\b(first(?:ly)?|second(?:ly)?|third(?:ly)?|then|next|after that|afterwards|finally|lastly|step \d|stage \d|phase \d|"
                    r"pehle|phir|uske baad|akhir mein|aakhir|پہلے|پھر|اس کے بعد|آخر میں)\b", re.IGNORECASE)
CYCLE_RE = re.compile(r"\bcycle\b|\bcycles\b|cyclic|repeats? again|دورہ|چکر|chakkar", re.IGNORECASE)


def _sentence_for(term, sentences):
    for s in sentences:
        if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", s, re.IGNORECASE):
            return s
    return ""


def _label(sentence):
    """Short heading for a step: its two most important words, in the order they appear in the sentence."""
    cleaned = SEQ_RE.sub(" ", sentence)
    top = set(keywords(cleaned, 3))
    seen, out = set(), []
    for w in WORD_RE.findall(cleaned):
        lw = w.lower()
        if lw in top and lw not in seen:
            seen.add(lw)
            out.append(w.title())
    return trim(" ".join(out[:2]) or cleaned, 28)


def make_spec(title, narration, key_points=(), labels=(), language="en"):
    """Build a diagram spec from scene text (offline, deterministic)."""
    text = " ".join([narration or "", " ".join(key_points or [])]).strip()
    sents, seen = [], set()
    for s in split_sentences(narration or text):          # narration and key points repeat each other: use each sentence once
        k = " ".join(s.lower().split())
        if len(s) > 25 and k not in seen:
            seen.add(k)
            sents.append(s)
    sents = sents or ([trim(text, 160)] if text else [])
    n_seq = len(SEQ_RE.findall(text))
    if CYCLE_RE.search(text) and len(sents) >= 3:
        kind = "cycle"
    elif n_seq >= 2 and len(sents) >= 3:
        kind = "flow"
    else:
        kind = "map"
    nodes = []
    if kind in ("flow", "cycle"):
        for s in sents[:6]:
            nodes.append({"label": _label(s), "detail": trim(SEQ_RE.sub("", s).strip(" ,;:"), 95)})
    else:
        terms = [l for l in (labels or []) if l] or [k.title() for k in keywords(text, 5)]
        for t in terms[:5]:
            nodes.append({"label": trim(str(t), 26), "detail": trim(_sentence_for(t, sents), 95)})
        if len(nodes) < 2:       # nothing to relate: show the key points as cards around the title
            nodes = [{"label": trim(p, 26), "detail": trim(p, 95)} for p in (key_points or [])[:4]]
    return {"kind": kind, "title": trim(title, 60), "nodes": nodes[:6]}


def validate_spec(spec, fallback_title=""):
    """Accept an LLM/teacher supplied spec only if it is well formed; returns a clean spec or None."""
    if not isinstance(spec, dict) or spec.get("kind") not in KINDS or not isinstance(spec.get("nodes"), list):
        return None
    nodes = []
    for n in spec["nodes"][:6]:
        if isinstance(n, dict) and str(n.get("label", "")).strip():
            nodes.append({"label": trim(str(n["label"]), 28), "detail": trim(str(n.get("detail", "")), 100)})
    if len(nodes) < 2:
        return None
    return {"kind": spec["kind"], "title": trim(str(spec.get("title") or fallback_title), 60), "nodes": nodes}


def describe(spec):
    """Text alternative for screen readers (WCAG): what the picture shows."""
    names = [n["label"] for n in spec.get("nodes", [])]
    if spec.get("kind") == "flow":
        return f"Flow diagram: {spec.get('title', '')}. Steps in order: " + ", then ".join(names) + "."
    if spec.get("kind") == "cycle":
        return f"Cycle diagram: {spec.get('title', '')}. The process repeats through: " + ", ".join(names) + "."
    return f"Concept map: {spec.get('title', '')}, connected to " + ", ".join(names) + "."


# ---------------------------------------------------------------- drawing
INK, SOFT = (24, 36, 70, 255), (84, 98, 130, 255)


def _hex(c):
    return media._rgb(c)


def _card(d, box, fill, outline, radius=22, shadow=True):
    x0, y0, x1, y1 = box
    if shadow:
        d.rounded_rectangle([x0 + 4, y0 + 6, x1 + 4, y1 + 6], radius=radius, fill=(30, 50, 110, 40))
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=3)


def _arrow(d, a, b, color, width=5, head=16):
    d.line([a, b], fill=color, width=width)
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    for s in (-0.45, 0.45):
        d.line([b, (b[0] - head * math.cos(ang + s), b[1] - head * math.sin(ang + s))], fill=color, width=width)


def _text_block(d, x, y, text, font, max_w, fill, language, line_h, max_lines, center=True):
    """Draw wrapped text; returns the y below it. Centre-aligned inside max_w around x when center."""
    rtl_mode = language in ("ur", "ar")
    lines = media.wrap_text(d, text, font, max_w, language)[:max_lines]
    for ln in lines:
        d.text((x, y), ln, font=font, fill=fill, anchor="ma" if center else ("ra" if rtl_mode else "la"))
        y += line_h
    return y


def _node_card(d, cx, cy, w, h, node, idx, color, language, numbered=True):
    box = (int(cx - w / 2), int(cy - h / 2), int(cx + w / 2), int(cy + h / 2))
    _card(d, box, (255, 255, 255, 255), color + (255,))
    if numbered:
        d.ellipse([box[0] - 16, box[1] - 16, box[0] + 24, box[1] + 24], fill=color + (255,))
        d.text((box[0] + 4, box[1] + 4), str(idx), font=media._font(22, True), fill=(255, 255, 255, 255), anchor="mm")
    y = box[1] + 14
    y = _text_block(d, cx, y, node["label"], media._font(26, True, language), w - 28, INK, language, 32, 2)
    if node.get("detail"):
        _text_block(d, cx, y + 2, node["detail"], media._font(19, False, language), w - 30, SOFT, language, 25, max(1, int((box[3] - y - 10) // 25)))


def _canvas(title, color, language, subtitle):
    img = Image.new("RGB", (media.W, media.H), (244, 248, 255))
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([0, 0, media.W, 88], fill=color + (255,))
    d.text((media.W // 2, 44), media.rtl(title, language), font=media._font(38, True, language), fill=(255, 255, 255, 255), anchor="mm")
    d.text((media.W - 24, media.H - 16), subtitle, font=media._font(15), fill=(120, 134, 168, 255), anchor="rd")
    return img, d


def render_diagram(spec, out_path, language="en", color="#5579ff"):
    """Draw a diagram spec as a 1280x720 PNG. Returns out_path."""
    col = _hex(color)
    nodes = spec["nodes"]
    img, d = _canvas(spec.get("title", ""), col, language, "Auto-generated from the lesson text - check it against your book")
    n = len(nodes)
    kind = spec["kind"]
    if kind == "flow":
        per_row = 3 if n > 3 else n
        rows = math.ceil(n / per_row)
        w, h = 330, 190 if rows == 1 else 175
        gap_x = (media.W - 2 * 60 - per_row * w) / max(1, per_row - 1) if per_row > 1 else 0
        top = 130 + (0 if rows > 1 else 120)
        pos = []
        for i in range(n):
            r, c = divmod(i, per_row)
            cx = 60 + w / 2 + c * (w + gap_x) if per_row > 1 else media.W / 2
            pos.append((cx, top + h / 2 + r * (h + 70)))
        for i in range(n - 1):
            (x0, y0), (x1, y1) = pos[i], pos[i + 1]
            if abs(y0 - y1) < 5:
                _arrow(d, (x0 + w / 2 + 6, y0), (x1 - w / 2 - 6, y1), col + (255,))
            else:   # wrap to the next row: down, left, down
                _arrow(d, (x0, y0 + h / 2 + 4), (x1, y1 - h / 2 - 6), col + (255,))
        for i, nd in enumerate(nodes):
            _node_card(d, pos[i][0], pos[i][1], w, h, nd, i + 1, col, language)
    elif kind == "cycle":
        cx, cy, R = media.W / 2, 408, 215
        w, h = 300, 128
        pts = [(cx + R * 1.45 * math.cos(-math.pi / 2 + 2 * math.pi * i / n), cy + R * math.sin(-math.pi / 2 + 2 * math.pi * i / n)) for i in range(n)]
        d.ellipse([cx - R * 1.45, cy - R, cx + R * 1.45, cy + R], outline=col + (110,), width=4)
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            ang = math.atan2(b[1] - a[1], b[0] - a[0])
            _arrow(d, (mx - 22 * math.cos(ang), my - 22 * math.sin(ang)), (mx + 22 * math.cos(ang), my + 22 * math.sin(ang)), col + (255,), 6, 18)
        d.ellipse([cx - 78, cy - 50, cx + 78, cy + 50], fill=col + (30,))
        _text_block(d, cx, cy - 26, "Repeats", media._font(26, True), 150, col + (255,), "en", 30, 2)
        for i, nd in enumerate(nodes):
            _node_card(d, pts[i][0], pts[i][1], w, h, nd, i + 1, col, language)
    else:   # concept map
        cx, cy = media.W / 2, 408
        hub_r = 86
        w, h = 300, 142
        pts = [(cx + 410 * math.cos(-math.pi / 2 + 2 * math.pi * i / n), cy + 215 * math.sin(-math.pi / 2 + 2 * math.pi * i / n)) for i in range(n)]
        for p in pts:
            d.line([(cx, cy), p], fill=col + (130,), width=5)
        media.sphere(d, cx, cy, hub_r, color)
        d.text((cx, cy), "\n".join(media.wrap_text(d, spec.get("title", ""), media._font(22, True, language), hub_r * 1.6, language)[:3]),
               font=media._font(22, True, language), fill=(255, 255, 255, 255), anchor="mm", align="center")
        for i, nd in enumerate(nodes):
            _node_card(d, pts[i][0], pts[i][1], w, h, nd, i + 1, col, language, numbered=False)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    return out


def render_builtin(vtype, color, labels, out_path, language="en"):
    """Large picture for one of the built-in subjects (solar system, cell, atom, circuit, DNA, geometry)."""
    img = media._background()
    d = ImageDraw.Draw(img, "RGBA")
    d.ellipse([-200, media.H - 120, media.W + 200, media.H + 380], fill=(208, 237, 255, 30))
    media.draw_visual(img, vtype, color, labels, cx=media.W // 2, cy=media.H // 2 + 10, language=language)
    d = ImageDraw.Draw(img, "RGBA")
    d.text((media.W - 24, media.H - 16), "Auto-generated illustration - not to scale", font=media._font(15), fill=(190, 205, 240, 255), anchor="rd")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    return out
