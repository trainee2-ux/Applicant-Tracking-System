from urllib.parse import urlencode
import json

from django.contrib import messages
from django.db.models import Avg
from django.db import models
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from app_settings.constants import INTERVIEW_ROUND_OPTIONS
from app_settings.models import AssessmentForm, UserMaster
from app_settings.notifications import create_notifications, normalize_recipients
from candidate_management.models import Candidate, CandidateEvaluation
from interview_recording.models import InterviewPanelSchedule
from applicant_tracking.models import (
    CandidateAssessmentAssignment,
    CandidateAssessmentSubmission,
    InPersonInterview,
    VideoInterviewSchedule,
)

from .models import InterviewEvaluationSubmission


def _evaluation_form_catalog():
    forms = AssessmentForm.objects.prefetch_related("fields").order_by("name")
    catalog = {"assessment": [], "feedback": [], "map": {}, "name_to_id": {}}
    for form in forms:
        fields = []
        for field in form.fields.all():
            fields.append(
                {
                    "field_name": field.field_name,
                    "label": field.label,
                    "field_type": field.field_type,
                    "required": field.required,
                    "options": [item.strip() for item in (field.options or "").split(",") if item.strip()],
                }
            )
        item = {
            "id": form.id,
            "name": form.name,
            "form_type": form.form_type,
            "fields": fields,
        }
        catalog["map"][str(form.id)] = item
        catalog["name_to_id"][form.name] = form.id
        if form.form_type == "feedback":
            catalog["feedback"].append({"id": form.id, "name": form.name})
        else:
            catalog["assessment"].append({"id": form.id, "name": form.name})
    return catalog


def interview_evaluation_view(request):
    current_user = _login_user_name(request)
    is_admin = _is_admin_request(request)
    aggregates = _build_aggregates(filter_name=current_user, is_admin=is_admin)
    return render(request, "interview_evaluation/index.html", {"aggregates": aggregates})


def interview_evaluation_panel_view(request):
    current_user = _login_user_name(request)
    is_admin = _is_admin_request(request)
    edit_id = request.GET.get("edit_id", "").strip()
    edit_record = InterviewPanelSchedule.objects.select_related("candidate").filter(id=edit_id).first() if edit_id else None
    show_form = request.GET.get("create") == "1" or bool(edit_record)
    interviewer_options = _interviewer_options()
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
        if any(not value for value in [candidate, payload["interviewers"], payload["date"], payload["time"], payload["mode"]]):
            messages.error(request, "Please fill all required panel fields.")
            return render(
                request,
                "interview_evaluation/panel.html",
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
            panel = get_object_or_404(InterviewPanelSchedule, id=record_id)
            previous_interviewers = panel.interviewers
            panel.candidate = candidate
            panel.interviewers = payload["interviewers"]
            panel.date = payload["date"]
            panel.time = payload["time"]
            panel.mode = payload["mode"]
            panel.video_link = payload["video_link"]
            panel.save()
            messages.success(request, "Interview panel updated successfully.")
            if payload["interviewers"] and payload["interviewers"] != previous_interviewers:
                create_notifications(
                    normalize_recipients(payload["interviewers"]),
                    title="Interview panel assigned",
                    message=f"Panel interview scheduled for {candidate.full_name}.",
                    link="/interview-evaluation/panel/",
                    source="interview_panel",
                    created_by=request.session.get("login_user_name", ""),
                )
        else:
            panel = InterviewPanelSchedule.objects.create(candidate=candidate, **payload)
            messages.success(request, "Interview panel scheduled successfully.")
            if payload["interviewers"]:
                create_notifications(
                    normalize_recipients(payload["interviewers"]),
                    title="Interview panel assigned",
                    message=f"Panel interview scheduled for {candidate.full_name}.",
                    link="/interview-evaluation/panel/",
                    source="interview_panel",
                    created_by=request.session.get("login_user_name", ""),
                )
        return redirect("/interview-evaluation/panel/")

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
        "interview_evaluation/panel.html",
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


def interview_evaluation_detail_view(request):
    if request.method == "POST":
        action = request.POST.get("action", "create_evaluation").strip()
        record_id = request.POST.get("record_id", "").strip()
        submit_mode = request.POST.get("submit_mode", "save")
        candidate_id = request.POST.get("candidate_id", "").strip()
        assessment_form_id = request.POST.get("assessment_form_id", "").strip()
        feedback_form_id = request.POST.get("feedback_form_id", "").strip()
        candidate = Candidate.objects.filter(candidate_id=candidate_id).first()
        form_catalog = _evaluation_form_catalog()
        form_map = form_catalog["map"]
        payload = {
            "candidate_name": request.POST.get("candidate_name", "").strip(),
            "interviewer_name": request.POST.get("interviewer_name", "").strip(),
            "interview_round": request.POST.get("interview_round", "").strip(),
            "technical_score": request.POST.get("technical_score", "").strip(),
            "communication_score": request.POST.get("communication_score", "").strip(),
            "cultural_fit_score": request.POST.get("cultural_fit_score", "").strip(),
            "comments": request.POST.get("comments", "").strip(),
        }

        def _collect_dynamic_form_data(form_id, expected_type, prefix):
            if not form_id:
                return "", ""
            form_cfg = form_map.get(str(form_id))
            if not form_cfg or form_cfg.get("form_type") != expected_type:
                return "", ""
            values = {}
            for field in form_cfg["fields"]:
                field_key = f"{prefix}{field['field_name']}"
                if field.get("field_type") == "checkbox":
                    selected_values = [item.strip() for item in request.POST.getlist(field_key) if item.strip()]
                    field_value = ", ".join(selected_values)
                else:
                    field_value = request.POST.get(field_key, "").strip()
                if field.get("required") and not field_value:
                    raise ValueError(f"{form_cfg['name']} - {field['label']} is required.")
                values[field["field_name"]] = field_value
            return form_cfg["name"], json.dumps(values)

        if candidate and not payload["candidate_name"]:
            payload["candidate_name"] = candidate.full_name
        required = [
            candidate,
            payload["candidate_name"],
            payload["interviewer_name"],
            payload["technical_score"],
            payload["communication_score"],
            payload["cultural_fit_score"],
            payload["interview_round"],
        ]
        if any(not value for value in required):
            messages.error(request, "Please fill all required fields.")
            return render_interview_evaluation(
                request,
                show_form=True,
                initial_candidate_id=candidate_id,
                initial_candidate_name=payload["candidate_name"],
                form_data=request.POST,
            )
        try:
            assessment_form_name, assessment_form_data = _collect_dynamic_form_data(
                assessment_form_id,
                "assessment",
                "assessment_field_",
            )
            feedback_form_name, feedback_form_data = _collect_dynamic_form_data(
                feedback_form_id,
                "feedback",
                "feedback_field_",
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return render_interview_evaluation(
                request,
                show_form=True,
                initial_candidate_id=candidate_id,
                initial_candidate_name=payload["candidate_name"],
                form_data=request.POST,
            )

        if action == "update_evaluation" and record_id:
            submission = get_object_or_404(InterviewEvaluationSubmission, id=record_id)
            submission.candidate = candidate
            submission.candidate_name = payload["candidate_name"]
            submission.interviewer_name = payload["interviewer_name"]
            submission.interview_round = payload["interview_round"]
            submission.technical_score = payload["technical_score"]
            submission.communication_score = payload["communication_score"]
            submission.cultural_fit_score = payload["cultural_fit_score"]
            submission.comments = payload["comments"]
            submission.assessment_form_name = assessment_form_name
            submission.assessment_form_data = assessment_form_data
            submission.feedback_form_name = feedback_form_name
            submission.feedback_form_data = feedback_form_data
            submission.save()
            messages.success(request, "Interview evaluation updated successfully.")
            return redirect("/interview-evaluation/evaluation/")

        InterviewEvaluationSubmission.objects.create(
            candidate=candidate,
            assessment_form_name=assessment_form_name,
            assessment_form_data=assessment_form_data,
            feedback_form_name=feedback_form_name,
            feedback_form_data=feedback_form_data,
            **payload,
        )
        CandidateEvaluation.objects.create(
            candidate=candidate,
            candidate_code=candidate.candidate_id,
            candidate_name=payload["candidate_name"],
            candidate_phone=candidate.contact_number or "",
            candidate_email=candidate.email or "",
            posting_title=candidate.applied_position or "",
            interviewed_by=payload["interviewer_name"],
            interview_round=payload["interview_round"],
            technical_score=payload["technical_score"],
            communication_score=payload["communication_score"],
            cultural_fit_score=payload["cultural_fit_score"],
            overall_rating=round(
                (float(payload["technical_score"]) + float(payload["communication_score"]) + float(payload["cultural_fit_score"])) / 3,
                2,
            ),
            interviewer_comments=payload["comments"],
            assessment_form_name=assessment_form_name,
            assessment_form_data=assessment_form_data,
            feedback_form_name=feedback_form_name,
            feedback_form_data=feedback_form_data,
            status="Move to Next Round",
        )
        messages.success(request, "Interview evaluation submitted and sent to Candidate Evaluation.")
        if submit_mode == "save_add":
            query = urlencode({"create": 1, "candidate_id": candidate.candidate_id, "candidate_name": candidate.full_name})
            return redirect(f"/interview-evaluation/evaluation/?{query}")
        return redirect("/interview-evaluation/evaluation/")

    edit_id = request.GET.get("edit_id", "").strip()
    edit_record = InterviewEvaluationSubmission.objects.select_related("candidate").filter(id=edit_id).first() if edit_id else None

    initial_candidate_id = request.GET.get("candidate_id", "").strip()
    initial_candidate_name = request.GET.get("candidate_name", "").strip()
    form_data = {}
    form_catalog = _evaluation_form_catalog()
    name_to_id = form_catalog["name_to_id"]
    if edit_record:
        assessment_values = {}
        feedback_values = {}
        if edit_record.assessment_form_data:
            try:
                assessment_values = json.loads(edit_record.assessment_form_data)
            except (TypeError, ValueError):
                assessment_values = {}
        if edit_record.feedback_form_data:
            try:
                feedback_values = json.loads(edit_record.feedback_form_data)
            except (TypeError, ValueError):
                feedback_values = {}
        form_data = {
            "record_id": str(edit_record.id),
            "candidate_id": edit_record.candidate.candidate_id,
            "candidate_name": edit_record.candidate_name,
            "interviewer_name": edit_record.interviewer_name,
            "interview_round": edit_record.interview_round,
            "technical_score": edit_record.technical_score,
            "communication_score": edit_record.communication_score,
            "cultural_fit_score": edit_record.cultural_fit_score,
            "comments": edit_record.comments,
            "assessment_form_id": str(name_to_id.get(edit_record.assessment_form_name, "")),
            "feedback_form_id": str(name_to_id.get(edit_record.feedback_form_name, "")),
            "assessment_form_values": assessment_values,
            "feedback_form_values": feedback_values,
        }
        initial_candidate_id = edit_record.candidate.candidate_id
        initial_candidate_name = edit_record.candidate_name

    return render_interview_evaluation(
        request,
        show_form=request.GET.get("create") == "1" or bool(edit_record),
        initial_candidate_id=initial_candidate_id,
        initial_candidate_name=initial_candidate_name,
        form_data=form_data,
        form_mode="edit" if edit_record else "create",
    )


def render_interview_evaluation(request, show_form=False, initial_candidate_id="", initial_candidate_name="", form_data=None, form_mode="create"):
    form_data = form_data or {}
    current_user = _login_user_name(request)
    is_admin = _is_admin_request(request)
    eval_proctor_session_token = ""
    EVAL_PROCTOR_MAX_WARNINGS = 5
    if show_form:
        try:
            from proctoring.models import ProctoringSession

            client_ip = (request.META.get("HTTP_X_FORWARDED_FOR") or request.META.get("REMOTE_ADDR") or "").split(",")[0].strip()
            eval_proctor = ProctoringSession.objects.create(
                context="evaluation",
                reference_id=str(form_data.get("record_id") or "new")[:200],
                candidate_name=str(current_user or "")[:200],
                candidate_email=str((request.session.get("login_user_email") or "") or "")[:200],
                max_warnings=EVAL_PROCTOR_MAX_WARNINGS,
                ip_address=client_ip or None,
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
            )
            eval_proctor_session_token = str(eval_proctor.session_token)
        except Exception:
            # Proctoring is best-effort; do not break the evaluator workflow.
            eval_proctor_session_token = ""
    form_catalog = _evaluation_form_catalog()
    round_map = {}
    scheduled_items = []
    for item in InPersonInterview.objects.select_related("candidate").order_by("-created_at"):
        scheduled_items.append((item.created_at, item.candidate, item.interview_process_name))
    for item in VideoInterviewSchedule.objects.select_related("candidate").order_by("-created_at"):
        scheduled_items.append((item.created_at, item.candidate, item.interview_process_name))
    scheduled_items.sort(key=lambda row: row[0] or "")
    for _, candidate_ref, round_name in reversed(scheduled_items):
        candidate_id = candidate_ref.candidate_id if candidate_ref else ""
        if candidate_id and candidate_id not in round_map and round_name:
            round_map[candidate_id] = round_name
    initial_assessment_values = form_data.get("assessment_form_values", {})
    initial_feedback_values = form_data.get("feedback_form_values", {})
    if not isinstance(initial_assessment_values, dict):
        initial_assessment_values = {}
    if not isinstance(initial_feedback_values, dict):
        initial_feedback_values = {}
    if hasattr(form_data, "items"):
        for key, value in form_data.items():
            if key.startswith("assessment_field_"):
                initial_assessment_values[key.replace("assessment_field_", "", 1)] = value
            elif key.startswith("feedback_field_"):
                initial_feedback_values[key.replace("feedback_field_", "", 1)] = value

    records = []
    seen_keys = set()

    def _norm(val):
        return str(val or "").strip().lower()

    submissions = InterviewEvaluationSubmission.objects.select_related("candidate").order_by("-submitted_at")
    if current_user and not is_admin:
        submissions = submissions.filter(interviewer_name__iexact=current_user)
    for item in submissions:
        key = (
            _norm(item.candidate.candidate_id),
            _norm(item.interviewer_name),
            _norm(item.interview_round),
            _norm(item.technical_score),
            _norm(item.communication_score),
            _norm(item.cultural_fit_score),
            _norm(item.comments),
        )
        seen_keys.add(key)
        records.append(
            {
                "id": item.id,
                "is_submission_record": True,
                "candidate_id": item.candidate.candidate_id,
                "candidate_name": item.candidate.full_name,
                "interviewer_name": item.interviewer_name,
                "interview_round": item.interview_round or "-",
                "technical_score": item.technical_score,
                "communication_score": item.communication_score,
                "cultural_fit_score": item.cultural_fit_score,
                "comments": item.comments,
                "assessment_form_name": item.assessment_form_name or "-",
                "feedback_form_name": item.feedback_form_name or "-",
                "submitted_at": item.submitted_at.strftime("%Y-%m-%d %H:%M"),
            }
        )

    # Include Candidate Evaluation entries so they are also visible in Interview Evaluation table.
    eval_records = CandidateEvaluation.objects.select_related("candidate").order_by("-created_at")
    if current_user and not is_admin:
        eval_records = eval_records.filter(interviewed_by__iexact=current_user)
    for item in eval_records:
        key = (
            _norm(item.candidate_code),
            _norm(item.interviewed_by),
            _norm(item.interview_round),
            _norm(item.technical_score),
            _norm(item.communication_score),
            _norm(item.cultural_fit_score),
            _norm(item.interviewer_comments),
        )
        if key in seen_keys:
            continue
        records.append(
            {
                "id": f"ce-{item.id}",
                "is_submission_record": False,
                "candidate_id": item.candidate_code,
                "candidate_name": item.candidate_name,
                "interviewer_name": item.interviewed_by,
                "interview_round": item.interview_round or "-",
                "technical_score": item.technical_score,
                "communication_score": item.communication_score,
                "cultural_fit_score": item.cultural_fit_score,
                "comments": item.interviewer_comments,
                "assessment_form_name": item.assessment_form_name or "-",
                "feedback_form_name": item.feedback_form_name or "-",
                "submitted_at": item.created_at.strftime("%Y-%m-%d %H:%M"),
            }
        )

    records.sort(key=lambda row: row["submitted_at"], reverse=True)
    interviewer_options = _interviewer_options()
    return render(
        request,
        "interview_evaluation/evaluation.html",
        {
            "show_form": show_form,
            "records": records,
            "aggregates": _build_aggregates(filter_name=current_user, is_admin=is_admin),
            "initial_candidate_id": initial_candidate_id,
            "initial_candidate_name": initial_candidate_name,
            "form_data": form_data,
            "form_mode": form_mode,
            "candidate_options": _candidate_options(),
            "interviewer_options": interviewer_options,
            "interviewer_name_list": [item["full_name"] for item in interviewer_options],
            "assessment_form_options": form_catalog["assessment"],
            "feedback_form_options": form_catalog["feedback"],
            "evaluation_form_map": form_catalog["map"],
            "initial_assessment_form_values": initial_assessment_values,
            "initial_feedback_form_values": initial_feedback_values,
            "interview_round_options": INTERVIEW_ROUND_OPTIONS,
            "candidate_round_map": round_map,
            "eval_proctor_session_token": eval_proctor_session_token,
            "eval_proctor_max_warnings": EVAL_PROCTOR_MAX_WARNINGS,
        },
    )


def assessment_result_view(request):
    candidate_id = (request.GET.get("candidate_id") or "").strip()
    assessment_form_id = (request.GET.get("assessment_form_id") or "").strip()
    if not candidate_id:
        return JsonResponse({"found": False, "error": "candidate_id is required"}, status=400)

    assignment_qs = CandidateAssessmentAssignment.objects.select_related("assessment_form", "candidate").filter(
        candidate__candidate_id__iexact=candidate_id
    )
    if assessment_form_id:
        try:
            assignment_qs = assignment_qs.filter(assessment_form_id=int(assessment_form_id))
        except ValueError:
            return JsonResponse({"found": False, "error": "assessment_form_id must be an integer"}, status=400)

    assignment = assignment_qs.order_by("-assigned_at").first()
    if not assignment:
        return JsonResponse({"found": False})

    submission = CandidateAssessmentSubmission.objects.filter(assignment=assignment).first()
    score = float(submission.score) if submission else None
    max_score = float(submission.max_score) if (submission and submission.max_score is not None) else None
    percent = None
    if score is not None and max_score:
        try:
            percent = round((score / float(max_score)) * 100.0, 2)
        except ZeroDivisionError:
            percent = None

    return JsonResponse(
        {
            "found": True,
            "candidate_id": candidate_id,
            "assessment_form_id": assignment.assessment_form_id,
            "assessment_form_name": assignment.assessment_form.name if assignment.assessment_form else "",
            "status": assignment.status,
            "assigned_at": assignment.assigned_at.strftime("%Y-%m-%d %H:%M") if assignment.assigned_at else "",
            "due_at": assignment.due_at.strftime("%Y-%m-%d %H:%M") if assignment.due_at else "",
            "completed_at": assignment.completed_at.strftime("%Y-%m-%d %H:%M") if assignment.completed_at else "",
            "submission_exists": bool(submission),
            "submitted_at": submission.submitted_at.strftime("%Y-%m-%d %H:%M") if submission else "",
            "score": score,
            "max_score": max_score,
            "percent": percent,
        }
    )


def _build_aggregates(filter_name="", is_admin=False):
    aggregates = []
    query = InterviewEvaluationSubmission.objects.select_related("candidate")
    if filter_name and not is_admin:
        query = query.filter(interviewer_name__iexact=filter_name)
    grouped = (
        query
        .values("candidate__candidate_id", "candidate__full_name")
        .annotate(
            technical_score=Avg("technical_score"),
            communication_score=Avg("communication_score"),
            cultural_fit_score=Avg("cultural_fit_score"),
        )
    )
    for row in grouped:
        latest_query = InterviewEvaluationSubmission.objects.select_related("candidate").filter(
            candidate__candidate_id=row["candidate__candidate_id"]
        )
        if filter_name and not is_admin:
            latest_query = latest_query.filter(interviewer_name__iexact=filter_name)
        latest = latest_query.order_by("-submitted_at").first()
        overall = round(
            (
                float(row["technical_score"] or 0)
                + float(row["communication_score"] or 0)
                + float(row["cultural_fit_score"] or 0)
            )
            / 3,
            2,
        )
        submission_query = InterviewEvaluationSubmission.objects.filter(
            candidate__candidate_id=row["candidate__candidate_id"]
        )
        if filter_name and not is_admin:
            submission_query = submission_query.filter(interviewer_name__iexact=filter_name)
        aggregates.append(
            {
                "candidate_id": row["candidate__candidate_id"],
                "candidate_name": row["candidate__full_name"],
                "technical_score": round(float(row["technical_score"] or 0), 2),
                "communication_score": round(float(row["communication_score"] or 0), 2),
                "cultural_fit_score": round(float(row["cultural_fit_score"] or 0), 2),
                "overall_score": overall,
                "comments": (latest.comments if latest and latest.comments else "-"),
                "submission_count": submission_query.count(),
            }
        )
    return aggregates


def _login_user_name(request):
    return (
        (request.session.get("login_user_name") or "").strip()
        or (request.session.get("login_user_email") or "").strip()
    )


def _is_admin_request(request):
    role = (request.session.get("login_user_role") or "").strip().lower()
    return role in {"admin", "super admin", "administrator"}


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
                "time": item.time,
                "mode": item.mode,
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


def _candidate_options():
    return list(Candidate.objects.order_by("candidate_id").values("candidate_id", "full_name"))


def _interviewer_options():
    return list(
        UserMaster.objects.filter(status__iexact="Active")
        .exclude(role__iexact="Candidate")
        .order_by("full_name")
        .values("full_name")
    )


def interview_evaluation_panel_delete_confirm_view(request, record_id):
    record = get_object_or_404(InterviewPanelSchedule.objects.select_related("candidate"), id=record_id)
    if request.method == "POST":
        if request.POST.get("action") == "confirm_delete":
            record.delete()
            messages.success(request, "Interview evaluation panel deleted.")
        return redirect("/interview-evaluation/panel/")
    return render(request, "interview_evaluation/panel_delete_confirm.html", {"record": record})


def interview_evaluation_submission_delete_confirm_view(request, record_id):
    record = get_object_or_404(InterviewEvaluationSubmission.objects.select_related("candidate"), id=record_id)
    if request.method == "POST":
        if request.POST.get("action") == "confirm_delete":
            record.delete()
            messages.success(request, "Interview evaluation submission deleted.")
        return redirect("/interview-evaluation/evaluation/")
    return render(request, "interview_evaluation/submission_delete_confirm.html", {"record": record})
