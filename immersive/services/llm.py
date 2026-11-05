"""Optional LLM storyboard drafting through the Anthropic Messages API (stdlib only).

Enabled only when ANTHROPIC_API_KEY is set. Output is validated; on any problem we return None and the
offline generator is used instead. The model is told to use ONLY the supplied text (curriculum grounding).
"""
import json
import os
import urllib.request

from django.conf import settings

API_URL = "https://api.anthropic.com/v1/messages"

PROMPT = """You are an instructional designer. Turn the BOOK TEXT into an immersive 3D lesson plan.
Use ONLY facts found in the BOOK TEXT. Write narration in the same language as the text.
Return ONLY valid JSON (no markdown) with this shape:
{{"objective": str,
 "scenes": [{{"title": str, "narration": str (60-120 words, spoken style), "key_points": [str, str, str],
   "visual": {{"type": one of {types}, "labels": [up to 5 short key terms]}} }}] (3 to {max_scenes} scenes),
 "quiz": [{{"text": str, "options": [4 strings], "answer_index": 0-3, "explanation": str}}] (4 to 6 questions)}}

LESSON TITLE: {title}
BOOK TEXT:
{text}
"""


def _validate(plan, types, palette):
    if not isinstance(plan, dict) or not isinstance(plan.get("scenes"), list) or not plan["scenes"]:
        return None
    scenes = []
    for s in plan["scenes"][: getattr(settings, "EDUPILOT_MAX_SCENES", 6)]:
        if not isinstance(s, dict) or not s.get("title") or not s.get("narration"):
            return None
        v = s.get("visual") or {}
        vtype = v.get("type") if v.get("type") in types else "cluster"
        scenes.append({
            "title": str(s["title"])[:200], "narration": str(s["narration"])[:1500],
            "key_points": [str(k)[:160] for k in (s.get("key_points") or [])][:4],
            "visual": {"type": vtype, "color": palette[vtype], "labels": [str(x)[:30] for x in (v.get("labels") or [])][:5]},
        })
    quiz = []
    for q in plan.get("quiz") or []:
        try:
            opts = [str(o)[:120] for o in q["options"]]
            ai = int(q["answer_index"])
            if len(opts) >= 2 and 0 <= ai < len(opts):
                quiz.append({"text": str(q["text"]), "options": opts, "answer_index": ai,
                             "explanation": str(q.get("explanation", ""))})
        except (KeyError, TypeError, ValueError):
            continue
    return {"objective": str(plan.get("objective", ""))[:600], "scenes": scenes, "quiz": quiz}


def llm_plan(title, text, language, types, palette):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    body = json.dumps({
        "model": getattr(settings, "EDUPILOT_LLM_MODEL", "claude-sonnet-5-5"),
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": PROMPT.format(
            types=json.dumps(types), max_scenes=getattr(settings, "EDUPILOT_MAX_SCENES", 6),
            title=title, text=text[:12000])}],
    }).encode()
    req = urllib.request.Request(API_URL, data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read())
    raw = "".join(b.get("text", "") for b in data.get("content", []))
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < 0:
        return None
    plan = _validate(json.loads(raw[start:end + 1]), types, palette)
    if plan:
        plan["title"] = title
    return plan
