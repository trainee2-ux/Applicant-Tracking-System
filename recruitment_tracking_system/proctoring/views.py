import json
import logging

from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET

# pyrefly: ignore [missing-import]
from .models import ProctoringSession, ProctoringViolationLog, ProctoringSnapshot

logger = logging.getLogger(__name__)

MAX_SNAPSHOT_SIZE = 2 * 1024 * 1024  # 2 MB base64 limit


def _get_client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/proctor/start/
# Called by assessment_form / evaluation page on load to create a session.
# ─────────────────────────────────────────────────────────────────────────────
@csrf_exempt
@require_POST
def proctor_start_view(request):
    try:
        body = json.loads(request.body or "{}")
    except Exception:
        body = {}

    context = body.get("context", "assessment")
    reference_id = str(body.get("reference_id", ""))[:200]
    candidate_name = str(body.get("candidate_name", ""))[:200]
    candidate_email = str(body.get("candidate_email", ""))[:200]
    max_warnings = int(body.get("max_warnings", 3))

    session = ProctoringSession.objects.create(
        context=context,
        reference_id=reference_id,
        candidate_name=candidate_name,
        candidate_email=candidate_email,
        max_warnings=max(1, min(max_warnings, 20)),
        ip_address=_get_client_ip(request) or None,
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
    )

    return JsonResponse({
        "ok": True,
        "session_token": str(session.session_token),
        "max_warnings": session.max_warnings,
    })


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/proctor/violation/
# Called by proctor.js whenever a behavioral violation is detected.
# ─────────────────────────────────────────────────────────────────────────────
@csrf_exempt
@require_POST
def proctor_violation_view(request):
    try:
        body = json.loads(request.body or "{}")
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    session_token = body.get("session_token", "")
    violation_type = body.get("violation_type", "unknown")
    meta = body.get("meta", {})

    if not session_token:
        return JsonResponse({"ok": False, "error": "Missing session_token"}, status=400)

    try:
        session = ProctoringSession.objects.get(session_token=session_token)
    except ProctoringSession.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Session not found"}, status=404)

    if session.status == "terminated":
        return JsonResponse({
            "ok": True,
            "terminated": True,
            "warnings_count": session.warnings_count,
            "max_warnings": session.max_warnings,
        })

    # Only log recognised violation types
    known_types = {v[0] for v in ProctoringViolationLog.VIOLATION_TYPES}
    if violation_type not in known_types:
        violation_type = "unknown"

    ProctoringViolationLog.objects.create(
        session=session,
        violation_type=violation_type,
        meta=meta if isinstance(meta, dict) else {},
    )

    session.warnings_count += 1
    terminated = session.warnings_count >= session.max_warnings

    if terminated:
        session.status = "terminated"
        session.ended_at = timezone.now()

    session.save(update_fields=["warnings_count", "status", "ended_at"])

    return JsonResponse({
        "ok": True,
        "terminated": terminated,
        "warnings_count": session.warnings_count,
        "max_warnings": session.max_warnings,
    })


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/proctor/snapshot/
# Receives a base64 webcam snapshot; stores it linked to the session.
# ─────────────────────────────────────────────────────────────────────────────
@csrf_exempt
@require_POST
def proctor_snapshot_view(request):
    try:
        body = json.loads(request.body or "{}")
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    session_token = body.get("session_token", "")
    image_data = body.get("image_data", "")

    if not session_token:
        return JsonResponse({"ok": False, "error": "Missing session_token"}, status=400)

    if len(image_data) > MAX_SNAPSHOT_SIZE:
        return JsonResponse({"ok": False, "error": "Snapshot too large"}, status=413)

    try:
        session = ProctoringSession.objects.get(session_token=session_token)
    except ProctoringSession.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Session not found"}, status=404)

    if session.status == "terminated":
        return JsonResponse({"ok": True, "terminated": True})

    ProctoringSnapshot.objects.create(
        session=session,
        image_data=image_data,
        face_count=-1,  # ML face detection not enabled; -1 = not analysed
        flagged=False,
    )

    return JsonResponse({"ok": True, "terminated": False})


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/proctor/complete/
# Called when candidate submits the form to mark session as completed.
# ─────────────────────────────────────────────────────────────────────────────
@csrf_exempt
@require_POST
def proctor_complete_view(request):
    try:
        body = json.loads(request.body or "{}")
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    session_token = body.get("session_token", "")
    if not session_token:
        return JsonResponse({"ok": False, "error": "Missing session_token"}, status=400)

    try:
        session = ProctoringSession.objects.get(session_token=session_token)
    except ProctoringSession.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Session not found"}, status=404)

    if session.status == "active":
        session.status = "completed"
        session.ended_at = timezone.now()
        session.save(update_fields=["status", "ended_at"])

    return JsonResponse({"ok": True, "status": session.status})


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/proctor/status/<session_token>/
# HR/Admin polling endpoint to check live session status.
# ─────────────────────────────────────────────────────────────────────────────
@require_GET
def proctor_status_view(request, session_token):
    try:
        session = ProctoringSession.objects.prefetch_related("violations").get(session_token=session_token)
    except ProctoringSession.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Session not found"}, status=404)

    violations = [
        {
            "type": v.violation_type,
            "timestamp": v.timestamp.isoformat(),
        }
        for v in session.violations.all()[:50]
    ]

    return JsonResponse({
        "ok": True,
        "status": session.status,
        "warnings_count": session.warnings_count,
        "max_warnings": session.max_warnings,
        "candidate_name": session.candidate_name,
        "candidate_email": session.candidate_email,
        "context": session.context,
        "started_at": session.started_at.isoformat(),
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "violations": violations,
        "snapshot_count": session.snapshots.count(),
    })


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/proctor/dashboard/
# HR / Admin dashboard listing all proctoring sessions with detailed timelines
# ─────────────────────────────────────────────────────────────────────────────
def proctoring_dashboard_view(request):
    # Only allow authenticated staff/admin users
    if not request.user.is_authenticated or not request.user.is_staff:
        # If not authenticated, we can redirect or show unauthorized.
        # Let's fallback to allowing it in dev if needed, or redirecting to login.
        from django.shortcuts import redirect
        return redirect("login")

    sessions = ProctoringSession.objects.all().order_by("-started_at")
    active_count = sessions.filter(status="active").count()
    terminated_count = sessions.filter(status="terminated").count()

    selected_token = request.GET.get("session")
    selected_session = None
    violations = []
    snapshots = []

    if selected_token:
        try:
            selected_session = ProctoringSession.objects.get(session_token=selected_token)
            violations = selected_session.violations.all().order_by("timestamp")
            snapshots = selected_session.snapshots.all().order_by("timestamp")
        except ProctoringSession.DoesNotExist:
            pass

    return render(
        request,
        "proctoring/session_list.html",
        {
            "sessions": sessions,
            "selected_session": selected_session,
            "violations": violations,
            "snapshots": snapshots,
            "active_count": active_count,
            "terminated_count": terminated_count,
        },
    )

