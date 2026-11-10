from pathlib import Path

from .services import analytics

_STATIC = Path(__file__).resolve().parent / "static" / "immersive"


def asset_version(request):
    """?v=<newest mtime of our own js/css>: browsers (student AND teacher) always load the current viewer.js / voice.js / css."""
    try:
        v = max(int(f.stat().st_mtime) for d in ("js", "css") for f in (_STATIC / d).glob("*") if f.is_file())
    except (OSError, ValueError):
        v = 1
    return {"asset_v": v}


def roles(request):
    u = request.user
    if not u.is_authenticated:
        return {}
    from . import roles
    teacher = roles.is_teacher(u)
    guardian = (not teacher) and u.groups.filter(name="Guardian").exists()
    ctx = {"teacher": teacher, "guardian": guardian, "supervisor": roles.can_use_lab(u) and not teacher,
           "reviewer_role": roles.is_reviewer(u)}
    if not teacher and not guardian:
        ctx["pending_count"] = analytics.pending_count(u)     # red badge on the bell
    return ctx
