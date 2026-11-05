from .services import analytics


def roles(request):
    u = request.user
    if not u.is_authenticated:
        return {}
    teacher = u.is_staff or u.groups.filter(name__in=["Teacher", "Reviewer"]).exists()
    guardian = (not teacher) and u.groups.filter(name="Guardian").exists()
    ctx = {"teacher": teacher, "guardian": guardian}
    if not teacher and not guardian:
        ctx["pending_count"] = analytics.pending_count(u)     # red badge on the bell
    return ctx
