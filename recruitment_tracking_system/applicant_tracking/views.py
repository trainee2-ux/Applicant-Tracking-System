import json
import logging
import smtplib
import re
from datetime import datetime

from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMessage, EmailMultiAlternatives, get_connection
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse
from django.core import signing
from django.db.models import Q
from django.utils import timezone
from django.template.loader import render_to_string
from django.template import Template, Context
from django.urls import reverse

from app_settings.constants import INTERVIEW_ROUND_OPTIONS
from app_settings.models import (
    AssessmentForm,
    CompanyInfo,
    EmailDeliveryConfig,
    EmailTemplate,
    InterviewIntegrationSetting,
    UserMaster,
)
from app_settings.notifications import create_notifications, normalize_recipients
from app_settings.models import UiNotification
from candidate_management.models import Candidate, CandidateJobApplication
from job_requisition.models import JobRequisition

from .meeting_service import MeetingServiceError, create_provider_meeting
from .google_calendar import sync_interview_calendar_event
from .models import (
    ApplicationPipelineCandidate,
    CandidateAssessmentAssignment,
    CandidateAssessmentSubmission,
    InPersonInterview,
    LoginInterviewSchedule,
    VideoInterviewSchedule,
)
try:
    from interview_recording.models import InterviewRecording
except ImportError:
    InterviewRecording = None

logger = logging.getLogger(__name__)


def _normalize_smtp_password(host: str, password: str) -> str:
    cleaned_host = (host or "").strip().lower()
    cleaned_password = (password or "").strip()
    if not cleaned_password:
        return ""

    if cleaned_host in {"smtp.gmail.com", "smtp.googlemail.com"}:
        if " " in cleaned_password:
            compact = cleaned_password.replace(" ", "")
            if len(compact) == 16:
                return compact
    return cleaned_password


def _set_application_stage_by_title(candidate, posting_title, stage):
    title = (posting_title or "").strip()
    if not title or not stage:
        return
    app = (
        CandidateJobApplication.objects.select_related("job")
        .filter(candidate=candidate, job__title__iexact=title)
        .order_by("-applied_on")
        .first()
    )
    if app and app.stage != stage:
        app.stage = stage
        app.save(update_fields=["stage"])


def _split_cc_emails(raw_value):
    if not raw_value:
        return []
    cleaned = raw_value.replace(";", ",")
    emails = [item.strip() for item in cleaned.split(",") if item.strip()]
    return list(dict.fromkeys(emails))


def _cc_role_user_options():
    rows = (
        UserMaster.objects.filter(status__iexact="Active")
        .exclude(role__iexact="Candidate")
        .order_by("role", "full_name", "email_id")
    )
    role_map = {}
    for user in rows:
        role = (user.role or "Other").strip() or "Other"
        email_value = (user.email_id or "").strip()
        entry = {
            "name": (user.full_name or "").strip() or email_value,
            "email": email_value,
        }
        if not entry["email"]:
            continue
        role_map.setdefault(role, []).append(entry)
    return [{"role": role, "users": users} for role, users in role_map.items()]


def _send_candidate_video_invite(candidate, interview, provider_label):
    if not candidate.email:
        return "Failed", "Candidate email is empty."

    mail_meeting_link = interview.meeting_link or ""
    default_subject = f"Interview Invite - {interview.posting_title or 'Interview'}"
    default_body = (
        f"Hi {candidate.full_name},\n\n"
        f"Your interview has been scheduled.\n"
        f"Provider: {provider_label}\n"
        f"Date: {interview.date}\n"
        f"Time: {interview.from_time} - {interview.to_time}\n"
        f"Meeting Link: {mail_meeting_link}\n\n"
        "Please join on time.\n"
    )

    def render_template(text, context):
        if not text:
            return ""
        rendered = text
        for key, value in context.items():
            token = "{{" + key + "}}"
            rendered = rendered.replace(token, str(value or ""))
        return rendered

    template = EmailTemplate.objects.filter(is_active=True, name__iexact="Interview Invite").first()
    context = {
        "candidate_name": candidate.full_name or "",
        "candidate_email": candidate.email or "",
        "interviewer_name": interview.interviewer_name or "",
        "interview_date": interview.date or "",
        "interview_time": f"{interview.from_time} - {interview.to_time}",
        "job_title": interview.posting_title or "",
        "meeting_link": mail_meeting_link,
    }
    subject = render_template(template.subject, context) if template else default_subject
    body = render_template(template.body, context) if template else default_body

    email_config = EmailDeliveryConfig.objects.order_by("-updated_at").first()
    if email_config and email_config.smtp_enabled:
        if not email_config.host:
            return "Failed", "SMTP is enabled but host is empty in Integration settings."
        smtp_password = _normalize_smtp_password(email_config.host, email_config.password or "")
        connection = get_connection(
            backend="django.core.mail.backends.smtp.EmailBackend",
            host=email_config.host,
            port=email_config.port or 587,
            username=email_config.username or "",
            password=smtp_password,
            use_tls=email_config.use_tls,
        )
        from_email = email_config.from_email or settings.DEFAULT_FROM_EMAIL
    else:
        connection = get_connection()
        from_email = settings.DEFAULT_FROM_EMAIL

    try:
        cc_list = _split_cc_emails(interview.cc_emails)
        message = EmailMessage(
            subject=subject,
            body=body,
            from_email=from_email,
            to=[candidate.email],
            cc=cc_list,
            connection=connection,
        )
        message.send(fail_silently=False)
        return "Sent", ""
    except smtplib.SMTPAuthenticationError as exc:
        host = (email_config.host or "").strip().lower() if email_config else ""
        if host in {"smtp.gmail.com", "smtp.googlemail.com"}:
            return (
                "Failed",
                "Gmail SMTP authentication failed. Use a Google App Password (not your normal password) "
                "and paste it without spaces; also ensure 2‑Step Verification is enabled on the account.",
            )
        return "Failed", f"SMTP authentication failed: {exc}"
    except Exception as exc:
        return "Failed", str(exc)


def _send_candidate_stage_update_email(*, request, candidate, job_title: str, previous_stage: str, new_stage: str) -> None:
    if not candidate or not (candidate.email or "").strip():
        return
    if not new_stage or (previous_stage or "").strip() == new_stage.strip():
        return

    def render_template(text, context):
        if not text:
            return ""
        try:
            return Template(str(text)).render(Context(context or {}, autoescape=True))
        except Exception:
            rendered = str(text)
            for key, value in (context or {}).items():
                pattern = r"{{\s*" + re.escape(str(key)) + r"\s*}}"
                rendered = re.sub(pattern, str(value or ""), rendered, flags=re.IGNORECASE)
            return rendered

    def _looks_like_full_html(value: str) -> bool:
        snippet = (value or "").strip().lower()
        if not snippet:
            return False
        return "<!doctype" in snippet[:400] or "<html" in snippet[:400] or "<head" in snippet[:800]

    def normalize_trigger(value: str) -> str:
        cleaned = (value or "").strip().lower()
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    stage_key = normalize_trigger(new_stage).replace(" ", "_")
    stage_trigger = f"candidate_stage:{stage_key}" if stage_key else ""

    template = None
    if stage_trigger:
        template = EmailTemplate.objects.filter(is_active=True, trigger__iexact=stage_trigger).order_by("-updated_at").first()
    if not template:
        template = EmailTemplate.objects.filter(is_active=True, trigger__iexact="candidate_stage_update").order_by("-updated_at").first()
    if not template:
        template = EmailTemplate.objects.filter(is_active=True, name__iexact="Stage Update").first()
    if not template:
        template = (
            EmailTemplate.objects.filter(is_active=True)
            .filter(Q(module__icontains="applicant") | Q(trigger__icontains="stage"))
            .order_by("-updated_at")
            .first()
        )

    signer = signing.TimestampSigner(salt="candidate_portal_magic")
    token = signer.sign(candidate.email)
    portal_url = request.build_absolute_uri(f"/candidate-portal/magic/{token}/")

    context = {
        "candidate_name": candidate.full_name or "",
        "candidate_email": candidate.email or "",
        "candidate_id": candidate.candidate_id or "",
        "job_title": job_title or "",
        "previous_stage": previous_stage or "",
        "stage": new_stage or "",
        "new_stage": new_stage or "",
        "company_name": getattr(settings, "ATS_COMPANY_NAME", ""),
        "today": timezone.localdate().isoformat(),
        "portal_url": portal_url,
    }

    default_subject = f"Application Stage Updated - {job_title or 'Your Application'}"
    default_body_text = (
        f"Hi {candidate.full_name},\n\n"
        f"Your application stage has been updated.\n\n"
        f"Job: {job_title}\n"
        f"Previous Stage: {previous_stage}\n"
        f"New Stage: {new_stage}\n\n"
        f"Regards,\n{getattr(settings, 'ATS_COMPANY_NAME', 'HR Team')}"
    )
    default_body_html = (
        f"<p>Hi {candidate.full_name},</p>"
        "<p>Your application stage has been updated.</p>"
        f"<p><strong>Job:</strong> {job_title}<br>"
        f"<strong>Previous Stage:</strong> {previous_stage}<br>"
        f"<strong>New Stage:</strong> {new_stage}</p>"
        f"<p>Regards,<br>{getattr(settings, 'ATS_COMPANY_NAME', 'HR Team')}</p>"
    )

    subject = render_template(template.subject, context) if template else default_subject
    inner_body_html = render_template(template.body, context) if template else default_body_html

    # If the user saved a full HTML document in the template body, send it as-is.
    # Otherwise, wrap their content inside the standard branded stage-update shell.
    if template and _looks_like_full_html(template.body):
        body_html = inner_body_html
    else:
        body_html = render_to_string(
            "applicant_tracking/emails/stage_update.html",
            {
                "candidate": candidate,
                "job_title": job_title,
                "previous_stage": previous_stage,
                "new_stage": new_stage,
                "body_html": inner_body_html,
                "company_name": getattr(settings, "ATS_COMPANY_NAME", "Company"),
                "portal_url": portal_url,
            },
        )
    # Generate a text fallback from the HTML body when possible.
    body_text = default_body_text
    if inner_body_html:
        body_text = re.sub(r"<[^>]+>", "", inner_body_html)
        body_text = re.sub(r"\n{3,}", "\n\n", body_text).strip() or default_body_text

    email_config = EmailDeliveryConfig.objects.order_by("-updated_at").first()
    if email_config and email_config.smtp_enabled:
        if not email_config.host:
            logger.warning("stage update email skipped: smtp enabled but host empty")
            return
        smtp_password = _normalize_smtp_password(email_config.host, email_config.password or "")
        connection = get_connection(
            backend="django.core.mail.backends.smtp.EmailBackend",
            host=email_config.host,
            port=email_config.port or 587,
            username=email_config.username or "",
            password=smtp_password,
            use_tls=email_config.use_tls,
        )
        from_email = (email_config.from_email or "").strip() or (email_config.username or "").strip() or settings.DEFAULT_FROM_EMAIL
    else:
        connection = get_connection()
        from_email = settings.DEFAULT_FROM_EMAIL

    message = EmailMultiAlternatives(
        subject=subject,
        body=body_text,
        from_email=from_email,
        to=[candidate.email],
        connection=connection,
    )
    if body_html:
        message.attach_alternative(body_html, "text/html")
    try:
        message.send(fail_silently=False)
    except Exception as exc:
        logger.warning("stage update email send failed candidate=%s err=%s", getattr(candidate, "candidate_id", ""), exc)
        raise


def applicant_tracking_view(request):
    return render(request, "applicant_tracking/index.html")


def _login_user_name(request):
    return (
        (request.session.get("login_user_name") or "").strip()
        or (request.session.get("login_user_email") or "").strip()
    )


def _is_admin_request(request):
    role = (request.session.get("login_user_role") or "").strip().lower()
    return role in {"admin", "super admin", "administrator"}


def _can_access_interview(request, interview):
    if _is_admin_request(request):
        return True
    user = _login_user_name(request).lower()
    if not user:
        return False
    owner = (interview.interview_owner or "").strip().lower()
    interviewer = (interview.interviewer_name or "").strip().lower()
    return user == owner or user == interviewer


def _send_assessment_assignment_email(*, request, candidate: Candidate, assessment_name: str, assignment_url: str) -> tuple[str, str]:
    if not candidate or not (candidate.email or "").strip():
        return "Skipped", "Candidate email missing."

    email_config = EmailDeliveryConfig.objects.order_by("-updated_at").first()
    if email_config and email_config.smtp_enabled:
        if not email_config.host:
            return "Failed", "SMTP is enabled but host is empty in Integration settings."
        smtp_password = _normalize_smtp_password(email_config.host, email_config.password or "")
        connection = get_connection(
            backend="django.core.mail.backends.smtp.EmailBackend",
            host=email_config.host,
            port=email_config.port or 587,
            username=email_config.username or "",
            password=smtp_password,
            use_tls=email_config.use_tls,
        )
        from_email = email_config.from_email or settings.DEFAULT_FROM_EMAIL
    else:
        connection = get_connection()
        from_email = settings.DEFAULT_FROM_EMAIL

    subject = f"Assessment Assigned: {assessment_name}".strip()
    html_body = render_to_string(
        "candidate_portal/emails/assessment_assignment.html",
        {
            "company_name": getattr(settings, "ATS_COMPANY_NAME", "Ultimatix ATS"),
            "candidate_name": candidate.full_name or "",
            "assessment_name": assessment_name or "",
            "assignment_url": assignment_url or "",
        },
    )
    text_body = re.sub(r"<[^>]+>", "", html_body or "").strip() or subject

    try:
        message = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=from_email,
            to=[candidate.email],
            connection=connection,
        )
        message.attach_alternative(html_body, "text/html")
        message.send(fail_silently=False)
        return "Sent", ""
    except smtplib.SMTPAuthenticationError as exc:
        host = (email_config.host or "").strip().lower() if email_config else ""
        if host in {"smtp.gmail.com", "smtp.googlemail.com"}:
            return (
                "Failed",
                "Gmail SMTP authentication failed. Use a Google App Password (not your normal password) "
                "and paste it without spaces; also ensure 2‑Step Verification is enabled on the account.",
            )
        return "Failed", f"SMTP authentication failed: {exc}"
    except Exception as exc:
        return "Failed", str(exc)


def _create_ui_notification(*, recipient: str, title: str, message: str = "", link: str = "", source: str = "assessment") -> None:
    recipient = (recipient or "").strip()
    if not recipient:
        return
    try:
        UiNotification.objects.create(
            recipient_name=recipient[:180],
            title=(title or "").strip()[:180] or "Notification",
            message=(message or "").strip(),
            link=(link or "").strip()[:255],
            source=(source or "").strip()[:60],
        )
    except Exception:
        logger.exception("UI notification create failed. recipient=%s title=%s", recipient, title)


def application_pipeline_view(request):
    if request.method == "POST":
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except Exception:
            payload = {}
        if payload.get("action") == "update_stage":
            candidate_id = (payload.get("candidate_id") or "").strip()
            job_applied = (payload.get("job_applied") or "").strip()
            stage = (payload.get("stage") or "").strip()
            if not candidate_id or not stage:
                return JsonResponse({"ok": False, "message": "Invalid request"}, status=400)

            candidate = Candidate.objects.filter(candidate_id=candidate_id).first()
            if not candidate:
                return JsonResponse({"ok": False, "message": "Candidate not found"}, status=404)

            previous_status = candidate.status
            candidate.status = stage
            candidate.save(update_fields=["status", "updated_at"])

            if job_applied:
                app = (
                    CandidateJobApplication.objects.select_related("job")
                    .filter(candidate=candidate, job__title__iexact=job_applied)
                    .order_by("-applied_on")
                    .first()
                )
                if app:
                    app.stage = stage
                    app.save(update_fields=["stage"])
            else:
                for app in CandidateJobApplication.objects.filter(candidate=candidate):
                    app.stage = stage
                    app.save(update_fields=["stage"])

            pipeline, _created = ApplicationPipelineCandidate.objects.get_or_create(
                candidate=candidate,
                job_applied=job_applied,
                defaults={"stage": stage},
            )
            if pipeline.stage != stage:
                pipeline.stage = stage
                pipeline.save(update_fields=["stage", "last_updated"])
            if not job_applied:
                for row in ApplicationPipelineCandidate.objects.filter(candidate=candidate):
                    if row.stage != stage:
                        row.stage = stage
                        row.save(update_fields=["stage", "last_updated"])

            try:
                # Stage-change email is handled by the branded stage update email below.
                # Avoid sending a second plain-text status-change email from candidate_management.
                pass
            except Exception:
                pass

            try:
                _send_candidate_stage_update_email(
                    request=request,
                    candidate=candidate,
                    job_title=job_applied,
                    previous_stage=previous_status,
                    new_stage=stage,
                )
                email_ok = True
                email_error = ""
            except Exception as exc:
                email_ok = False
                email_error = str(exc)
                logger.warning("stage update email failed candidate=%s err=%s", candidate_id, exc)

            return JsonResponse({"ok": True, "email_ok": email_ok, "email_error": email_error})

    default_stage_order = ["Applied", "Screened", "Interview", "Offer", "Hired", "Rejected"]
    selected_job_id = request.GET.get("job_id", "").strip()
    selected_job = JobRequisition.objects.filter(job_id=selected_job_id).first() if selected_job_id else None
    stage_order = default_stage_order
    if selected_job:
        configured = [item.strip() for item in (selected_job.stages or "").split(",") if item.strip()]
        if configured:
            stage_order = configured

    def _candidate_has_selected_job(candidate_obj):
        if not selected_job:
            return True
        target_title = (selected_job.title or "").strip().lower()
        if not target_title:
            return False
        mapped_titles = [
            (entry.job.title or "").strip().lower()
            for entry in candidate_obj.job_applications.all()
            if entry.job and entry.job.title
        ]
        if target_title in mapped_titles:
            return True
        applied_positions = [item.strip().lower() for item in (candidate_obj.applied_position or "").split(",") if item.strip()]
        return target_title in applied_positions

    def _find_resume_match_score(candidate_obj, job_title: str):
        title_key = (job_title or "").strip().lower()
        if not title_key:
            return None
        apps = getattr(candidate_obj, "job_applications", None)
        if apps is None:
            return None
        for app in apps.all():
            if not app.job or not app.job.title:
                continue
            if (app.job.title or "").strip().lower() != title_key:
                continue
            value = getattr(app, "resume_match_score", None)
            if value is None:
                return None
            try:
                return round(float(value), 2)
            except Exception:
                return None
        return None

    def _score_to_quotient(score):
        if score is None:
            return "N/A"
        try:
            value = float(score)
        except Exception:
            return "N/A"
        if value >= 90:
            return "A+ Intelligence"
        if value >= 80:
            return "A Intelligence"
        if value >= 70:
            return "B+ Intelligence"
        if value >= 60:
            return "B Intelligence"
        if value >= 50:
            return "C Intelligence"
        return "D Intelligence"

    def _format_score(score):
        if score is None:
            return None
        try:
            value = float(score)
        except Exception:
            return None
        text = f"{value:.2f}".rstrip("0").rstrip(".")
        return text

    entries = (
        ApplicationPipelineCandidate.objects.select_related("candidate")
        .prefetch_related("candidate__job_applications__job")
        .exclude(stage__iexact="Rejected")
        .order_by("-last_updated")
    )
    grouped = {stage: [] for stage in stage_order}
    covered_candidate_jobs = set()
    for item in entries:
        if selected_job and (item.job_applied or "").strip().lower() != (selected_job.title or "").strip().lower():
            continue
        covered_candidate_jobs.add((item.candidate_id, (item.job_applied or "").strip().lower()))
        if item.stage not in grouped:
            grouped[item.stage] = []
            stage_order.append(item.stage)
        match_score = _find_resume_match_score(item.candidate, item.job_applied)
        grouped[item.stage].append(
            {
                "candidate_id": item.candidate.candidate_id,
                "name": item.candidate.full_name,
                "job_applied": item.job_applied,
                "stage": item.stage,
                "last_updated": item.last_updated.strftime("%Y-%m-%d %H:%M"),
                "match_score": _format_score(match_score),
                "quotient": _score_to_quotient(match_score),
            }
        )

    # Show candidates in pipeline even before an explicit pipeline row is created.
    for candidate in Candidate.objects.prefetch_related("job_applications__job").order_by("-updated_at"):
        if (candidate.status or "").strip().lower() == "rejected":
            continue
        if not _candidate_has_selected_job(candidate):
            continue
        for app in candidate.job_applications.all():
            if not app.job:
                continue
            if (app.stage or "").strip().lower() == "rejected":
                continue
            job_title = (app.job.title or "").strip()
            if selected_job and (job_title.lower() != (selected_job.title or "").strip().lower()):
                continue
            if (candidate.id, job_title.lower()) in covered_candidate_jobs:
                continue
            stage = app.stage or _map_candidate_status_to_stage(candidate.status)
            if stage not in grouped:
                grouped[stage] = []
                stage_order.append(stage)
            match_score = None
            try:
                match_score = round(float(getattr(app, "resume_match_score", None)), 2) if app.resume_match_score is not None else None
            except Exception:
                match_score = None
            grouped[stage].append(
                {
                    "candidate_id": candidate.candidate_id,
                    "name": candidate.full_name,
                    "job_applied": job_title or candidate.applied_position,
                    "stage": stage,
                    "last_updated": app.applied_on.strftime("%Y-%m-%d %H:%M"),
                    "match_score": _format_score(match_score),
                    "quotient": _score_to_quotient(match_score),
                }
            )

    columns = [{"name": stage, "items": grouped.get(stage, [])} for stage in stage_order]
    position_options = list(
        JobRequisition.objects.order_by("-created_at").values("job_id", "title", "stages")
    )
    return render(
        request,
        "applicant_tracking/application_pipeline.html",
        {
            "columns": columns,
            "position_options": position_options,
            "selected_job_id": selected_job_id,
        },
    )


def _map_candidate_status_to_stage(status):
    value = (status or "").strip().lower()
    if value in {"applied"}:
        return "Applied"
    if value in {"screened", "under review"}:
        return "Screened"
    if value in {"offer", "offered"}:
        return "Offer"
    if value in {"hired", "strong hire"}:
        return "Hired"
    if value in {"rejected"}:
        return "Rejected"
    if "interview" in value or value in {"in progress", "move to next round", "shortlist", "on-hold", "wait-list"}:
        return "Interview"
    return "Applied"


def interview_scheduling_view(request):
    candidate_options = [
        {"id": c.candidate_id, "name": c.full_name}
        for c in Candidate.objects.order_by("candidate_id")
    ]
    enabled_video_integrations = list(
        InterviewIntegrationSetting.objects.filter(
            is_enabled=True,
            provider_key__in=["google_meet", "microsoft_teams", "zoom"],
        ).values_list("provider_label", flat=True)
    )
    return render(
        request,
        "applicant_tracking/interview_scheduling.html",
        {
            "candidate_options": candidate_options,
            "enabled_video_integrations": enabled_video_integrations,
        },
    )


def in_person_interview_view(request):
    option_context = _in_person_form_options()
    current_user = _login_user_name(request)
    is_admin = _is_admin_request(request)

    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        record_id = request.POST.get("record_id", "").strip()
        if action == "update_interview_dropdown":
            interview = get_object_or_404(InPersonInterview, id=request.POST.get("interview_id"))
            if not _can_access_interview(request, interview):
                messages.error(request, "Access denied for this interview.")
                return redirect("applicant_tracking:in_person_interview")
            field_name = request.POST.get("field_name", "").strip()
            field_value = request.POST.get("field_value", "").strip()
            if field_name in {"interview_process_name", "client_name", "interview_owner", "assessment_name"} and field_value:
                setattr(interview, field_name, field_value)
                interview.save(update_fields=[field_name, "updated_at"] if hasattr(interview, "updated_at") else [field_name])
                messages.success(request, "Interview row updated.")
            return redirect("applicant_tracking:in_person_interview")

        candidate_ref = request.POST.get("candidate_name", "").strip()
        candidate = Candidate.objects.filter(candidate_id=candidate_ref).first() or Candidate.objects.filter(
            full_name=candidate_ref
        ).first()
        if not candidate:
            messages.error(request, "Valid candidate is required.")
            return redirect("applicant_tracking:in_person_interview")

        required = [
            request.POST.get("posting_title", "").strip(),
            request.POST.get("date", "").strip(),
            request.POST.get("from_time", "").strip(),
            request.POST.get("to_time", "").strip(),
        ]
        if any(not item for item in required):
            messages.error(request, "Please fill all mandatory fields.")
            return render(
                request,
                "applicant_tracking/in_person_interview.html",
                {
                    "rows": _serialize_interviews(filter_name=current_user, is_admin=is_admin),
                    "show_form": True,
                    "form_data": request.POST,
                    **option_context,
                },
            )

        payload = {
            "candidate": candidate,
            "interview_process_name": request.POST.get("interview_process_name", "").strip(),
            "posting_title": request.POST.get("posting_title", "").strip(),
            "interviewer_name": request.POST.get("interview_owner", "").strip(),
            "client_name": request.POST.get("client_name", "").strip(),
            "date": request.POST.get("date"),
            "from_time": request.POST.get("from_time"),
            "to_time": request.POST.get("to_time"),
            "location": request.POST.get("location", "").strip(),
            "interview_owner": request.POST.get("interview_owner", "").strip(),
            "schedule_comments": request.POST.get("schedule_comments", "").strip(),
            "assessment_name": request.POST.get("assessment_name", "").strip(),
        }
        attachment = request.FILES.get("attachment")
        if attachment:
            payload["attachment_name"] = attachment.name
        if record_id:
            interview = get_object_or_404(InPersonInterview, id=record_id)
            if not _can_access_interview(request, interview):
                messages.error(request, "Access denied for this interview.")
                return redirect("applicant_tracking:in_person_interview")
            previous_owner = (interview.interview_owner or "").strip()
            for key, value in payload.items():
                setattr(interview, key, value)
            interview.save()
            messages.success(request, "In person interview updated successfully.")
            if payload["interview_owner"] and payload["interview_owner"] != previous_owner:
                create_notifications(
                    payload["interview_owner"],
                    title="Interview assigned",
                    message=f"In-person interview scheduled for {candidate.full_name}.",
                    link=f"/applicant-tracking/interview-scheduling/in-person/?edit_id={interview.id}",
                    source="interview",
                    created_by=request.session.get("login_user_name", ""),
                )
        else:
            interview = InPersonInterview.objects.create(
                **payload,
                attachment_name=payload.get("attachment_name", ""),
            )
            messages.success(request, "In person interview scheduled successfully.")
            if payload["interview_owner"]:
                create_notifications(
                    payload["interview_owner"],
                    title="Interview assigned",
                    message=f"In-person interview scheduled for {candidate.full_name}.",
                    link=f"/applicant-tracking/interview-scheduling/in-person/?edit_id={interview.id}",
                    source="interview",
                    created_by=request.session.get("login_user_name", ""),
                )
        ApplicationPipelineCandidate.objects.get_or_create(
            candidate=candidate,
            job_applied=interview.posting_title or candidate.applied_position,
            defaults={"stage": "Interview"},
        )
        _set_application_stage_by_title(candidate, interview.posting_title, "Interview")

        sync_result = sync_interview_calendar_event(interview, candidate, meeting_link="", is_video=False)
        if sync_result.ok:
            interview.calendar_event_id = sync_result.event_id or interview.calendar_event_id
            interview.calendar_sync_error = ""
            interview.save(update_fields=["calendar_event_id", "calendar_sync_error"])
        else:
            interview.calendar_sync_error = sync_result.error or ""
            interview.save(update_fields=["calendar_sync_error"])
            if not sync_result.skipped:
                messages.warning(request, f"Calendar sync failed: {sync_result.error}")
        return redirect("applicant_tracking:in_person_interview")

    prefill_candidate_id = request.GET.get("candidate_id", "").strip()
    edit_id = request.GET.get("edit_id", "").strip()
    edit_record = InPersonInterview.objects.select_related("candidate").filter(id=edit_id).first() if edit_id else None
    if edit_record and not _can_access_interview(request, edit_record):
        messages.error(request, "Access denied for this interview.")
        return redirect("applicant_tracking:in_person_interview")
    prefill_form_data = {}
    if edit_record:
        prefill_form_data = {
            "record_id": edit_record.id,
            "candidate_name": edit_record.candidate.candidate_id,
            "posting_title": edit_record.posting_title,
            "interview_process_name": edit_record.interview_process_name,
            "client_name": edit_record.client_name,
            "date": edit_record.date.isoformat() if edit_record.date else "",
            "from_time": edit_record.from_time.strftime("%H:%M") if edit_record.from_time else "",
            "to_time": edit_record.to_time.strftime("%H:%M") if edit_record.to_time else "",
            "location": edit_record.location,
            "interview_owner": edit_record.interview_owner,
            "schedule_comments": edit_record.schedule_comments,
            "assessment_name": edit_record.assessment_name,
        }
    elif prefill_candidate_id:
        candidate = Candidate.objects.filter(candidate_id=prefill_candidate_id).first()
        if candidate:
            prefill_form_data["candidate_name"] = candidate.candidate_id
            prefill_form_data["posting_title"] = candidate.applied_position or ""
            prefill_form_data["interview_process_name"] = ""

    show_form = request.GET.get("create") == "1" or bool(edit_record)
    template_name = "applicant_tracking/in_person_interview_form.html" if show_form else "applicant_tracking/in_person_interview_dashboard.html"
    return render(
        request,
        template_name,
        {
            "rows": _serialize_interviews(filter_name=current_user, is_admin=is_admin),
            "show_form": show_form,
            "form_data": prefill_form_data,
            **option_context,
        },
    )


def video_interview_view(request):
    option_context = _in_person_form_options()
    current_user = _login_user_name(request)
    is_admin = _is_admin_request(request)
    enabled_integrations = list(
        InterviewIntegrationSetting.objects.filter(
            is_enabled=True,
            provider_key__in=["google_meet", "microsoft_teams", "zoom"],
        ).order_by("provider_label")
    )

    if request.method == "POST":
        record_id = request.POST.get("record_id", "").strip()
        edit_record = VideoInterviewSchedule.objects.select_related("candidate").filter(id=record_id).first() if record_id else None
        candidate_ref = request.POST.get("candidate_name", "").strip()
        candidate = Candidate.objects.filter(candidate_id=candidate_ref).first() or Candidate.objects.filter(
            full_name=candidate_ref
        ).first()
        if not candidate:
            messages.error(request, "Valid candidate is required.")
            return redirect("applicant_tracking:video_interview")

        provider_key = request.POST.get("provider", "").strip()
        provider_setting = next((item for item in enabled_integrations if item.provider_key == provider_key), None)
        if not provider_setting:
            messages.error(request, "Selected video provider is not enabled in Settings > Integration.")
            return redirect("applicant_tracking:video_interview")

        required = [
            request.POST.get("posting_title", "").strip(),
            request.POST.get("interviewer_name", "").strip(),
            request.POST.get("date", "").strip(),
            request.POST.get("from_time", "").strip(),
            request.POST.get("to_time", "").strip(),
            request.POST.get("interview_process_name", "").strip(),
        ]
        if any(not item for item in required):
            messages.error(request, "Please fill all mandatory fields.")
            return render(
                request,
                "applicant_tracking/video_interview.html",
                {
                    "rows": _serialize_video_interviews(filter_name=current_user, is_admin=is_admin),
                    "show_form": True,
                    "form_data": request.POST,
                    "enabled_integrations": enabled_integrations,
                    **option_context,
                },
            )

        manual_meeting_link = request.POST.get("manual_meeting_link", "").strip()
        if manual_meeting_link:
            if not manual_meeting_link.lower().startswith(("http://", "https://")):
                manual_meeting_link = f"https://{manual_meeting_link}"
            created_meeting = {
                "meeting_link": manual_meeting_link,
                "host_link": manual_meeting_link,
                "external_meeting_id": "",
                "provider_payload": {"mode": "manual_browser_link"},
            }
        else:
            try:
                created_meeting = create_provider_meeting(
                    provider_setting,
                    candidate,
                    request.POST.get("posting_title", "").strip(),
                    request.POST.get("date", "").strip(),
                    request.POST.get("from_time", "").strip(),
                    request.POST.get("to_time", "").strip(),
                )
            except MeetingServiceError as exc:
                messages.error(request, str(exc))
                return render(
                    request,
                    "applicant_tracking/video_interview.html",
                    {
                        "rows": _serialize_video_interviews(filter_name=current_user, is_admin=is_admin),
                        "show_form": True,
                        "form_data": request.POST,
                        "enabled_integrations": enabled_integrations,
                        **option_context,
                    },
                )
            except Exception as exc:
                messages.error(request, f"Meeting creation failed: {exc}")
                return render(
                    request,
                    "applicant_tracking/video_interview.html",
                    {
                        "rows": _serialize_video_interviews(filter_name=current_user, is_admin=is_admin),
                        "show_form": True,
                        "form_data": request.POST,
                        "enabled_integrations": enabled_integrations,
                        **option_context,
                    },
                )

        cc_selected = request.POST.getlist("cc_emails_multi")
        cc_manual = request.POST.get("cc_emails_manual", "").strip()
        cc_combined = _split_cc_emails(",".join(cc_selected + [cc_manual]))

        if edit_record:
            interview = edit_record
            previous_owner = (interview.interview_owner or "").strip()
            previous_interviewer = (interview.interviewer_name or "").strip()
            interview.candidate = candidate
            interview.interview_process_name = request.POST.get("interview_process_name", "").strip()
            interview.posting_title = request.POST.get("posting_title", "").strip()
            interview.interviewer_name = request.POST.get("interviewer_name", "").strip()
            interview.provider = provider_key
            interview.meeting_link = created_meeting["meeting_link"]
            interview.host_link = created_meeting.get("host_link", "")
            interview.external_meeting_id = created_meeting.get("external_meeting_id", "")
            interview.provider_payload = json.dumps(created_meeting.get("provider_payload") or {})
            interview.date = request.POST.get("date")
            interview.from_time = request.POST.get("from_time")
            interview.to_time = request.POST.get("to_time")
            interview.interview_owner = request.POST.get("interview_owner", "").strip()
            interview.schedule_comments = request.POST.get("schedule_comments", "").strip()
            interview.cc_emails = ", ".join(cc_combined)
            interview.save()
        else:
            interview = VideoInterviewSchedule.objects.create(
                candidate=candidate,
                interview_process_name=request.POST.get("interview_process_name", "").strip(),
                posting_title=request.POST.get("posting_title", "").strip(),
                interviewer_name=request.POST.get("interviewer_name", "").strip(),
                provider=provider_key,
                meeting_link=created_meeting["meeting_link"],
                host_link=created_meeting.get("host_link", ""),
                external_meeting_id=created_meeting.get("external_meeting_id", ""),
                provider_payload=json.dumps(created_meeting.get("provider_payload") or {}),
                date=request.POST.get("date"),
                from_time=request.POST.get("from_time"),
                to_time=request.POST.get("to_time"),
                interview_owner=request.POST.get("interview_owner", "").strip(),
                schedule_comments=request.POST.get("schedule_comments", "").strip(),
                cc_emails=", ".join(cc_combined),
            )
        logger.info(
            "Video interview link stored for Open Link button (interview_id=%s, candidate=%s): %s",
            interview.id,
            candidate.candidate_id,
            interview.meeting_link,
        )
        print(
            f"[VideoInterview] Open Link stored (interview_id={interview.id}, candidate={candidate.candidate_id}): {interview.meeting_link}"
        )
        ApplicationPipelineCandidate.objects.get_or_create(
            candidate=candidate,
            job_applied=interview.posting_title or candidate.applied_position,
            defaults={"stage": "Interview"},
        )
        _set_application_stage_by_title(candidate, interview.posting_title, "Interview")
        email_status, email_error = _send_candidate_video_invite(candidate, interview, provider_setting.provider_label)
        interview.email_delivery_status = email_status
        interview.email_delivery_error = email_error
        interview.email_sent_at = timezone.now() if email_status == "Sent" else None
        interview.save(update_fields=["email_delivery_status", "email_delivery_error", "email_sent_at"])

        sync_result = sync_interview_calendar_event(
            interview,
            candidate,
            meeting_link=interview.meeting_link,
            is_video=True,
        )
        if sync_result.ok:
            interview.calendar_event_id = sync_result.event_id or interview.calendar_event_id
            interview.calendar_sync_error = ""
            interview.save(update_fields=["calendar_event_id", "calendar_sync_error"])
        else:
            interview.calendar_sync_error = sync_result.error or ""
            interview.save(update_fields=["calendar_sync_error"])
            if not sync_result.skipped:
                messages.warning(request, f"Calendar sync failed: {sync_result.error}")
        if email_status != "Sent":
            messages.warning(request, f"Interview scheduled, but candidate email could not be sent: {email_error}")
        messages.success(
            request,
            "Video interview updated successfully." if edit_record else "Video interview scheduled successfully.",
        )
        current_owner = (interview.interview_owner or "").strip()
        current_interviewer = (interview.interviewer_name or "").strip()
        recipients = []
        if edit_record:
            if current_owner and current_owner != previous_owner:
                recipients.append(current_owner)
            if current_interviewer and current_interviewer != previous_interviewer:
                recipients.append(current_interviewer)
        else:
            recipients = [name for name in [current_owner, current_interviewer] if name]
        if recipients:
            create_notifications(
                normalize_recipients(recipients),
                title="Interview assigned",
                message=f"Video interview scheduled for {candidate.full_name}.",
                link=f"/applicant-tracking/interview-scheduling/video/?edit_id={interview.id}",
                source="interview",
                created_by=request.session.get("login_user_name", ""),
            )
        return redirect("applicant_tracking:video_interview")

    prefill_candidate_id = request.GET.get("candidate_id", "").strip()
    edit_id = request.GET.get("edit_id", "").strip()
    edit_record = VideoInterviewSchedule.objects.select_related("candidate").filter(id=edit_id).first() if edit_id else None
    if edit_record and not _can_access_interview(request, edit_record):
        messages.error(request, "Access denied for this interview.")
        return redirect("applicant_tracking:video_interview")
    prefill_form_data = {}
    if edit_record:
        prefill_form_data = {
            "record_id": edit_record.id,
            "candidate_name": edit_record.candidate.candidate_id,
            "interview_process_name": edit_record.interview_process_name,
            "posting_title": edit_record.posting_title,
            "interviewer_name": edit_record.interviewer_name,
            "provider": edit_record.provider,
            "manual_meeting_link": edit_record.meeting_link,
            "date": edit_record.date.isoformat() if edit_record.date else "",
            "from_time": edit_record.from_time.strftime("%H:%M") if edit_record.from_time else "",
            "to_time": edit_record.to_time.strftime("%H:%M") if edit_record.to_time else "",
            "interview_owner": edit_record.interview_owner,
            "schedule_comments": edit_record.schedule_comments,
            "cc_emails": edit_record.cc_emails,
            "cc_emails_list": _split_cc_emails(edit_record.cc_emails),
        }
    elif prefill_candidate_id:
        candidate = Candidate.objects.filter(candidate_id=prefill_candidate_id).first()
        if candidate:
            prefill_form_data["candidate_name"] = candidate.candidate_id
            prefill_form_data["posting_title"] = candidate.applied_position or ""

    show_form = request.GET.get("create") == "1" or bool(edit_record)
    if not prefill_form_data.get("cc_emails_list"):
        selected_multi = request.POST.getlist("cc_emails_multi") if hasattr(request, "POST") else []
        manual_value = request.POST.get("cc_emails_manual", "") if hasattr(request, "POST") else ""
        prefill_form_data["cc_emails_list"] = _split_cc_emails(",".join(selected_multi + [manual_value]))

    # Fetch real recordings
    recording_records = []
    if InterviewRecording:
        query = InterviewRecording.objects.select_related("candidate").order_by("-created_at")[:12]
        for item in query:
            recording_records.append({
                "id": item.id,
                "candidate_name": item.candidate.full_name,
                "posting_title": item.candidate.applied_position or "General Protocol",
                "date": item.created_at.strftime("%b %d, %Y"),
                "dominant_emotion": item.dominant_emotion or "Neutral",
                "sentiment_score": item.sentiment_score,
                "video_file_name": item.video_file_name,
            })

    template_name = "applicant_tracking/video_interview_form.html" if show_form else "applicant_tracking/video_interview_dashboard.html"
    return render(
        request,
        template_name,
        {
            "rows": _serialize_video_interviews(filter_name=current_user, is_admin=is_admin),
            "show_form": show_form,
            "form_data": prefill_form_data,
            "enabled_integrations": enabled_integrations,
            "recording_records": recording_records,
            **option_context,
        },
    )


def _serialize_interviews(filter_name="", is_admin=False):
    rows = []
    query = InPersonInterview.objects.select_related("candidate").order_by("-created_at")
    if filter_name and not is_admin:
        query = query.filter(
            Q(interview_owner__iexact=filter_name)
            | Q(interviewer_name__iexact=filter_name)
        )
    for item in query:
        req_id = item.manpower_requisition_id or f"MPR{item.id:04d}"
        candidate_label = item.candidate.full_name or item.candidate.candidate_id
        rows.append(
            {
                "id": item.id,
                "manpower_requisition_id": req_id,
                "candidate_name": candidate_label,
                "interview_process_name": item.interview_process_name,
                "posting_title": item.posting_title,
                "interviewer_name": item.interviewer_name,
                "date": item.date,
                "from_time": item.from_time,
                "to_time": item.to_time,
                "location": item.location,
                "client_name": item.client_name,
                "interview_owner": item.interview_owner,
                "assessment_name": item.assessment_name,
                "attachment_name": item.attachment_name,
            }
        )
    return rows


def in_person_interview_delete_confirm_view(request, record_id):
    record = get_object_or_404(InPersonInterview.objects.select_related("candidate"), id=record_id)
    if not _is_admin_request(request):
        messages.error(request, "Only admin can delete this interview.")
        return redirect("applicant_tracking:in_person_interview")
    if not _can_access_interview(request, record):
        messages.error(request, "Access denied for this interview.")
        return redirect("applicant_tracking:in_person_interview")
    if request.method == "POST":
        if request.POST.get("action") == "confirm_delete":
            record.delete()
            messages.success(request, "In person interview deleted.")
        return redirect("applicant_tracking:in_person_interview")
    return render(request, "applicant_tracking/in_person_interview_delete_confirm.html", {"record": record})


def _serialize_video_interviews(filter_name="", is_admin=False):
    rows = []
    provider_map = dict(VideoInterviewSchedule.PROVIDER_CHOICES)
    query = VideoInterviewSchedule.objects.select_related("candidate").order_by("-created_at")
    if filter_name and not is_admin:
        query = query.filter(
            Q(interview_owner__iexact=filter_name)
            | Q(interviewer_name__iexact=filter_name)
        )
    for item in query:
        req_id = item.manpower_requisition_id or f"MPR{item.id:04d}"
        candidate_label = item.candidate.full_name or item.candidate.candidate_id
        rows.append(
            {
                "id": item.id,
                "manpower_requisition_id": req_id,
                "candidate_db_id": item.candidate.id,
                "candidate_id": item.candidate.candidate_id,
                "candidate_name": candidate_label,
                "interview_process_name": item.interview_process_name,
                "posting_title": item.posting_title,
                "interviewer_name": item.interviewer_name,
                "provider": provider_map.get(item.provider, item.provider),
                "interview_process_name": item.interview_process_name,
                "meeting_link": item.meeting_link,
                "host_link": item.host_link,
                "external_meeting_id": item.external_meeting_id,
                "email_delivery_status": item.email_delivery_status,
                "email_delivery_error": item.email_delivery_error,
                "date": item.date,
                "from_time": item.from_time,
                "to_time": item.to_time,
            "interview_owner": item.interview_owner,
            "cc_emails": item.cc_emails,
        }
        )
    return rows


def _serialize_login_interviews(filter_name="", is_admin=False):
    rows = []
    query = LoginInterviewSchedule.objects.select_related("candidate").order_by("-created_at")
    if filter_name and not is_admin:
        query = query.filter(Q(interview_owner__iexact=filter_name) | Q(interviewer_name__iexact=filter_name))
    for item in query:
        req_id = item.manpower_requisition_id or f"MPR{item.id:04d}"
        candidate_label = item.candidate.full_name or item.candidate.candidate_id
        rows.append(
            {
                "id": item.id,
                "manpower_requisition_id": req_id,
                "candidate_db_id": item.candidate.id,
                "candidate_id": item.candidate.candidate_id,
                "candidate_name": candidate_label,
                "interview_process_name": item.interview_process_name,
                "posting_title": item.posting_title,
                "interviewer_name": item.interviewer_name,
                "client_name": item.client_name,
                "login_url": item.login_url,
                "date": item.date,
                "from_time": item.from_time,
                "to_time": item.to_time,
                "interview_owner": item.interview_owner,
                "assessment_name": item.assessment_name,
            }
        )
    return rows


def video_interview_delete_confirm_view(request, record_id):
    record = get_object_or_404(VideoInterviewSchedule.objects.select_related("candidate"), id=record_id)
    if not _is_admin_request(request):
        messages.error(request, "Only admin can delete this interview.")
        return redirect("applicant_tracking:video_interview")
    if not _can_access_interview(request, record):
        messages.error(request, "Access denied for this interview.")
        return redirect("applicant_tracking:video_interview")
    if request.method == "POST":
        if request.POST.get("action") == "confirm_delete":
            record.delete()
            messages.success(request, "Video interview deleted.")
        return redirect("applicant_tracking:video_interview")
    return render(request, "applicant_tracking/video_interview_delete_confirm.html", {"record": record})


def login_interview_delete_confirm_view(request, record_id):
    record = get_object_or_404(LoginInterviewSchedule.objects.select_related("candidate"), id=record_id)
    if not _is_admin_request(request):
        messages.error(request, "Only admin can delete this interview.")
        return redirect("applicant_tracking:login_interview")
    if not _can_access_interview(request, record):
        messages.error(request, "Access denied for this interview.")
        return redirect("applicant_tracking:login_interview")
    if request.method == "POST":
        if request.POST.get("action") == "confirm_delete":
            record.delete()
            messages.success(request, "Log in interview deleted.")
        return redirect("applicant_tracking:login_interview")
    return render(request, "applicant_tracking/login_interview_delete_confirm.html", {"record": record})


def login_interview_view(request):
    option_context = _in_person_form_options()
    current_user = _login_user_name(request)
    is_admin = _is_admin_request(request)

    if request.method == "POST":
        record_id = (request.POST.get("record_id") or "").strip()
        edit_record = (
            LoginInterviewSchedule.objects.select_related("candidate").filter(id=record_id).first() if record_id else None
        )
        if edit_record and not _can_access_interview(request, edit_record):
            messages.error(request, "Access denied for this interview.")
            return redirect("applicant_tracking:login_interview")

        candidate_ref = request.POST.get("candidate_name", "").strip()
        candidate = Candidate.objects.filter(candidate_id=candidate_ref).first() or Candidate.objects.filter(
            full_name=candidate_ref
        ).first()
        if not candidate:
            messages.error(request, "Valid candidate is required.")
            return redirect("applicant_tracking:login_interview")

        required = [
            request.POST.get("posting_title", "").strip(),
            request.POST.get("interviewer_name", "").strip(),
            request.POST.get("date", "").strip(),
            request.POST.get("from_time", "").strip(),
            request.POST.get("to_time", "").strip(),
            request.POST.get("interview_process_name", "").strip(),
        ]
        if any(not item for item in required):
            messages.error(request, "Please fill all mandatory fields.")
            return render(
                request,
                "applicant_tracking/login_interview_form.html",
                {
                    "rows": _serialize_login_interviews(filter_name=current_user, is_admin=is_admin),
                    "show_form": True,
                    "form_data": request.POST,
                    **option_context,
                },
            )

        payload = {
            "candidate": candidate,
            "interview_process_name": request.POST.get("interview_process_name", "").strip(),
            "posting_title": request.POST.get("posting_title", "").strip(),
            "interviewer_name": request.POST.get("interviewer_name", "").strip(),
            "client_name": request.POST.get("client_name", "").strip(),
            "login_url": request.POST.get("login_url", "").strip(),
            "access_notes": request.POST.get("access_notes", "").strip(),
            "date": request.POST.get("date"),
            "from_time": request.POST.get("from_time"),
            "to_time": request.POST.get("to_time"),
            "interview_owner": request.POST.get("interview_owner", "").strip(),
            "schedule_comments": request.POST.get("schedule_comments", "").strip(),
            "assessment_name": request.POST.get("assessment_name", "").strip(),
        }

        if edit_record:
            for key, value in payload.items():
                setattr(edit_record, key, value)
            edit_record.save()
            messages.success(request, "Log in interview updated.")
        else:
            LoginInterviewSchedule.objects.create(**payload)
            messages.success(request, "Log in interview scheduled.")
        return redirect("applicant_tracking:login_interview")

    prefill_candidate_id = request.GET.get("candidate_id", "").strip()
    edit_id = request.GET.get("edit_id", "").strip()
    edit_record = (
        LoginInterviewSchedule.objects.select_related("candidate").filter(id=edit_id).first() if edit_id else None
    )
    if edit_record and not _can_access_interview(request, edit_record):
        messages.error(request, "Access denied for this interview.")
        return redirect("applicant_tracking:login_interview")

    prefill_form_data = {}
    if edit_record:
        prefill_form_data = {
            "record_id": edit_record.id,
            "candidate_name": edit_record.candidate.candidate_id,
            "posting_title": edit_record.posting_title,
            "interview_process_name": edit_record.interview_process_name,
            "client_name": edit_record.client_name,
            "login_url": edit_record.login_url,
            "access_notes": edit_record.access_notes,
            "interviewer_name": edit_record.interviewer_name,
            "date": edit_record.date.isoformat() if edit_record.date else "",
            "from_time": edit_record.from_time.strftime("%H:%M") if edit_record.from_time else "",
            "to_time": edit_record.to_time.strftime("%H:%M") if edit_record.to_time else "",
            "interview_owner": edit_record.interview_owner,
            "schedule_comments": edit_record.schedule_comments,
            "assessment_name": edit_record.assessment_name,
        }
    elif prefill_candidate_id:
        candidate = Candidate.objects.filter(candidate_id=prefill_candidate_id).first()
        if candidate:
            prefill_form_data["candidate_name"] = candidate.candidate_id
            prefill_form_data["posting_title"] = candidate.applied_position or ""

    show_form = request.GET.get("create") == "1" or bool(edit_record)
    template_name = (
        "applicant_tracking/login_interview_form.html"
        if show_form
        else "applicant_tracking/login_interview_dashboard.html"
    )
    return render(
        request,
        template_name,
        {
            "rows": _serialize_login_interviews(filter_name=current_user, is_admin=is_admin),
            "show_form": show_form,
            "form_data": prefill_form_data,
            **option_context,
        },
    )


def _serialize_assessment_assignments(*, request, filter_name: str, is_admin: bool):
    qs = CandidateAssessmentAssignment.objects.select_related("candidate", "assessment_form", "submission")
    if not is_admin and filter_name:
        qs = qs.filter(assigned_by__iexact=filter_name)
    rows = []
    for row in qs.order_by("-assigned_at")[:500]:
        submission = getattr(row, "submission", None)
        passing_percent = getattr(row.assessment_form, "passing_score_percent", None)
        score_value = getattr(submission, "score", None)
        max_score_value = getattr(submission, "max_score", None)
        score_percent = None
        pass_fail = ""
        try:
            if score_value is not None and max_score_value not in (None, 0):
                score_percent = round((float(score_value) / float(max_score_value)) * 100.0, 2)
        except Exception:
            score_percent = None
        try:
            if score_percent is not None and passing_percent not in (None, ""):
                pass_fail = "Pass" if float(score_percent) >= float(passing_percent) else "Fail"
        except Exception:
            pass_fail = ""

        assignment_url = ""
        try:
            assignment_url = request.build_absolute_uri(
                reverse("candidate_portal:assessment_form", kwargs={"token": row.token})
            )
        except Exception:
            assignment_url = ""
        rows.append(
            {
                "id": row.id,
                "candidate_id": row.candidate.candidate_id,
                "candidate_name": row.candidate.full_name,
                "candidate_email": row.candidate.email,
                "assessment_name": row.assessment_form.name,
                "assessment_published": bool(getattr(row.assessment_form, "is_published", False)),
                "passing_score_percent": passing_percent,
                "assigned_by": row.assigned_by,
                "assigned_at": row.assigned_at,
                "due_at": row.due_at,
                "status": row.status,
                "score": score_value,
                "max_score": max_score_value,
                "score_percent": score_percent,
                "pass_fail": pass_fail,
                "submitted_at": getattr(submission, "submitted_at", None),
                "token": str(row.token),
                "assignment_url": assignment_url,
            }
        )
    return rows


def assessment_assignments_view(request):
    current_user = _login_user_name(request)
    is_admin = _is_admin_request(request)

    if request.method == "POST":
        candidate_id = (request.POST.get("candidate_id") or "").strip()
        form_id = (request.POST.get("assessment_form_id") or "").strip()
        due_at_raw = (request.POST.get("due_at") or "").strip()

        candidate = Candidate.objects.filter(candidate_id=candidate_id).first() if candidate_id else None
        assessment_form = AssessmentForm.objects.filter(id=form_id).first() if form_id else None

        if not candidate or not assessment_form:
            messages.error(request, "Please select candidate and assessment form.")
            return redirect("applicant_tracking:assessment_assignments")

        if not getattr(assessment_form, "is_published", False):
            messages.error(request, "This form is not published yet. Please publish it in Settings → Assessments Wizard.")
            return redirect("applicant_tracking:assessment_assignments")

        due_at = None
        if due_at_raw:
            try:
                due_at = datetime.fromisoformat(due_at_raw)
                if timezone.is_naive(due_at):
                    due_at = timezone.make_aware(due_at, timezone.get_current_timezone())
            except Exception:
                due_at = None

        assignment = CandidateAssessmentAssignment.objects.create(
            candidate=candidate,
            assessment_form=assessment_form,
            assigned_by=current_user,
            due_at=due_at,
            source_type="interview_scheduling",
        )
        assignment_url = request.build_absolute_uri(
            reverse("candidate_portal:assessment_form", kwargs={"token": assignment.token})
        )

        # UI notifications (candidate + assigner)
        _create_ui_notification(
            recipient=candidate.email,
            title="New assessment assigned",
            message=f"Assessment: {assessment_form.name}",
            link=assignment_url,
            source="assessment",
        )
        _create_ui_notification(
            recipient=current_user,
            title="Assessment assigned",
            message=f"{assessment_form.name} assigned to {candidate.full_name} ({candidate.candidate_id})",
            link=request.build_absolute_uri(reverse("applicant_tracking:assessment_assignments")),
            source="assessment",
        )

        delivery_status, delivery_error = _send_assessment_assignment_email(
            request=request,
            candidate=candidate,
            assessment_name=assessment_form.name,
            assignment_url=assignment_url,
        )
        if delivery_status == "Sent":
            messages.success(request, f"Assessment link sent to {candidate.full_name}.")
        elif delivery_status == "Skipped":
            messages.warning(request, "Assessment assigned, but email was skipped (candidate email missing).")
        else:
            messages.warning(request, f"Assessment assigned, but email failed: {delivery_error}")

        return redirect("applicant_tracking:assessment_assignments")

    candidate_options = [
        {"id": c.candidate_id, "name": c.full_name, "posting": c.applied_position or ""}
        for c in Candidate.objects.order_by("candidate_id")
    ]
    assessment_forms = list(AssessmentForm.objects.order_by("name").values("id", "name", "description", "form_type", "is_published"))

    show_form = request.GET.get("create") == "1"
    template_name = (
        "applicant_tracking/assessment_assignment_form.html"
        if show_form
        else "applicant_tracking/assessment_assignment_dashboard.html"
    )
    return render(
        request,
        template_name,
        {
            "rows": _serialize_assessment_assignments(request=request, filter_name=current_user, is_admin=is_admin),
            "show_form": show_form,
            "candidate_options": candidate_options,
            "assessment_forms": assessment_forms,
        },
    )


def _in_person_form_options():
    candidate_options = [
        {"id": c.candidate_id, "name": c.full_name, "posting": c.applied_position or ""}
        for c in Candidate.objects.order_by("candidate_id")
    ]
    candidate_postings = {item["posting"] for item in candidate_options if item["posting"]}
    requisition_postings = set(
        JobRequisition.objects.exclude(title__exact="")
        .values_list("title", flat=True)
    )
    posting_options = sorted(candidate_postings | requisition_postings)
    process_options = INTERVIEW_ROUND_OPTIONS
    client_options = list(
        CompanyInfo.objects.exclude(company_name__exact="")
        .order_by("company_name")
        .values_list("company_name", flat=True)
    )
    allowed_owner_roles = [
        "Super Admin",
        "Admin",
        "HR Manager",
        "Recruiter",
        "Team Lead",
        "Interviewer",
        "Hiring Manager",
    ]
    owner_options = list(
        UserMaster.objects.exclude(full_name__exact="")
        .filter(role__in=allowed_owner_roles)
        .order_by("full_name")
        .values_list("full_name", flat=True)
    )
    assessment_options = list(
        AssessmentForm.objects.exclude(name__exact="")
        .order_by("name")
        .values_list("name", flat=True)
    )
    return {
        "candidate_options": candidate_options,
        "posting_options": posting_options,
        "process_options": process_options,
        "client_options": client_options,
        "owner_options": owner_options,
        "interviewer_options": owner_options,
        "assessment_options": assessment_options,
        "cc_role_options": _cc_role_user_options(),
    }
