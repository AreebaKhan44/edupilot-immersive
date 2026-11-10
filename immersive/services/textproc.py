"""Book text -> chapters, sentences, keywords. Pure Python, works offline, English / Roman Urdu / Urdu."""
import math
import re
from collections import Counter

STOP = set("""a an the is are was were be been being of in on at to for from by with and or but if then than that this these
those it its as into about over under between during he she they we you i his her their our your not no yes can could
should would may might will shall do does did has have had also such more most other some any each which who whom what
when where why how very so up out there here only just like many much used use using called known one two three because through everything based made make makes however therefore while after before often usually every
hai hain tha thi the ka ki ke ko se mein me par aur ya yeh ye woh wo jo kya hota hoti hote hota hain kiya gaya gayi
اور کے کی کا کو سے میں پر یہ وہ ہے ہیں تھا تھی تھے جو کہ بھی ہو ہوتا ہوتی ہوتے""".split())

WORD_RE = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
SENT_SPLIT = re.compile(r"(?<=[.!?۔؟])\s+|\n\s*\n|\n(?=\s*[-•*]\s)")
HEAD_RE = re.compile(
    r"^\s*(?:#{1,3}\s+.+|(?:chapter|unit|lesson|section|باب|سبق)\s+(?:\d+|[ivxlc]+)\b.*)$",
    re.IGNORECASE | re.MULTILINE,
)


def clean(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def trim(s, n):
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def short_title(title):
    t = re.sub(r"^(?:chapter|unit|lesson|section|باب|سبق)\s+(?:\d+|[ivxlc]+)\s*[:.\-–]?\s*", "", title.strip(), flags=re.I)
    return t or title


INSTRUCTION_RE = re.compile(
    r"^(?:to\s+\w+|ask|draw|show|explain|discuss|tell|help|write|bring|let|make sure|take|encourage|divide|distribute|hold up|point|"
    r"perform|introduce|recite|sing|teach|revise|display|demonstrate|teaching|learning|key words?|method|resources?|note|task|cw|hw|"
    r"answers?|worksheet|activity|activities|students?\s+(?:should|will|can)|children\s+(?:should|will|can))\b", re.I)


JUNK_RE = re.compile(r"_{3,}|\[[^\]]{1,40}\]|\(\w\)\s|\bMCQs?\b|photocopiable", re.I)


def is_instruction(sentence):
    """Teacher-directed lines or worksheet leftovers of a teaching guide ("Draw a plant on the chalkboard",
    "(g) Pine trees have ____ [thin leaves]") - poor material for student-facing scenes and quiz questions."""
    return bool(INSTRUCTION_RE.match(sentence.strip()) or JUNK_RE.search(sentence))


def _reflow(text):
    """Hard-wrapped PDF text: a SHORT line ends a list item/sentence, a full-width line continues into the next one."""
    lines, out = text.split("\n"), []
    for i, ln in enumerate(lines):
        out.append(ln)
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if ln.strip() and nxt.strip() and len(ln) < 70 and (ln.rstrip()[-1] in ".!?:؟۔" or nxt.lstrip()[:1].isupper()):
            out.append("")
    return "\n".join(out)


def split_sentences(text):
    out = []
    for p in SENT_SPLIT.split(_reflow(text)):
        p = " ".join(p.split())
        if len(p) >= 25:
            out.append(p)
    return out


def keywords(text, n=10):
    words = [w for w in WORD_RE.findall(text) if w.lower() not in STOP]
    counts = Counter(w.lower() for w in words)
    caps = Counter(w.lower() for w in words if w[0].isupper())
    scored = {w: c * (1 + math.log(len(w))) + 0.5 * caps.get(w, 0) for w, c in counts.items()}
    return [w for w, _ in sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


def rank_sentences(sentences, kws):
    kset = set(kws)

    def score(s):
        ws = [w.lower() for w in WORD_RE.findall(s)]
        if not ws:
            return 0
        hit = sum(1 for w in ws if w in kset)
        length_pen = 1.0 if 40 <= len(s) <= 220 else 0.6
        return (hit / math.sqrt(len(ws))) * length_pen

    return sorted(sentences, key=score, reverse=True)


# ---- real-book chapter detection (teaching guides, textbooks, PDFs) -------------------------------
_TOC_LINE = re.compile(r"(\.{3,}|\s\.\s\.)")
_TOC_NUM_TAIL = re.compile(r"^\s*(?:unit|chapter|lesson|section|باب|سبق)\s+\d+\s*[:.\-–]?\s*\S.*\s\d{1,3}\s*$", re.I)
_MAJOR = re.compile(r"^\s*(?:#{1,2}\s+(?P<md>.+)|(?P<kind>unit|chapter|باب)\s+(?P<num>\d+|[ivxlc]+)\b\s*[:.\-–]?\s*(?P<title>.*))$", re.I)
_MINOR = re.compile(r"^\s*(?:lesson|section|سبق)\s+(?P<num>\d+|[ivxlc]+)\b\s*[:.\-–]?\s*(?P<title>.*)$", re.I)
_PAGE_NO = re.compile(r"^\s*\d{1,3}(\s+\d{1,3})?\s*$")
_BAD_TITLE_START = re.compile(r"^(teaching|learning|objectives?|answers?|note|task|ask|explain|the |a |an |in |to |students?|children)\b", re.I)


def _num(v):
    v = v.lower()
    if v.isdigit():
        return int(v)
    vals, total = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}, 0
    for a, b in zip(v, v[1:] + " "):
        total += -vals[a] if vals.get(b, 0) > vals[a] else vals[a]
    return total


def _is_toc(line):
    return bool(_TOC_LINE.search(line) or _TOC_NUM_TAIL.match(line))


def _toc_titles(lines):
    """{unit number: title} taken from a table of contents (used only to name groups of lessons)."""
    out = {}
    for ln in lines[:400]:
        m = re.match(r"^\s*(?:unit|chapter)\s+(\d+)\s*[:.\-–]?\s*(.+?)[\s.]*\d{0,3}\s*$", ln, re.I)
        if m and _is_toc(ln) or (m and re.search(r"\s\d{1,3}\s*$", ln)):
            t = re.sub(r"[\s.]+\d{0,3}\s*$", "", m.group(2)).strip(" .")
            if t and int(m.group(1)) not in out:
                out[int(m.group(1))] = t
    return out


_ANSWER_START = re.compile(r"^(?:answers?\s+to\s+(?:the\s+)?activit|additional\s+activit|mcqs?\b)", re.I)
_ANSWER_END = re.compile(r"^(?:unit\s+\d+\s*:|date\s*:|lesson plan|name\s*:|photocopiable|teaching objectives)", re.I)


def _drop_noise(body_lines, repeated):
    out, skipping = [], False
    for ln in body_lines:
        t = ln.strip()
        if _ANSWER_START.match(t):
            skipping = True
        elif skipping and _ANSWER_END.match(t):
            skipping = False
        if skipping:
            continue
        if not t or _PAGE_NO.match(t) or t in repeated:
            out.append("") if out and out[-1] != "" else None
            continue
        out.append(t)
    return clean("\n".join(out))


def split_chapters(text, default_title="Lesson", max_chapters=40):
    """Return [(title, body)].

    Handles pasted text ("Chapter 1: ...") *and* real book/PDF text: table-of-contents lines are ignored, page
    numbers / repeated page headers are stripped, "UNIT 1 \n Title" headings are merged, repeated headings of
    the same unit are folded into one topic, and "Lesson N" runs are grouped into their unit.
    """
    text = clean(text)
    lines = text.split("\n")
    toc = _toc_titles(lines)
    freq = Counter(l.strip() for l in lines if 3 <= len(l.strip()) <= 60)
    repeated = {k for k, c in freq.items() if c >= 4 and not _MAJOR.match(k) and not _MINOR.match(k)}

    def heading_at(i, rx):
        ln = lines[i]
        if len(ln) > 90 or _is_toc(ln):
            return None
        m = rx.match(ln)
        return m

    majors, minors = [], []
    for i in range(len(lines)):
        m = heading_at(i, _MAJOR)
        if m:
            if m.group("md"):
                majors.append((i, None, m.group("md").strip(), True, ""))
            else:
                n, title = _num(m.group("num")), (m.group("title") or "").strip()
                if not title:  # "UNIT 1" followed by its title line
                    for j in range(i + 1, min(i + 4, len(lines))):
                        nxt = lines[j].strip()
                        if nxt:
                            if len(nxt) <= 60 and not nxt.endswith((".", ":", "?")) and not _BAD_TITLE_START.match(nxt) \
                                    and not _PAGE_NO.match(nxt) and not _MAJOR.match(nxt):
                                title = nxt
                            break
                title = re.sub(r"\s+(worksheet|test|assessment)\b.*$", "", title, flags=re.I).strip()
                if n in toc and (not title or len(toc[n]) > len(title)):
                    title = toc[n]  # the table of contents gives the full, correct unit name
                majors.append((i, n, title, False, m.group("kind").title()))
            continue
        m = heading_at(i, _MINOR)
        if m:
            minors.append((i, _num(m.group("num")), (m.group("title") or "").strip()))

    def build(sections):
        """sections: [(title, start_line, end_line)] -> [(title, body)] merging same titles."""
        merged = {}
        order = []
        for title, a, b in sections:
            body = _drop_noise(lines[a:b], repeated)
            if title not in merged:
                merged[title] = ""
                order.append(title)
            merged[title] += "\n\n" + body
        out = []
        for t in order:
            body = clean(merged[t])
            if len(body) >= 80:
                out.append((trim(t, 120), body))
        return out

    chapters = []
    # --- 1) major headings (unit / chapter / # heading). Same unit number repeated => same topic.
    if majors:
        secs, cur_n = [], object()
        starts = []
        for idx, (i, n, title, is_md, kind) in enumerate(majors):
            if is_md or n != cur_n:
                starts.append((i, n, title, is_md, kind))
                cur_n = n
        if len(starts) >= 2 or (len(starts) == 1 and starts[0][0] < 5):
            for k, (i, n, title, is_md, kind) in enumerate(starts):
                end = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
                label = title if is_md else (f"{kind} {n}: {title}" if title else f"{kind} {n}")
                secs.append((label, i + 1, end))
            chapters = build(secs)
    # --- 2) "Lesson N" headings; a restart of the numbering begins a new unit group
    if not chapters and len(minors) >= 2:
        groups, cur = [], []
        last = 0
        for i, n, t in minors:
            if cur and n <= last:
                groups.append(cur)
                cur = []
            cur.append((i, n, t))
            last = n
        if cur:
            groups.append(cur)
        secs = []
        if len(groups) >= 2:
            for gi, g in enumerate(groups, 1):
                title = f"Unit {gi}: {toc[gi]}" if gi in toc else f"Unit {gi}: {g[0][2] or 'Topic'}"
                end = groups[gi][0][0] if gi < len(groups) else len(lines)
                secs.append((title, g[0][0], end))
        else:
            for k, (i, n, t) in enumerate(minors):
                end = minors[k + 1][0] if k + 1 < len(minors) else len(lines)
                secs.append((f"Lesson {n}: {t}" if t else f"Lesson {n}", i + 1, end))
        chapters = build(secs)
    # --- 3) fallback: chunks
    if not chapters:
        body = _drop_noise([l for l in lines if not _is_toc(l)], repeated)
        if len(body) <= 4000:
            chapters = [(default_title, body)]
        else:
            paras, buf, parts = [p for p in body.split("\n\n") if p.strip()], "", []
            for p in paras:
                if len(buf) + len(p) > 3000 and buf:
                    parts.append(buf)
                    buf = ""
                buf += p + "\n\n"
            if buf.strip():
                parts.append(buf)
            chapters = [(f"{default_title} – Part {i}", b.strip()) for i, b in enumerate(parts, 1)]
    return chapters[:max_chapters]
