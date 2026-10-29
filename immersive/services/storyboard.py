"""Lesson plan generation: text -> scenes (narration, key points, 3D visual spec) + quiz.

Offline heuristic engine always works. If ANTHROPIC_API_KEY is set, llm.llm_plan() is tried first.
Per blueprint s.14: the LLM only drafts; a human reviews before publishing.
"""
import random
import re

from django.conf import settings

from . import llm
from .textproc import is_instruction, keywords, rank_sentences, short_title, split_sentences, trim

VISUAL_RULES = {
    "solar": r"solar system|planet|orbit|\bsun\b|mercury|venus|\bmars\b|jupiter|saturn|neptune|uranus|galaxy|نظام شمسی|سیار|سورج|suraj|sooraj|sayyar",
    "cell": r"\bcells?\b|nucleus|mitochondri|organelle|membrane|cytoplasm|ribosom|خلیہ|khaliya",
    "atom": r"\batoms?\b|electron|proton|neutron|molecule|chemical|element|compound|ایٹم|zarra",
    "circuit": r"circuit|current|voltage|resistor|battery|electric|bulb|ohm|برقی|بجلی|bijli",
    "dna": r"\bdna\b|\bgenes?\b|chromosome|heredit|genetic|helix|جین",
    "geometry": r"triangle|angle|geometry|polygon|circle|\barea\b|volume|cube|pyramid|cylinder|مثلث|zawiya",
}
PALETTE = {"solar": "#f0aa49", "cell": "#11a88b", "atom": "#7a5bf1", "circuit": "#315bde",
           "dna": "#d9467a", "geometry": "#20b7c4", "cluster": "#5579ff"}
VISUAL_KEYS = list(PALETTE)


def pick_visual(text, kws, index=0):
    low = text.lower()
    scores = {k: len(re.findall(rx, low)) for k, rx in VISUAL_RULES.items()}
    best = max(scores, key=scores.get)
    vtype = best if scores[best] > 0 else "cluster"
    return {"type": vtype, "color": PALETTE[vtype], "labels": [k.title() for k in kws[:5]]}


def _group(items, n):
    n = max(1, min(n, len(items)))
    size, extra, out, i = len(items) // n, len(items) % n, [], 0
    for g in range(n):
        step = size + (1 if g < extra else 0)
        out.append(items[i:i + step])
        i += step
    return [g for g in out if g]


def make_quiz(text, max_q=5):
    sents = [s for s in split_sentences(text) if 40 <= len(s) <= 240 and not is_instruction(s)]
    kws = keywords(text, 30)
    if len(kws) < 4:
        return []
    questions, used = [], set()
    for s in sents:
        if len(questions) >= max_q:
            break
        for k in kws:
            if k in used:
                continue
            m = re.search(r"(?<!\w)" + re.escape(k) + r"(?!\w)", s, re.IGNORECASE)
            if not m:
                continue
            rng = random.Random(len(s) * 31 + len(k))
            pool = [w for w in kws if w != k and not re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", s, re.I)]
            if len(pool) < 3:
                continue
            opts = rng.sample(pool, 3) + [k]
            rng.shuffle(opts)
            used.add(k)
            questions.append({
                "text": "Fill in the blank: " + s[:m.start()] + "_____" + s[m.end():],
                "options": [o.title() for o in opts], "answer_index": opts.index(k),
                "explanation": s,
            })
            break
    return questions


def heuristic_plan(title, text, language="en"):
    sents = split_sentences(text) or [" ".join(text.split())[:300]]
    facts = [s for s in sents if not is_instruction(s)]
    if len(facts) >= 4:     # teaching guides: keep the subject content, drop "Draw X on the chalkboard" lines
        sents = facts
    max_scenes = getattr(settings, "EDUPILOT_MAX_SCENES", 6)
    groups = _group(sents, max(1, round(len(sents) / 3)) if len(sents) > 3 else 1)
    groups = _group(sents, min(len(groups), max_scenes))
    all_kw = keywords(text, 12)
    title_full, title = title, short_title(title)
    scenes = []
    for i, g in enumerate(groups):
        gt = " ".join(g)
        kw = keywords(gt, 6) or all_kw[:6]
        ranked = rank_sentences(g, kw)
        points = [trim(s, 130) for s in ranked[:3]]
        if i == 0:
            stitle = trim(f"Overview: {title}", 80)
        elif len(kw) >= 2:
            stitle = f"{kw[0].title()} & {kw[1].title()}"
        else:
            stitle = f"{title} – {i + 1}"
        scenes.append({"title": stitle, "narration": trim(" ".join(g[:4]), 700),
                       "key_points": points, "visual": pick_visual(gt, kw, i)})
    objective = f"Students will be able to explain the main ideas of “{title}”" + (
        f" – including {', '.join(k.title() for k in all_kw[:3])}." if all_kw else ".")
    return {"title": title_full, "objective": objective, "scenes": scenes, "quiz": make_quiz(text), "generator": "offline"}


def build_plan(title, text, language="en"):
    plan = None
    try:
        plan = llm.llm_plan(title, text, language, VISUAL_KEYS, PALETTE)
    except Exception:  # never break lesson creation because the LLM failed
        plan = None
    if plan:
        plan.setdefault("quiz", [])
        if not plan["quiz"]:
            plan["quiz"] = make_quiz(text)
        plan["generator"] = "llm"
        return plan
    return heuristic_plan(title, text, language)
