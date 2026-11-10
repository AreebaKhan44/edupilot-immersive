"""Views for the features of EduPilot_Immersive_Learning_Roadmap.docx that the first version did not have:

  scene pictures / GLB models, content passport, curriculum mappings (separate review per pathway), curriculum
  versions with change register, content issues, market scoring + country readiness, pilot scorecard, PDF report,
  offline lesson pack + service worker.
"""
import io
import re
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import roles
from .forms import IssueForm, MappingForm, NewCurriculumVersionForm, ScenePictureForm
from .models import (ClassSession, ContentIssue, Curriculum, CurriculumChange, CurriculumMapping, Lesson, MarketAssessment,
                     Outcome, OutcomeProgress, QuizAttempt, SceneImage, Submission)
from .services import outcomes, pipeline
from .views import get_lesson_for_edit, get_lesson_for_view, is_reviewer, is_teacher


def _reviewer_required(user):
    if not is_reviewer(user):
        raise PermissionDenied


# ---------------------------------------------------------------- scene pictures / models
@require_POST
@login_required
def scene_picture(request, pk):
    """Teacher: add a picture / GLB model to a scene, redraw the generated picture, or delete a picture."""
    lesson = get_lesson_for_edit(request, pk)
    action = request.POST.get("action", "add")
    root = Path(settings.MEDIA_ROOT)
    if action == "add":
        form = ScenePictureForm(request.POST, request.FILES)
        if not form.is_valid():
            messages.error(request, "; ".join(e for errs in form.errors.values() for e in errs))
            return redirect(lesson)
        scene = get_object_or_404(lesson.scenes, pk=form.cleaned_data["scene"])
        img, model = form.cleaned_data.get("image"), form.cleaned_data.get("model")
        if img:
            from PIL import Image
            try:
                pil = Image.open(img)
                pil.load()
            except Exception:  # noqa: BLE001
                messages.error(request, "That file is not a readable picture.")
                return redirect(lesson)
            if max(pil.size) > 1600:
                pil.thumbnail((1600, 1600))
            d = root / "books" / f"book_{lesson.book_id}"
            d.mkdir(parents=True, exist_ok=True)
            n = lesson.pictures.count() + 1
            name = f"upload_l{lesson.pk}_{n}_{int(timezone.now().timestamp())}.png"
            pil.convert("RGBA").save(d / name, "PNG")
            cap = form.cleaned_data.get("caption", "")
            SceneImage.objects.create(book=lesson.book, lesson=lesson, scene=scene, kind=SceneImage.UPLOAD,
                                      file=f"books/book_{lesson.book_id}/{name}", caption=cap, alt_text=cap or scene.title,
                                      width=pil.size[0], height=pil.size[1], order=n)
            messages.success(request, f"Picture added to scene {scene.order}.")
        if model:
            d = root / "scenes" / f"lesson_{lesson.pk}"
            d.mkdir(parents=True, exist_ok=True)
            name = f"model_{scene.order}_{int(timezone.now().timestamp())}.glb"
            with open(d / name, "wb") as fh:
                for chunk in model.chunks():
                    fh.write(chunk)
            scene.model_file = f"scenes/lesson_{lesson.pk}/{name}"
            scene.save(update_fields=["model_file"])
            messages.success(request, f"3D model added to scene {scene.order}; the viewer shows it instead of the built-in shape.")
        pipeline.generate_images(lesson)
    elif action == "delete":
        pic = get_object_or_404(lesson.pictures, pk=request.POST.get("picture"))
        try:
            (root / pic.file).unlink()
        except OSError:
            pass
        pic.delete()
        pipeline.generate_scene_pictures(lesson)        # a scene never stays without a picture
        pipeline.generate_images(lesson)
        messages.success(request, "Picture removed.")
    elif action == "remove_model":
        scene = get_object_or_404(lesson.scenes, pk=request.POST.get("scene"))
        scene.model_file = ""
        scene.save(update_fields=["model_file"])
        messages.success(request, "3D model removed.")
    elif action == "redraw":
        pipeline.refresh_pictures(lesson)
        messages.success(request, "Generated pictures were redrawn from the current scene text.")
    else:
        raise Http404
    return redirect(lesson)


# ---------------------------------------------------------------- content passport (s.8)
@login_required
def lesson_passport(request, pk):
    lesson = get_lesson_for_view(request, pk)
    scenes = list(lesson.scenes.prefetch_related("pictures"))
    checks = [
        ("Sources recorded", bool(lesson.sources.strip())), ("Licence / rights recorded", bool(lesson.licence.strip())),
        ("Mapped to a curriculum outcome", lesson.outcome_id is not None or lesson.mappings.exists()),
        ("Every scene has a picture", all(sc.pictures.exists() for sc in scenes) and bool(scenes)),
        ("Limitations stated", bool(lesson.limitations.strip())),
        ("Accessibility route (screen-based) written", bool(lesson.alternative_route.strip())),
        ("Approved by a reviewer other than the creator", lesson.approved_by_id is not None and lesson.approved_by_id != lesson.book.owner_id),
        ("No open critical issue", not lesson.issues.filter(status="open", severity="critical").exists()),
    ]
    return render(request, "immersive/passport.html", {
        "lesson": lesson, "scenes": scenes, "checks": checks, "mappings": lesson.mappings.select_related("outcome__curriculum", "reviewed_by"),
        "versions": lesson.versions.all(), "issues": lesson.issues.all()[:10],
        "outcome_choices": Outcome.objects.select_related("curriculum")})


# ---------------------------------------------------------------- curriculum mappings (s.4): every pathway reviewed separately
@require_POST
@login_required
def mapping_action(request, pk):
    lesson = get_lesson_for_view(request, pk)
    action = request.POST.get("action")
    if action == "propose":
        if lesson.book.owner_id != request.user.id and not request.user.is_staff:
            raise PermissionDenied
        form = MappingForm(request.POST)
        if form.is_valid():
            m, created = CurriculumMapping.objects.get_or_create(
                lesson=lesson, outcome=form.cleaned_data["outcome"], defaults={"proposed_by": request.user, "note": form.cleaned_data["note"]})
            messages.success(request, "Mapping proposed. A reviewer must approve it." if created else "That outcome is already mapped.")
            outcomes.log(request.user, "mapping.proposed", f"lesson {lesson.pk} -> {m.outcome}")
        else:
            messages.error(request, "Choose an outcome.")
    elif action in ("approve", "reject"):
        _reviewer_required(request.user)
        m = get_object_or_404(lesson.mappings, pk=request.POST.get("mapping"))
        if m.proposed_by_id == request.user.id:
            messages.error(request, "A mapping must be approved by someone other than the person who proposed it.")
            return redirect(lesson)
        m.status = CurriculumMapping.APPROVED if action == "approve" else CurriculumMapping.REJECTED
        m.reviewed_by, m.reviewed_at = request.user, timezone.now()
        m.save()
        if action == "approve" and lesson.outcome_id is None:
            lesson.outcome = m.outcome
            lesson.save(update_fields=["outcome"])
        outcomes.log(request.user, f"mapping.{action}", f"lesson {lesson.pk} -> {m.outcome}")
        messages.success(request, f"Mapping {m.get_status_display().lower()}.")
    else:
        raise Http404
    return redirect(lesson)


# ---------------------------------------------------------------- curriculum versions (s.4)
@require_POST
@login_required
def curriculum_new_version(request):
    """Create a new version of a curriculum: outcomes are copied, the change is registered (reason, reviewer, impact) and
    lessons linked to the old version are flagged for review. Existing cohorts / sessions keep the version they were given."""
    _reviewer_required(request.user)
    form = NewCurriculumVersionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Fill curriculum, new version and the reason for the change.")
        return redirect("curriculum_home")
    old, ver = form.cleaned_data["curriculum"], form.cleaned_data["version"].strip()
    if Curriculum.objects.filter(name=old.name, version=ver).exists():
        messages.error(request, f"{old.name} v{ver} already exists.")
        return redirect("curriculum_home")
    with transaction.atomic():
        new = Curriculum.objects.create(name=old.name, country=old.country, version=ver,
                                        effective_from=form.cleaned_data.get("effective_from"), review_owner=request.user)
        for o in old.outcomes.all():
            n = Outcome.objects.create(curriculum=new, subject=o.subject, level=o.level, code=o.code, description=o.description,
                                       expected_evidence=o.expected_evidence)
        affected = list(Lesson.objects.filter(Q(outcome__curriculum=old) | Q(mappings__outcome__curriculum=old)).distinct())
        Lesson.objects.filter(pk__in=[l.pk for l in affected]).update(needs_review=True)
        impact = f"{len(affected)} lesson(s) flagged for review: " + ", ".join(l.title[:40] for l in affected[:8]) if affected else "No lessons were linked to the old version."
        CurriculumChange.objects.create(curriculum=new, previous=old, reason=form.cleaned_data["reason"], reviewer=request.user, impact=impact)
    outcomes.log(request.user, "curriculum.new_version", f"{old.name} v{old.version} -> v{ver}")
    messages.success(request, f"{new} created. {impact}")
    return redirect("curriculum_home")


@require_POST
@login_required
def lesson_adopt_version(request, pk):
    """Teacher decides to move a flagged lesson to the matching outcome of the newest curriculum version (or keep the old mapping)."""
    lesson = get_lesson_for_edit(request, pk)
    if request.POST.get("action") == "adopt" and lesson.outcome_id:
        new = Outcome.objects.filter(code=lesson.outcome.code, curriculum__name=lesson.outcome.curriculum.name).exclude(
            curriculum=lesson.outcome.curriculum).order_by("-curriculum__created").first()
        if new:
            lesson.outcome = new
            messages.success(request, f"Lesson moved to {new.curriculum}.")
        else:
            messages.info(request, "No matching outcome code in a newer version; the old mapping was kept.")
    lesson.needs_review = False
    lesson.save(update_fields=["outcome", "needs_review"])
    outcomes.log(request.user, "lesson.curriculum_reviewed", f"lesson {lesson.pk}")
    return redirect("lesson_design", pk=lesson.pk)


# ---------------------------------------------------------------- content issues (s.8)
@require_POST
@login_required
def issue_action(request, pk):
    lesson = get_lesson_for_view(request, pk)
    action = request.POST.get("action", "report")
    if action == "report":
        if not is_teacher(request.user):
            raise PermissionDenied
        form = IssueForm(request.POST)
        if form.is_valid():
            issue = form.save(commit=False)
            issue.lesson, issue.reported_by = lesson, request.user
            issue.save()
            classes = sorted({s.school_class.name for s in ClassSession.objects.filter(lesson=lesson).select_related("school_class")})
            outcomes.log(request.user, "issue.reported", f"lesson {lesson.pk} [{issue.severity}]")
            messages.success(request, "Issue recorded." + (f" Classes that used this lesson: {', '.join(classes)}." if classes else ""))
    elif action == "fix":
        if lesson.book.owner_id != request.user.id and not is_reviewer(request.user):
            raise PermissionDenied
        issue = get_object_or_404(lesson.issues, pk=request.POST.get("issue"))
        issue.status, issue.resolved_at = ContentIssue.FIXED, timezone.now()
        issue.save()
        outcomes.log(request.user, "issue.fixed", f"lesson {lesson.pk}")
        messages.success(request, "Issue marked as fixed.")
    return redirect(lesson)


# ---------------------------------------------------------------- market scoring + country readiness (s.3, s.14)
@login_required
def markets(request):
    _reviewer_required(request.user)
    if request.method == "POST":
        m = get_object_or_404(MarketAssessment, pk=request.POST.get("market"))
        scores = {}
        for key, _label, _w in MarketAssessment.CRITERIA:
            raw = request.POST.get(f"score_{key}", "").strip()
            if raw.isdigit() and 1 <= int(raw) <= 5:
                scores[key] = {"score": int(raw), "evidence": request.POST.get(f"evidence_{key}", "")[:300],
                               "confidence": request.POST.get(f"conf_{key}", "low") if request.POST.get(f"conf_{key}") in ("low", "medium", "high") else "low"}
        m.scores = scores
        items = {i: bool(request.POST.get(f"ready_{n}")) for n, i in enumerate(MarketAssessment.READINESS_ITEMS)}
        m.readiness = {"verification": request.POST.get("verification", "")[:500], "items": items}
        m.save()
        outcomes.log(request.user, "market.updated", m.country)
        messages.success(request, f"{m.country} saved.")
        return redirect("markets")
    rows = []
    for m in MarketAssessment.objects.all():
        crit = [{"key": k, "label": l, "weight": w, "score": (m.scores.get(k) or {}).get("score"), "evidence": (m.scores.get(k) or {}).get("evidence", ""),
                 "conf": (m.scores.get(k) or {}).get("confidence", "low")} for k, l, w in MarketAssessment.CRITERIA]
        items = [{"n": n, "label": i, "done": bool((m.readiness.get("items") or {}).get(i))} for n, i in enumerate(MarketAssessment.READINESS_ITEMS)]
        rows.append({"m": m, "crit": crit, "items": items, "ready_count": sum(1 for i in items if i["done"])})
    ranked = sorted([r for r in rows if r["m"].weighted_score is not None], key=lambda r: -r["m"].weighted_score)
    return render(request, "immersive/markets.html", {"rows": rows, "ranked": ranked, "n_criteria": len(MarketAssessment.CRITERIA)})


# ---------------------------------------------------------------- pilot scorecard (s.12)
def pilot_metrics(user=None):
    """Roadmap s.12 decision targets, computed from real data. Targets are proposals: agree them before the pilot starts."""
    ended = ClassSession.objects.filter(status=ClassSession.ENDED)
    if user is not None and not user.is_staff:
        ended = ended.filter(school_class__teacher=user)
    n_ended = ended.count()
    n_fail = ended.filter(blocking_failure=True).count()
    delivery = round(100 * (n_ended - n_fail) / n_ended, 1) if n_ended else None
    published = Lesson.objects.filter(status=Lesson.PUBLISHED)
    n_pub = published.count()
    with_route = published.exclude(alternative_route="").count()
    crit_open = ContentIssue.objects.filter(severity="critical", status="open").count()
    teachers = ClassSession.objects.values("school_class__teacher").distinct().count()
    ran = ended.values("school_class__teacher").distinct().count()
    graded = QuizAttempt.objects.filter(marks__isnull=False)
    avg = graded.aggregate(a=Avg("marks"))["a"]
    pct = None
    if graded.exists():
        tot = sum(a.total for a in graded)
        pct = round(100 * sum(a.marks for a in graded) / tot) if tot else None
    target = getattr(settings, "EDUPILOT_PILOT_DELIVERY_TARGET", 95)
    return [
        {"name": "Content quality", "target": "No unresolved critical scientific errors", "value": f"{crit_open} open critical issue(s)",
         "ok": crit_open == 0},
        {"name": "Technical delivery", "target": f"At least {target}% of sessions complete without a blocking failure",
         "value": f"{delivery}% ({n_ended - n_fail}/{n_ended} sessions)" if n_ended else "no ended sessions yet", "ok": (delivery is not None and delivery >= target) if n_ended else None},
        {"name": "Learning", "target": "No disadvantage on core understanding + evidence of benefit (needs a comparison group - measure outside the app)",
         "value": f"teacher-marked quizzes average {pct}%" if pct is not None else "no marked quizzes yet", "ok": None},
        {"name": "Teacher readiness", "target": "Most teachers can run lessons independently after training",
         "value": f"{ran}/{teachers} teachers ran at least one session" if teachers else "no sessions yet", "ok": (ran * 2 > teachers) if teachers else None},
        {"name": "Accessibility", "target": "Every published lesson has an equivalent screen-based route",
         "value": f"{with_route}/{n_pub} published lessons" if n_pub else "no published lessons", "ok": (with_route == n_pub) if n_pub else None},
        {"name": "Commercial demand", "target": "At least one institution agrees to paid continuation", "value": "record outside the app", "ok": None},
    ]


@login_required
def pilot(request):
    if not is_teacher(request.user):
        raise PermissionDenied
    sessions = ClassSession.objects.filter(status=ClassSession.ENDED, blocking_failure=True).select_related("school_class", "lesson")[:10]
    return render(request, "immersive/pilot.html", {"metrics": pilot_metrics(request.user), "failures": sessions,
                                                    "issues": ContentIssue.objects.filter(status="open").select_related("lesson")[:10]})


# ---------------------------------------------------------------- PDF report (ReportLab, optional)
@login_required
def report_pdf(request):
    if not is_teacher(request.user):
        raise PermissionDenied
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError:
        return HttpResponse("PDF export needs ReportLab: pip install reportlab", status=501, content_type="text/plain")
    prog = OutcomeProgress.objects.all()
    if not request.user.is_staff:
        prog = prog.filter(student__enrolments__school_class__teacher=request.user).distinct()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title="EduPilot report", leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=40)
    st = getSampleStyleSheet()
    story = [Paragraph("EduPilot Immersive - leadership report", st["Title"]),
             Paragraph(timezone.localtime().strftime("Generated %d %b %Y %H:%M"), st["Normal"]), Spacer(1, 14),
             Paragraph("Outcome progress", st["Heading2"])]
    rows = [["Status", "Learners"]] + [[label, str(prog.filter(status=code).count())] for code, label in OutcomeProgress.STATUS]
    story += [_table(Table, TableStyle, colors, rows), Spacer(1, 14), Paragraph("Pilot decision targets", st["Heading2"])]
    rows = [["Measure", "Target", "Now"]] + [[Paragraph(m["name"], st["Normal"]), Paragraph(m["target"], st["Normal"]), Paragraph(m["value"], st["Normal"])]
                                              for m in pilot_metrics(request.user)]
    story += [_table(Table, TableStyle, colors, rows, widths=[110, 230, 175])]
    doc.build(story)
    outcomes.log(request.user, "report.export", "PDF leadership report")
    return HttpResponse(buf.getvalue(), content_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="edupilot-report.pdf"'})


def _table(Table, TableStyle, colors, rows, widths=None):
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3558f0")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d3ea")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("FONTSIZE", (0, 0), (-1, -1), 9)]))
    return t


# ---------------------------------------------------------------- offline (s.7)
@require_GET
@login_required
def lesson_pack(request, pk):
    """List of every URL the viewer needs to run offline (assets, pictures, models, audio, manifest). The service worker caches them."""
    lesson = get_lesson_for_view(request, pk)
    if not lesson.offline_capable:
        return JsonResponse({"error": "This lesson is not marked offline-capable."}, status=403)
    urls = {reverse_static("immersive/js/viewer.js"), reverse_static("immersive/js/voice.js"), reverse_static("immersive/css/app.css"),
            reverse_static("immersive/vendor/three/three.module.js"), reverse_static("immersive/vendor/three/jsm/controls/OrbitControls.js"),
            reverse_static("immersive/vendor/three/jsm/webxr/VRButton.js"), reverse_static("immersive/vendor/three/jsm/loaders/GLTFLoader.js"),
            reverse_static("immersive/vendor/three/jsm/utils/BufferGeometryUtils.js"),
            reverse_static("immersive/fonts/NotoNaskhArabic-Regular.ttf"), reverse_static("immersive/fonts/NotoNaskhArabic-Bold.ttf")}
    from django.urls import reverse
    m = lesson.manifest()
    for sc in m["scenes"]:
        urls.update(i["url"] for i in sc["images"])
        if sc["model"]:
            urls.add(sc["model"])
        urls.add(sc["audio"])
    urls.add(reverse("api_manifest", args=[lesson.pk]))
    urls.add(reverse("viewer", args=[lesson.pk]))
    return JsonResponse({"lesson": lesson.pk, "version": lesson.version, "cache": f"edupilot-lesson-{lesson.pk}-v{lesson.version}", "urls": sorted(urls)})


def reverse_static(path):
    from django.templatetags.static import static
    return static(path)


@require_GET
def service_worker(request):
    """Served from the site root so it can control every page. Caches static files and approved lesson packs."""
    js = (Path(__file__).resolve().parent / "static" / "immersive" / "js" / "sw.js").read_text(encoding="utf-8")
    resp = HttpResponse(js, content_type="application/javascript")
    resp["Service-Worker-Allowed"] = "/"
    resp["Cache-Control"] = "no-cache"
    return resp
