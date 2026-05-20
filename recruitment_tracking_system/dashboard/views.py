from django.contrib import messages
from django.contrib import messages
from django.shortcuts import redirect
from django.shortcuts import render

from applicant_tracking.models import InPersonInterview, VideoInterviewSchedule
from background_verification.models import BackgroundVerificationRecord
from candidate_management.models import Candidate
from interview_recording.models import InterviewPanelSchedule
from job_requisition.models import JobRequisition
from recruitment_teams.models import RecruitmentTeamMaster
from super_admin.utils import current_context_from_request, is_platform_superadmin


def dashboard_view(request):
    role_name = (request.session.get("login_user_role") or "").strip().lower()
    if role_name == "candidate":
        messages.error(request, "Dashboard is available only for admin/recruitment roles.")
        return redirect("/candidate-portal/")

    widget_catalog = [
        {"key": "requisition", "label": "Requisition Dashboard"},
        {"key": "bgv", "label": "BGV Verification Dashboard"},
        {"key": "candidate", "label": "Candidate Dashboard"},
        {"key": "team", "label": "Team Dashboard"},
    ]
    all_widget_keys = [item["key"] for item in widget_catalog]
    selected_widgets = [key for key in request.GET.getlist("widgets") if key in all_widget_keys]
    if not selected_widgets:
        selected_widgets = all_widget_keys

    job_rows = [
        {
            "job_id": row.job_id,
            "title": row.title,
            "department": row.department,
            "openings": row.openings,
            "applications_received": row.applications_received,
            "status": row.status,
        }
        for row in JobRequisition.objects.order_by("-created_at")
    ]
    bgv_rows = [
        {
            "candidate_id": row.candidate.candidate_id,
            "document_type": row.document_type,
            "verifier_assigned": row.verifier_assigned,
            "status": row.status,
            "comments": row.comments,
        }
        for row in BackgroundVerificationRecord.objects.select_related("candidate").order_by("-updated_at")
    ]
    candidate_rows = [
        {
            "candidate_id": row.candidate_id,
            "job_applied": _candidate_jobs(row),
            "status": (row.evaluations.first().status if row.evaluations.first() else row.status),
            "interview_schedule": "Scheduled" if row.in_person_interviews.exists() else "",
            "bgv_status": (row.bgv_records.first().status if row.bgv_records.first() else ""),
            "documents_uploaded": "Yes" if row.resume_path else "No",
            "offer_letter": "-",
        }
        for row in Candidate.objects.prefetch_related(
            "evaluations",
            "in_person_interviews",
            "bgv_records",
            "job_applications__job",
        ).order_by("-created_at")
    ]
    team_rows = [
        {
            "team": row.team_name,
            "tasks_pending": 0,
            "tasks_completed": 0,
            "total_hours": 0,
            "productivity_metrics": "-",
        }
        for row in RecruitmentTeamMaster.objects.order_by("-created_date")
    ]
    panel_records = []
    for row in InterviewPanelSchedule.objects.select_related("candidate").order_by("-created_at"):
        panel_records.append(
            {
                "candidate": row.candidate.full_name,
                "interviewers": row.interviewers,
                "date": row.date,
                "time": str(row.time),
                "mode": row.mode or "Panel",
            }
        )
    for row in InPersonInterview.objects.select_related("candidate").order_by("-created_at"):
        panel_records.append(
            {
                "candidate": row.candidate.full_name,
                "interviewers": row.interviewer_name,
                "date": row.date,
                "time": f"{row.from_time} - {row.to_time}",
                "mode": "In Person",
            }
        )
    for row in VideoInterviewSchedule.objects.select_related("candidate").order_by("-created_at"):
        panel_records.append(
            {
                "candidate": row.candidate.full_name,
                "interviewers": row.interviewer_name,
                "date": row.date,
                "time": f"{row.from_time} - {row.to_time}",
                "mode": "Video",
            }
        )

    pending_statuses = {"pending", "in review", "in progress", "shortlisted"}

    job_metrics = {
        "total": len(job_rows),
        "pending": sum(1 for row in job_rows if str(row.get("status", "")).strip().lower() in pending_statuses),
        "applications": sum(_to_int(row.get("applications_received")) for row in job_rows),
    }
    bgv_metrics = {
        "total": len(bgv_rows),
        "pending": sum(1 for row in bgv_rows if str(row.get("status", "")).lower() == "pending"),
        "completed": sum(1 for row in bgv_rows if str(row.get("status", "")).lower() == "completed"),
    }
    candidate_metrics = {
        "total": len(candidate_rows),
        "scheduled": sum(1 for row in candidate_rows if str(row.get("interview_schedule", "")).strip()),
        "bgv_completed": sum(
            1 for row in candidate_rows if str(row.get("bgv_status", "")).lower() == "completed"
        ),
    }
    team_metrics = {
        "teams": len(team_rows),
        "pending": sum(_to_int(row.get("tasks_pending")) for row in team_rows),
        "completed": sum(_to_int(row.get("tasks_completed")) for row in team_rows),
    }

    company = None
    subscription = None
    if role_name == "admin" and not is_platform_superadmin(request):
        try:
            from super_admin.models import CompanySubscription

            ctx = current_context_from_request(request)
            company = ctx.company
            if company:
                subscription = (
                    CompanySubscription.objects.filter(company=company)
                    .select_related("plan")
                    .order_by("-end_date", "-created_at")
                    .first()
                )
        except Exception:
            company = None
            subscription = None
    return render(
        request,
        "dashboard/index.html",
        {
            "job_rows": job_rows,
            "bgv_rows": bgv_rows,
            "candidate_rows": candidate_rows,
            "team_rows": team_rows,
            "panel_records": panel_records,
            "job_metrics": job_metrics,
            "bgv_metrics": bgv_metrics,
            "candidate_metrics": candidate_metrics,
            "team_metrics": team_metrics,
            "widget_catalog": widget_catalog,
            "selected_widgets": selected_widgets,
            "company": company,
            "subscription": subscription,
        },
    )


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _candidate_jobs(candidate):
    titles = [item.job.title for item in candidate.job_applications.all() if item.job and item.job.title]
    if titles:
        return ", ".join(dict.fromkeys(titles))
    return candidate.applied_position
