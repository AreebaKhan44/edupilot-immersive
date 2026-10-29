def roles(request):
    u = request.user
    if not u.is_authenticated:
        return {}
    return {"teacher": u.is_staff or u.groups.filter(name__in=["Teacher", "Reviewer"]).exists()}
