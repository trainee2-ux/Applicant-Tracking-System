import os
import json
from pathlib import Path
import uuid

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.db import models
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.core.files.storage import default_storage

from applicant_tracking.models import InPersonInterview, VideoInterviewSchedule
from app_settings.models import UserMaster
from app_settings.notifications import create_notifications, normalize_recipients
from candidate_management.models import Candidate

from .emotion_service import analyze_video_emotions
from .models import InterviewPanelSchedule, InterviewRecording


def _store_uploaded_video(uploaded_file) -> str:
    """
    Persist uploaded interview videos under MEDIA_ROOT so they can be previewed
    in the web UI. Returns the storage-relative path.
    """

    original_name = (getattr(uploaded_file, "name", "") or "recording.mp4").strip()
    safe_name = os.path.basename(original_name).replace("\\", "_").replace("/", "_")
    key = uuid.uuid4().hex[:12]
    storage_path = f"interview_recordings/{key}_{safe_name}"
    return default_storage.save(storage_path, uploaded_file)


def interview_recording_view(request):
    current_user = _login_user_name(request)
    is_admin = _is_admin_request(request)
    panel_records = _panel_rows(filter_name=current_user, is_admin=is_admin)
    return render(request, "interview_recording/index.html", {"panel_records": panel_records})


def interview_panel_dashboard_view(request):
    edit_id = request.GET.get("edit_id", "").strip()
    edit_record = InterviewPanelSchedule.objects.select_related("candidate").filter(id=edit_id).first() if edit_id else None
    show_form = request.GET.get("create") == "1" or bool(edit_record)
    interviewer_options = _interviewer_options()
    current_user = _login_user_name(request)
    is_admin = _is_admin_request(request)

    if request.method == "POST":
        action = request.POST.get("action", "create_panel").strip()
        record_id = request.POST.get("record_id", "").strip()
        candidate_ref = request.POST.get("candidate", "").strip()
        candidate = Candidate.objects.filter(candidate_id=candidate_ref).first() or Candidate.objects.filter(full_name=candidate_ref).first()
        payload = {
            "interviewers": request.POST.get("interviewers", "").strip(),
            "date": request.POST.get("date", "").strip(),
            "time": request.POST.get("time", "").strip(),
            "mode": request.POST.get("mode", "").strip(),
            "video_link": request.POST.get("video_link", "").strip(),
        }
        required = [candidate, payload["interviewers"], payload["date"], payload["time"], payload["mode"]]
        if any(not val for val in required):
            messages.error(request, "Please fill all mandatory Panel fields.")
            return render(
                request,
                "interview_recording/panel_dashboard.html",
                {
                    "panel_records": _panel_rows(),
                    "show_form": True,
                    "form_data": request.POST,
                    "form_mode": "edit" if record_id else "create",
                    "candidate_options": _candidate_options(),
                    "interviewer_options": interviewer_options,
                    "interviewer_name_list": [item["full_name"] for item in interviewer_options],
                },
            )

        if action == "update_panel" and record_id:
            record = get_object_or_404(InterviewPanelSchedule, id=record_id)
            previous_interviewers = record.interviewers
            record.candidate = candidate
            record.interviewers = payload["interviewers"]
            record.date = payload["date"]
            record.time = payload["time"]
            record.mode = payload["mode"]
            record.video_link = payload["video_link"]
            record.save()
            messages.success(request, "Interview panel updated successfully.")
            if payload["interviewers"] and payload["interviewers"] != previous_interviewers:
                create_notifications(
                    normalize_recipients(payload["interviewers"]),
                    title="Interview panel assigned",
                    message=f"Panel interview scheduled for {candidate.full_name}.",
                    link="/interview-recording/panel/",
                    source="interview_panel",
                    created_by=request.session.get("login_user_name", ""),
                )
        else:
            record = InterviewPanelSchedule.objects.create(
                candidate=candidate,
                interviewers=payload["interviewers"],
                date=payload["date"],
                time=payload["time"],
                mode=payload["mode"],
                video_link=payload["video_link"],
            )
            messages.success(request, "Interview panel scheduled successfully.")
            if payload["interviewers"]:
                create_notifications(
                    normalize_recipients(payload["interviewers"]),
                    title="Interview panel assigned",
                    message=f"Panel interview scheduled for {candidate.full_name}.",
                    link="/interview-recording/panel/",
                    source="interview_panel",
                    created_by=request.session.get("login_user_name", ""),
                )
        return redirect("/interview-recording/panel/")

    form_data = {}
    form_mode = "create"
    if edit_record:
        form_mode = "edit"
        form_data = {
            "record_id": str(edit_record.id),
            "candidate": edit_record.candidate.candidate_id,
            "interviewers": edit_record.interviewers,
            "date": str(edit_record.date),
            "time": str(edit_record.time),
            "mode": edit_record.mode,
            "video_link": edit_record.video_link,
        }

    return render(
        request,
        "interview_recording/panel_dashboard.html",
        {
            "panel_records": _panel_rows(filter_name=current_user, is_admin=is_admin),
            "show_form": show_form,
            "form_data": form_data,
            "form_mode": form_mode,
            "candidate_options": _candidate_options(),
            "interviewer_options": interviewer_options,
            "interviewer_name_list": [item["full_name"] for item in interviewer_options],
        },
    )


def interview_recording_dashboard_view(request):
    edit_id = request.GET.get("edit_id", "").strip()
    edit_record = InterviewRecording.objects.select_related("candidate").filter(id=edit_id).first() if edit_id else None
    show_form = request.GET.get("create") == "1" or bool(edit_record)
    interviewer_options = _interviewer_options()
    current_user = _login_user_name(request)
    is_admin = _is_admin_request(request)

    if request.method == "POST":
        action = request.POST.get("action", "create_recording").strip()
        record_id = request.POST.get("record_id", "").strip()
        uploaded_file = request.FILES.get("video_file")
        transcript = request.POST.get("transcript", "").strip() or "Transcript generated by AI service."
        sentiment_score = request.POST.get("sentiment_score", "").strip() or _score_from_transcript(transcript)
        candidate_ref = request.POST.get("candidate", "").strip()
        candidate = Candidate.objects.filter(candidate_id=candidate_ref).first() or Candidate.objects.filter(full_name=candidate_ref).first()

        if uploaded_file:
            allowed_extensions = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
            file_ext = os.path.splitext(uploaded_file.name)[1].lower()
            content_type = (uploaded_file.content_type or "").lower()
            if file_ext not in allowed_extensions or not content_type.startswith("video/"):
                messages.error(request, "File not supported. Please upload a video file.")
                return render(
                    request,
                    "interview_recording/recording_dashboard.html",
                    {"recording_records": _recording_rows(), "show_form": True},
                )

        required = [candidate, request.POST.get("interviewer", "").strip()]
        if action != "update_recording":
            required.append(uploaded_file)
        if any(not val for val in required):
            messages.error(request, "Please fill all mandatory Recording fields.")
            return render(
                request,
                "interview_recording/recording_dashboard.html",
                {
                    "recording_records": _recording_rows(),
                    "show_form": True,
                    "form_data": request.POST,
                    "form_mode": "edit" if record_id else "create",
                    "candidate_options": _candidate_options(),
                    "interviewer_options": interviewer_options,
                    "interviewer_name_list": [item["full_name"] for item in interviewer_options],
                },
            )

        if action == "update_recording" and record_id:
            record = get_object_or_404(InterviewRecording, id=record_id)
            previous_interviewer = record.interviewer
            record.candidate = candidate
            record.interviewer = request.POST.get("interviewer", "").strip()
            if uploaded_file:
                try:
                    if record.video_file_path:
                        default_storage.delete(record.video_file_path)
                except Exception:
                    pass

                record.video_file_name = uploaded_file.name
                record.video_file_path = _store_uploaded_video(uploaded_file)
            record.transcript = transcript
            
            # Apply Presidio PII Shield (always enabled).
            from .pii_service import redact_pii

            redacted_text, is_redacted = redact_pii(transcript)
            record.anonymized_transcript = redacted_text
            record.pii_redacted = is_redacted
                 
            record.sentiment_score = sentiment_score
            record.save()
            messages.success(request, "Interview recording updated successfully.")
            if record.interviewer and record.interviewer != previous_interviewer:
                create_notifications(
                    record.interviewer,
                    title="Interview recording assigned",
                    message=f"Recording updated for {candidate.full_name}.",
                    link=f"/interview-recording/recording/?edit_id={record.id}",
                    source="interview_recording",
                    created_by=request.session.get("login_user_name", ""),
                )
        else:
            # Apply Presidio PII Shield (always enabled).
            from .pii_service import redact_pii

            redacted_text, is_redacted = redact_pii(transcript)

            record = InterviewRecording.objects.create(
                candidate=candidate,
                interviewer=request.POST.get("interviewer", "").strip(),
                video_file_name=uploaded_file.name,
                video_file_path=_store_uploaded_video(uploaded_file) if uploaded_file else "",
                transcript=transcript,
                anonymized_transcript=redacted_text,
                pii_redacted=is_redacted,
                sentiment_score=sentiment_score,
            )
            messages.success(request, "Interview recording saved securely with transcript and PII controls.")
            if request.POST.get("interviewer", "").strip():
                create_notifications(
                    request.POST.get("interviewer", "").strip(),
                    title="Interview recording assigned",
                    message=f"Recording created for {candidate.full_name}.",
                    link=f"/interview-recording/recording/?edit_id={record.id}",
                    source="interview_recording",
                    created_by=request.session.get("login_user_name", ""),
                )
        return redirect("/interview-recording/recording/")

    form_data = {}
    form_mode = "create"
    if edit_record:
        form_mode = "edit"
        form_data = {
            "record_id": str(edit_record.id),
            "candidate": edit_record.candidate.candidate_id,
            "interviewer": edit_record.interviewer,
            "transcript": edit_record.transcript,
            "sentiment_score": edit_record.sentiment_score,
        }

    return render(
        request,
        "interview_recording/recording_dashboard.html",
        {
            "recording_records": _recording_rows(filter_name=current_user, is_admin=is_admin),
            "show_form": show_form,
            "form_data": form_data,
            "form_mode": form_mode,
            "candidate_options": _candidate_options(),
            "interviewer_options": interviewer_options,
            "interviewer_name_list": [item["full_name"] for item in interviewer_options],
        },
    )


def _panel_rows(filter_name="", is_admin=False):
    rows = []
    panel_query = InterviewPanelSchedule.objects.select_related("candidate").order_by("-created_at")
    if filter_name and not is_admin:
        panel_query = panel_query.filter(interviewers__icontains=filter_name)
    for item in panel_query:
        rows.append(
            {
                "candidate": item.candidate.full_name,
                "interviewers": item.interviewers,
                "date": item.date,
                "time": str(item.time),
                "mode": item.mode or "Panel",
                "video_link": item.video_link,
                "created_at": item.created_at.strftime("%Y-%m-%d %H:%M"),
                "id": item.id,
                "is_editable": True,
                "source": "panel",
                "source_id": item.id,
            }
        )
    inperson_query = InPersonInterview.objects.select_related("candidate").order_by("-created_at")
    if filter_name and not is_admin:
        inperson_query = inperson_query.filter(
            models.Q(interview_owner__iexact=filter_name) | models.Q(interviewer_name__iexact=filter_name)
        )
    for item in inperson_query:
        rows.append(
            {
                "candidate": item.candidate.full_name,
                "interviewers": item.interviewer_name,
                "date": item.date,
                "time": f"{item.from_time} - {item.to_time}",
                "mode": "In Person",
                "video_link": "",
                "created_at": item.created_at.strftime("%Y-%m-%d %H:%M"),
                "id": f"inperson-{item.id}",
                "is_editable": False,
                "source": "inperson",
                "source_id": item.id,
            }
        )
    video_query = VideoInterviewSchedule.objects.select_related("candidate").order_by("-created_at")
    if filter_name and not is_admin:
        video_query = video_query.filter(
            models.Q(interview_owner__iexact=filter_name) | models.Q(interviewer_name__iexact=filter_name)
        )
    for item in video_query:
        rows.append(
            {
                "candidate": item.candidate.full_name,
                "interviewers": item.interviewer_name,
                "date": item.date,
                "time": f"{item.from_time} - {item.to_time}",
                "mode": "Video",
                "video_link": item.meeting_link,
                "created_at": item.created_at.strftime("%Y-%m-%d %H:%M"),
                "id": f"video-{item.id}",
                "is_editable": False,
                "source": "video",
                "source_id": item.id,
            }
        )
    return rows


def _recording_rows(filter_name="", is_admin=False):
    rows = []
    query = InterviewRecording.objects.select_related("candidate").order_by("-created_at")
    if filter_name and not is_admin:
        query = query.filter(interviewer__iexact=filter_name)
    for item in query:
        video_url = ""
        if item.video_file_path and not os.path.isabs(item.video_file_path):
            try:
                video_url = default_storage.url(item.video_file_path)
            except Exception:
                video_url = ""
        rows.append(
            {
                "candidate": item.candidate.full_name,
                "interviewer": item.interviewer,
                "video_file_name": item.video_file_name,
                "video_url": video_url,
                "transcript": item.transcript,
                "anonymized_transcript": item.anonymized_transcript,
                "pii_redacted": item.pii_redacted,
                "sentiment_score": item.sentiment_score,
                "dominant_emotion": item.dominant_emotion,
                "emotion_summary": item.emotion_summary,
                "emotion_error": item.emotion_error,
                "created_at": item.created_at.strftime("%Y-%m-%d %H:%M"),
                "id": item.id,
            }
        )
    return rows


def _score_from_transcript(transcript):
    text = (transcript or "").lower()
    positive_words = ["good", "great", "excellent", "strong", "confident", "clear"]
    negative_words = ["weak", "poor", "confused", "bad", "unclear"]
    score = 5.0
    score += sum(0.6 for word in positive_words if word in text)
    score -= sum(0.6 for word in negative_words if word in text)
    return str(max(0.0, min(10.0, round(score, 2))))


def _candidate_options():
    return list(Candidate.objects.order_by("candidate_id").values("candidate_id", "full_name"))


def _interviewer_options():
    return list(
        UserMaster.objects.filter(status__iexact="Active")
        .exclude(role__iexact="Candidate")
        .order_by("full_name")
        .values("full_name")
    )


def _login_user_name(request):
    return (
        (request.session.get("login_user_name") or "").strip()
        or (request.session.get("login_user_email") or "").strip()
    )


def _is_admin_request(request):
    role = (request.session.get("login_user_role") or "").strip().lower()
    return role in {"admin", "super admin", "administrator"}


def _resolve_video_path(video_file_path, video_file_name):
    if video_file_path and os.path.exists(video_file_path):
        return video_file_path
    if video_file_name:
        fallback = str(Path.home() / "Videos" / video_file_name)
        if os.path.exists(fallback):
            return fallback
    return ""


def _format_emotion_summary(percentages):
    if not percentages:
        return ""
    pairs = sorted(percentages.items(), key=lambda item: item[1], reverse=True)
    return ", ".join([f"{emotion}: {value}%" for emotion, value in pairs])


def _apply_emotion_analysis(record, video_path):
    if not video_path or not os.path.exists(video_path):
        record.emotion_error = "Emotion analysis skipped: video file path not found."
        record.emotion_processed_at = timezone.now()
        record.save(update_fields=["emotion_error", "emotion_processed_at"])
        return

    try:
        result = analyze_video_emotions(video_path)
        record.dominant_emotion = result.get("dominant_emotion", "")
        record.emotion_summary = _format_emotion_summary(result.get("percentages", {}))
        if record.dominant_emotion:
            record.emotion_error = ""
        else:
            record.emotion_error = "Emotion analysis completed, but no face frames were detected."
    except Exception as exc:
        record.dominant_emotion = ""
        record.emotion_summary = ""
        record.emotion_error = f"Emotion analysis failed: {exc}"

    record.emotion_processed_at = timezone.now()
    record.save(update_fields=["dominant_emotion", "emotion_summary", "emotion_error", "emotion_processed_at"])


def panel_delete_confirm_view(request, record_id):
    record = get_object_or_404(InterviewPanelSchedule.objects.select_related("candidate"), id=record_id)
    if request.method == "POST":
        if request.POST.get("action") == "confirm_delete":
            record.delete()
            messages.success(request, "Interview panel schedule deleted.")
        return redirect("/interview-recording/panel/")
    return render(request, "interview_recording/panel_delete_confirm.html", {"record": record})


def recording_delete_confirm_view(request, record_id):
    record = get_object_or_404(InterviewRecording.objects.select_related("candidate"), id=record_id)
    if request.method == "POST":
        if request.POST.get("action") == "confirm_delete":
            record.delete()
            messages.success(request, "Interview recording deleted.")
        return redirect("/interview-recording/recording/")
    return render(request, "interview_recording/recording_delete_confirm.html", {"record": record})


@csrf_exempt
def auto_recording_ingest_view(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Only POST is allowed."}, status=405)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON payload."}, status=400)

    candidate_pk = payload.get("candidate_pk")
    candidate_ref = str(payload.get("candidate_id", "")).strip()
    interviewer = str(payload.get("interviewer", "")).strip()
    video_file_name = str(payload.get("video_file_name", "")).strip()
    video_file_path = str(payload.get("video_file_path", "")).strip()
    transcript = str(payload.get("transcript", "")).strip() or "Auto-recorded via ATS Desktop + OBS."

    if (not candidate_pk and not candidate_ref) or not interviewer or not video_file_name:
        return JsonResponse(
            {"ok": False, "error": "candidate_pk or candidate_id, interviewer and video_file_name are required."},
            status=400,
        )

    candidate = None
    if candidate_pk:
        candidate = Candidate.objects.filter(id=candidate_pk).first()
    if not candidate and candidate_ref:
        candidate = Candidate.objects.filter(candidate_id=candidate_ref).first() or Candidate.objects.filter(
            full_name=candidate_ref
        ).first()
    if not candidate:
        return JsonResponse({"ok": False, "error": "Candidate not found."}, status=404)

    # Apply Presidio PII Shield (always enabled).
    from .pii_service import redact_pii

    redacted_text, is_redacted = redact_pii(transcript)

    created = InterviewRecording.objects.create(
        candidate=candidate,
        interviewer=interviewer,
        video_file_name=video_file_name,
        video_file_path=video_file_path,
        transcript=transcript,
        anonymized_transcript=redacted_text,
        pii_redacted=is_redacted,
        sentiment_score=_score_from_transcript(transcript),
    )
    resolved_video_path = _resolve_video_path(video_file_path, video_file_name)
    _apply_emotion_analysis(created, resolved_video_path)
    return JsonResponse({"ok": True, "record_id": created.id, "dominant_emotion": created.dominant_emotion})
