"""Lesson plan generation: text -> scenes (narration, key points, 3D visual spec) + quiz.

Offline heuristic engine always works. If ANTHROPIC_API_KEY is set, llm.llm_plan() is tried first.
Per blueprint s.14: the LLM only drafts; a human reviews before publishing.
"""
import random
import re

from django.conf import settings

from . import diagrams, llm
from .textproc import is_instruction, keywords, rank_sentences, short_title, split_sentences, trim

VISUAL_RULES = {
    "bits": r"\bbits?\b|\bbytes?\b|binary|kilobyte|megabyte|gigabyte|\bkb\b|\bmb\b|\bgb\b|ones and zeros|0s and 1s|ascii|بٹ|بائٹ|بائنری",
    "solar": r"solar system|planet|orbit|\bsun\b|mercury|venus|\bmars\b|jupiter|saturn|neptune|uranus|galaxy|نظام شمسی|سیار|سورج|suraj|sooraj|sayyar",
    "cell": r"\bcells?\b|nucleus|mitochondri|organelle|membrane|cytoplasm|ribosom|خلیہ|khaliya",
    "atom": r"\batoms?\b|electron|proton|neutron|molecule|chemical|element|compound|ایٹم|zarra",
    "circuit": r"circuit|current|voltage|resistor|battery|electric|bulb|ohm|برقی|بجلی|bijli",
    "dna": r"\bdna\b|\bgenes?\b|chromosome|heredit|genetic|helix|جین",
    "geometry": r"triangle|angle|geometry|polygon|circle|\barea\b|volume|cube|pyramid|cylinder|مثلث|zawiya",
}
PALETTE = {"bits": "#20b7c4", "solar": "#f0aa49", "cell": "#11a88b", "atom": "#7a5bf1", "circuit": "#315bde",
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
        visual = pick_visual(gt, kw, i)
        narration = trim(" ".join(g[:4]), 700)
        visual["diagram"] = diagrams.make_spec(stitle, narration, points, visual["labels"], language)
        scenes.append({"title": stitle, "narration": narration, "key_points": points, "visual": visual})
    objective = f"Students will be able to explain the main ideas of “{title}”" + (
        f" – including {', '.join(k.title() for k in all_kw[:3])}." if all_kw else ".")
    plan = {"title": title_full, "objective": objective, "scenes": scenes, "quiz": make_quiz(text), "generator": "offline"}
    plan["lesson_plan"] = build_lesson_plan(title, text, scenes, all_kw, plan["quiz"])
    return plan


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
        for sc in plan["scenes"]:        # LLM plan without a diagram: derive one so every scene can get a picture
            sc["visual"].setdefault("diagram", diagrams.make_spec(sc["title"], sc["narration"], sc.get("key_points", []),
                                                                  sc["visual"].get("labels", []), language))
        kws = keywords(text, 12)
        extra = plan.pop("extra", {})
        lp = build_lesson_plan(short_title(title), text, plan["scenes"], kws, plan["quiz"])
        if extra.get("misconceptions"):
            lp["misconceptions"] = extra["misconceptions"]
        if extra.get("vocabulary"):
            lp["vocabulary"] = extra["vocabulary"]
        plan["lesson_plan"] = lp
        return plan
    return heuristic_plan(title, text, language)


# ---------------------------------------------------------------- lesson plan (roadmap s.5 / s.12)
PHASE_SHARE = [("Introduction", 0.12), ("Prediction", 0.13), ("Guided activity", 0.40), ("Discussion", 0.20), ("Short assessment", 0.15)]


def _definition(term, sentences):
    for s in sentences:
        if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", s, re.IGNORECASE):
            return trim(s, 140)
    return ""


def build_lesson_plan(title, text, scenes, kws, quiz, duration=40):
    """Teacher-ready plan: five phases with minutes, vocabulary, probe questions, rubric and the fall-back route.
    Offline and deterministic. It is a DRAFT: a teacher (and for science a subject reviewer) must check it."""
    title = short_title(title)
    sents = [s for s in split_sentences(text) if not is_instruction(s)]
    names = [sc["title"] for sc in scenes]
    kw = [k.title() for k in kws[:6]]
    first, last = (names[0] if names else title), (names[-1] if names else title)
    kw_txt = ", ".join(kw[:3]) if kw else title
    acts = {
        "Introduction": f"Show the first 3D scene \"{first}\" and its picture. Ask: what do you already know about {title}? "
                        f"Write 2-3 student ideas on the board and state today's objective.",
        "Prediction": f"Before opening the next scenes, ask students to predict: what will we see about {kw_txt}? "
                      f"Students write or say one prediction and one reason.",
        "Guided activity": f"Walk through all {len(scenes)} scenes in the 3D viewer ({' → '.join(names[:6])}). In each scene let students click the "
                           f"labelled parts, read the narration and compare the 3D model with the picture from the book.",
        "Discussion": f"In pairs, students explain {kw_txt} in their own words and check their earlier prediction. "
                      f"Revisit \"{last}\" and ask: what is the most important idea and what example shows it?",
        "Short assessment": f"Students answer the {len(quiz)}-question quiz and one transfer question: apply {kws[0].title() if kws else title} to a new situation. "
                            f"The teacher reviews the answers before marks are released.",
    }
    phases = []
    for name, share in PHASE_SHARE:
        phases.append({"phase": name, "minutes": max(2, round(duration * share)), "activity": acts[name]})
    vocab = [{"term": k.title(), "meaning": _definition(k, sents)} for k in kws[:6] if _definition(k, sents)]
    probes = []
    for i in range(0, min(len(kw) - 1, 6), 2):
        probes.append(f"How is {kw[i]} different from {kw[i + 1]}? Ask students to explain with an example.")
    if kw:
        probes.append(f"A student says \"{kw[0]} is the same in every situation\". When might that not be true? (Check against the book.)")
    rubric = (f"4 Achieved: explains {kw_txt} correctly in own words with an example.\n"
              f"3 Secure: explains most ideas; one small gap or missing example.\n"
              f"2 Developing: names the terms but cannot explain how they connect.\n"
              f"1 Beginning: needs support; revisit the scenes and the picture notes, then reassess.")
    return {
        "phases": phases, "duration": duration, "vocabulary": vocab, "misconceptions": [], "misconception_probes": probes[:4],
        "rubric": rubric, "success_criteria": f"I can explain {kw_txt} in my own words and answer the quiz questions.",
        "assessment_objectives": f"Recall and explain the main ideas of {title}; apply one idea to a new example.",
        "fallback": "No headset or 3D needed: read each scene's narration on any screen or printout, label the scene picture in the notebook, "
                    "discuss in pairs, then answer the quiz. Every learner works towards the same objective.",
        "draft_note": "Auto-generated draft. A teacher must check it against the book before publishing (probe questions are prompts, not verified misconceptions).",
    }
