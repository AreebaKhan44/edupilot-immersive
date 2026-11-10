"""Read a PDF page by page (text + pictures) and attach each picture to the lesson scene it belongs to.

Pictures that really are in the book are used first. Logos, rules, tiny icons and pictures repeated on many pages
(page headers) are skipped. Matching uses the text of the page the picture sits on: the page is compared with every
lesson's text, then with every scene's narration/key points inside the winning lesson.
"""
import hashlib
import io
import re
from collections import Counter
from pathlib import Path

from django.conf import settings

from .textproc import WORD_RE, STOP

MIN_SIDE = 110            # px: smaller pictures are bullets / icons
MIN_AREA = 22_000
MAX_ASPECT = 7.0          # very long thin pictures are rules / banners
MAX_IMAGES = 80
MAX_SIDE = 1600
FIG_RE = re.compile(r"^\s*(?:fig(?:ure)?\.?|diagram|chart|picture|image|تصویر|شکل|نقشہ)\s*[\d.:\-–]*\s*(.*)$", re.IGNORECASE)


# ---------------------------------------------------------------- reading
def read_pdf(data):
    """bytes -> (pages, images). pages = [text per page]; images = [{page, pil, hash, width, height}] (page is 1-based).

    PyMuPDF (pip install pymupdf) is used when it is installed: it draws every picture exactly as it looks on the book
    page (masks, CMYK, rotation, transparency and vector drawings are all handled). Without it the older pypdf reader is used."""
    try:
        import fitz  # noqa: F401  (PyMuPDF)
    except Exception:  # noqa: BLE001
        return _read_pdf_pypdf(data)
    try:
        return _read_pdf_mupdf(data)
    except Exception:  # noqa: BLE001 - damaged / odd file: fall back instead of losing the whole upload
        return _read_pdf_pypdf(data)


def _read_pdf_mupdf(data):
    import fitz
    doc = fitz.open(stream=data, filetype="pdf")
    pages, raw, seen = [], [], Counter()
    zoom = 2.0
    for pno in range(len(doc)):
        page = doc[pno]
        try:
            pages.append(page.get_text("text") or "")
        except Exception:  # noqa: BLE001
            pages.append("")
        pw, ph = page.rect.width, page.rect.height
        rects = []
        # 1) raster pictures: where each one is drawn on the page
        try:
            for img in page.get_images(full=True):
                for r in page.get_image_rects(img[0]):
                    rects.append(fitz.Rect(r))
        except Exception:  # noqa: BLE001
            pass
        # 2) vector figures (drawn with lines / shapes, not stored as a picture)
        if getattr(settings, "EDUPILOT_BOOK_VECTOR_FIGURES", True):
            try:
                rects += _vector_figures(page, rects)
            except Exception:  # noqa: BLE001
                pass
        for r in _merge_rects(rects, pw, ph):
            r = r & page.rect
            if r.is_empty or r.width < 40 or r.height < 40:
                continue
            if r.width * r.height > 0.92 * pw * ph:        # full-page background / scan: not a figure
                continue
            if max(r.width, r.height) / max(1.0, min(r.width, r.height)) > MAX_ASPECT:
                continue
            try:
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=r, alpha=False)   # exactly what the student sees in the book
                from PIL import Image
                pil = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            except Exception:  # noqa: BLE001
                continue
            w, h = pil.size
            if min(w, h) < MIN_SIDE or w * h < MIN_AREA:
                continue
            if _is_blank(pil):
                continue
            digest = hashlib.sha1(pil.convert("L").resize((16, 16)).tobytes()).hexdigest()[:16]
            seen[digest] += 1
            raw.append({"page": pno + 1, "pil": pil, "hash": digest, "width": w, "height": h})
    doc.close()
    return pages, _drop_repeated(raw, len(pages))


def _is_blank(pil):
    """True for an (almost) single-colour picture: empty frames, white boxes, lines."""
    small = pil.convert("L").resize((24, 24))
    px = list(small.getdata())
    return (max(px) - min(px)) < 12


def _merge_rects(rects, pw, ph, gap=14):
    """Pieces of one figure (several images / drawings side by side) become ONE picture."""
    import fitz
    rects = [fitz.Rect(r) for r in rects if r.width > 6 and r.height > 6]
    merged = True
    while merged:
        merged = False
        out = []
        for r in rects:
            for o in out:
                grown = fitz.Rect(o.x0 - gap, o.y0 - gap, o.x1 + gap, o.y1 + gap)
                if grown.intersects(r):
                    o |= r
                    merged = True
                    break
            else:
                out.append(fitz.Rect(r))
        rects = out
    # small margin so that outlines are not cut
    return [fitz.Rect(max(0, r.x0 - 6), max(0, r.y0 - 6), min(pw, r.x1 + 6), min(ph, r.y1 + 6)) for r in rects]


def _vector_figures(page, known):
    """Drawings that are not table borders / underlines: clusters made of curves or slanted lines (arrows, cartoons, diagrams)."""
    import fitz
    items = []
    for d in page.get_drawings():
        r = fitz.Rect(d["rect"])
        if r.width < 2 and r.height < 2:
            continue
        organic = 0
        for it in d.get("items", []):
            if it[0] in ("c", "qu"):
                organic += 1
            elif it[0] == "l" and abs(it[1].x - it[2].x) > 1.5 and abs(it[1].y - it[2].y) > 1.5:     # slanted line (table borders are straight)
                organic += 1
        items.append((r, organic))
    clusters = []
    for r, organic in items:
        for c in clusters:
            if fitz.Rect(c["r"].x0 - 10, c["r"].y0 - 10, c["r"].x1 + 10, c["r"].y1 + 10).intersects(r):
                c["r"] |= r
                c["n"] += 1
                c["organic"] += organic
                break
        else:
            clusters.append({"r": fitz.Rect(r), "n": 1, "organic": organic})
    out = []
    for c in clusters:
        r = c["r"]
        if c["n"] < 4 or c["organic"] < 3 or r.width < 50 or r.height < 50:      # table lines, boxes, underlines -> not pictures
            continue
        if any(k.contains(r) for k in known):
            continue
        out.append(r)
    return out


def _drop_repeated(raw, n_pages):
    """A picture that repeats on many pages is a logo / header, not teaching material; one picture per (page, look)."""
    seen = Counter(r["hash"] for r in raw)
    limit = max(3, n_pages // 4)
    uniq, keys = [], set()
    for r in raw:
        if seen[r["hash"]] > limit:
            continue
        k = (r["page"], r["hash"])
        if k not in keys:
            keys.add(k)
            uniq.append(r)
    return uniq[:MAX_IMAGES]


def _read_pdf_pypdf(data):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    pages, images, seen = [], [], Counter()
    raw = []
    for pno, page in enumerate(reader.pages, 1):
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - one bad page must not stop the whole book
            pages.append("")
        try:
            found = list(page.images)
        except Exception:  # noqa: BLE001
            found = []
        for im in found:
            try:
                pil = im.image
                if pil is None:
                    continue
                pil.load()
            except Exception:  # noqa: BLE001 - unsupported filter (JPX, CCITT ...) -> skip that picture
                continue
            w, h = pil.size
            if min(w, h) < MIN_SIDE or w * h < MIN_AREA or max(w, h) / max(1, min(w, h)) > MAX_ASPECT:
                continue
            small = pil.convert("L").resize((16, 16))
            digest = hashlib.sha1(small.tobytes()).hexdigest()[:16]
            seen[digest] += 1
            raw.append({"page": pno, "pil": pil, "hash": digest, "width": w, "height": h})
    # a picture that repeats on many pages is a logo / header, not teaching material
    limit = max(3, len(pages) // 4)
    for r in raw:
        if seen[r["hash"]] <= limit:
            images.append(r)
    # the same picture twice on one page is usually the same figure
    uniq, keys = [], set()
    for r in images:
        k = (r["page"], r["hash"])
        if k not in keys:
            keys.add(k)
            uniq.append(r)
    return pages, uniq[:MAX_IMAGES]


def save_images(book, images, media_root=None):
    """Write the pictures to MEDIA_ROOT/books/book_<id>/ and return [(relative_path, info)]."""
    from PIL import Image
    root = Path(media_root or settings.MEDIA_ROOT)
    d = root / "books" / f"book_{book.pk}"
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for n, info in enumerate(images, 1):
        pil = info["pil"]
        if pil.mode not in ("RGB", "RGBA", "L"):
            pil = pil.convert("RGB")
        if max(pil.size) > MAX_SIDE:
            pil.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
        has_alpha = pil.mode == "RGBA"
        ext = "png" if has_alpha else "jpg"
        name = f"p{info['page']:03d}_{n:02d}.{ext}"
        pil.convert("RGBA" if has_alpha else "RGB").save(d / name, "PNG" if has_alpha else "JPEG", **({} if has_alpha else {"quality": 88}))
        out.append((f"books/book_{book.pk}/{name}", dict(info, width=pil.size[0], height=pil.size[1])))
    return out


# ---------------------------------------------------------------- matching
def _norm(line):
    return " ".join(line.lower().split())


def _words(text):
    return {w.lower() for w in WORD_RE.findall(text) if w.lower() not in STOP}


def _page_lines(text):
    return [_norm(l) for l in text.split("\n") if len(l.strip()) >= 25]


def match_pages_to_lessons(pages, lessons):
    """For every page number find the lesson whose body contains most of the page's lines (fallback: shared words).
    Pages without text (picture-only pages) inherit the previous page's lesson. Returns {page_no: lesson}."""
    bodies = [(l, _norm(l.source_text)) for l in lessons]
    wsets = [(l, _words(l.source_text)) for l in lessons]
    result, last = {}, None
    for pno, text in enumerate(pages, 1):
        lines = _page_lines(text)
        best, best_score = None, 0.0
        if lines:
            for l, body in bodies:
                hit = sum(1 for ln in lines if ln in body)
                if hit > best_score:
                    best, best_score = l, hit
            if best is None:
                pw = _words(text)
                for l, ws in wsets:
                    if pw:
                        sc = len(pw & ws) / len(pw)
                        if sc > best_score and sc >= 0.25:
                            best, best_score = l, sc
        if best is None:
            best = last
        if best is not None:
            result[pno] = best
            last = best
    return result


def _scene_score(scene, words, caption_words):
    sw = _words(scene.narration + " " + " ".join(scene.key_points) + " " + scene.title)
    if not sw:
        return 0.0
    return len(sw & words) + 2.0 * len(sw & caption_words)


def caption_near(text):
    """Look for a 'Figure 2: ...' style line on the page; returns the caption text or ''."""
    for ln in text.split("\n"):
        m = FIG_RE.match(ln.strip())
        if m and len(ln.strip()) >= 8:
            cap = m.group(1).strip() or ln.strip()
            return cap[:200]
    return ""


def attach_images(book, pages, saved, lessons):
    """Create SceneImage rows. `saved` comes from save_images(); returns the number of pictures attached."""
    from ..models import Scene, SceneImage
    if not saved:
        return 0
    page_lesson = match_pages_to_lessons(pages, lessons)
    scenes_by_lesson = {l.pk: list(l.scenes.all()) for l in lessons}
    per_scene = Counter()
    n = 0
    for rel, info in saved:
        lesson = page_lesson.get(info["page"])
        if lesson is None:
            continue
        scenes = scenes_by_lesson.get(lesson.pk) or []
        if not scenes:
            continue
        text = pages[info["page"] - 1] if info["page"] - 1 < len(pages) else ""
        cap = caption_near(text)
        pw, cw = _words(text), _words(cap)
        ranked = sorted(scenes, key=lambda s: (_scene_score(s, pw, cw), -per_scene[s.pk]), reverse=True)
        scene = ranked[0]
        if _scene_score(scene, pw, cw) == 0:          # nothing in common: spread evenly instead of piling on scene 1
            scene = min(scenes, key=lambda s: per_scene[s.pk])
        per_scene[scene.pk] += 1
        SceneImage.objects.create(
            book=book, lesson=lesson, scene=scene, kind=SceneImage.BOOK, file=rel, page=info["page"],
            caption=cap, alt_text=f"{scene.title} (book page {info['page']})", width=info["width"], height=info["height"],
            context=text[:600], order=per_scene[scene.pk])
        pg = info["page"]
        lo, hi = (scene.source_pages.split("-") + [""])[:2] if scene.source_pages else ("", "")
        if not lo:
            scene.source_pages = str(pg)
        else:
            a, b = int(lo), int(hi or lo)
            scene.source_pages = f"{min(a, pg)}-{max(b, pg)}" if (min(a, pg) != max(b, pg)) else str(pg)
        scene.save(update_fields=["source_pages"])
        n += 1
    return n


def reassign(lesson):
    """Pictures of a lesson that lost their scene (after a regeneration / scene delete) go to the best matching scene."""
    orphans = list(lesson.pictures.filter(scene__isnull=True))
    scenes = list(lesson.scenes.all())
    if not orphans or not scenes:
        return 0
    counts = Counter(p.scene_id for p in lesson.pictures.filter(scene__isnull=False))
    for pic in orphans:
        pw, cw = _words(pic.context), _words(pic.caption)
        best = max(scenes, key=lambda s: (_scene_score(s, pw, cw), -counts[s.pk]))
        if _scene_score(best, pw, cw) == 0:
            best = min(scenes, key=lambda s: counts[s.pk])
        counts[best.pk] += 1
        pic.scene = best
        pic.order = counts[best.pk]
        pic.save(update_fields=["scene", "order"])
        if pic.page and not best.source_pages:
            best.source_pages = str(pic.page)
            best.save(update_fields=["source_pages"])
    return len(orphans)
